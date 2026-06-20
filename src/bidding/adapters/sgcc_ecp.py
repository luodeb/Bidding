from __future__ import annotations

import asyncio
import base64
import json
import re
from datetime import date, datetime
from typing import AsyncIterator

import structlog
from playwright.async_api import BrowserContext, Page

from bidding.adapters.base import AdapterMeta, SiteAdapter
from bidding.adapters.registry import register
from bidding.models.enums import NoticeType, ProcurementMethod, ProjectCategory
from bidding.models.schema import BidNotice

logger = structlog.get_logger()

_BASE_URL = "https://ecp.sgcc.com.cn"
_PORTAL = f"{_BASE_URL}/ecp2.0/portal"
_API = f"{_BASE_URL}/ecp2.0/ecpwcmcore//index"

_MENU_IDS: dict[NoticeType, str] = {
    NoticeType.BID_ANNOUNCEMENT: "2018032700291334",
    NoticeType.PREQUALIFICATION: "2018032700290425",
    NoticeType.NON_BID_ANNOUNCEMENT: "2018032900295987",
    NoticeType.CANDIDATE_PUBLICITY: "2018060501171107",
    NoticeType.WIN_ANNOUNCEMENT: "2018060501171111",
}

_DOC_TYPES: dict[NoticeType, str] = {
    NoticeType.BID_ANNOUNCEMENT: "doci-bid",
    NoticeType.PREQUALIFICATION: "doci-bid",
    NoticeType.NON_BID_ANNOUNCEMENT: "doci-bid",
    NoticeType.CANDIDATE_PUBLICITY: "doci-win",
    NoticeType.WIN_ANNOUNCEMENT: "doci-win",
}

_DETAIL_APIS: dict[str, str] = {
    "doci-bid": f"{_API}/getNoticeBid",
    "doci-win": f"{_API}/getNoticeWin",
}

_FILE_APIS: dict[str, str] = {
    "doci-win": f"{_API}/getWinFile",
}

_PUR_TYPE_MAP: dict[str, ProjectCategory] = {
    "物资": ProjectCategory.GOODS,
    "工程": ProjectCategory.ENGINEERING,
    "服务": ProjectCategory.SERVICE,
}


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _parse_datetime(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def _clean_html(text: str | None) -> str | None:
    if not text:
        return None
    clean = re.sub(r"<[^>]+>", "", text)
    return clean.strip() or None


@register
class SgccEcpAdapter(SiteAdapter):
    meta = AdapterMeta(
        name="sgcc_ecp",
        display_name="国家电网ECP",
        base_url=_BASE_URL,
        notice_types=[
            NoticeType.BID_ANNOUNCEMENT,
            NoticeType.NON_BID_ANNOUNCEMENT,
            NoticeType.WIN_ANNOUNCEMENT,
            NoticeType.CANDIDATE_PUBLICITY,
        ],
        requires_login=False,
        rate_limit=1.0,
    )

    async def _api_post(self, page: Page, url: str, body: dict | str) -> dict | None:
        result = await page.evaluate(
            """async ([url, body]) => {
                const r = await fetch(url, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(body),
                });
                return await r.text();
            }""",
            [url, body],
        )
        try:
            data = json.loads(result)
            if data.get("successful"):
                return data.get("resultValue")
            logger.warning("sgcc_ecp.api_error", url=url, hint=data.get("resultHint"))
            return None
        except json.JSONDecodeError:
            logger.error("sgcc_ecp.json_error", url=url, body=result[:200])
            return None

    async def scrape_list(
        self, page: Page, notice_type: NoticeType
    ) -> AsyncIterator[BidNotice]:
        menu_id = _MENU_IDS.get(notice_type)
        if not menu_id:
            return

        await page.goto(
            f"{_PORTAL}/#/portal/home",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await asyncio.sleep(3)

        page_index = 1
        page_size = 20
        total_fetched = 0

        while True:
            body = {
                "index": page_index,
                "size": page_size,
                "firstPageMenuId": menu_id,
                "purOrgStatus": "",
                "purOrgCode": "",
                "purType": "",
                "noticeType": "",
                "orgId": "",
                "key": "",
                "orgName": "",
            }

            rv = await self._api_post(page, f"{_API}/noteList", body)
            if not rv:
                break

            items = rv.get("noteList", [])
            if not items:
                break

            total_count = rv.get("count", 0)
            logger.info(
                "sgcc_ecp.list_page",
                notice_type=notice_type.value,
                page=page_index,
                items=len(items),
                total=total_count,
            )

            for item in items:
                notice = await self._process_item(page, item, notice_type)
                if notice:
                    yield notice
                    total_fetched += 1

                await asyncio.sleep(self.meta.rate_limit)

            if len(items) < page_size:
                break

            page_index += 1
            if page_index > 5:
                break

    async def _download_bid_zip(self, page: Page, notice_id: str) -> bytes | None:
        """Download the announcement ZIP file via fetch and return raw bytes."""
        try:
            result = await page.evaluate(
                """async (noticeId) => {
                    const resp = await fetch(
                        '/ecp2.0/ecpwcmcore//index/downLoadBid?noticeId=' + noticeId + '&noticeDetId='
                    );
                    if (!resp.ok) return null;
                    const buf = await resp.arrayBuffer();
                    if (buf.byteLength < 100) return null;
                    const bytes = new Uint8Array(buf);
                    let binary = '';
                    const chunk = 8192;
                    for (let i = 0; i < bytes.length; i += chunk) {
                        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
                    }
                    return btoa(binary);
                }""",
                notice_id,
            )
            if result:
                return base64.b64decode(result)
            return None
        except Exception:
            logger.warning("sgcc_ecp.download_failed", notice_id=notice_id)
            return None

    async def _extract_doc_from_zip(self, zip_data: bytes) -> tuple[str | None, str | None]:
        from bidding.utils.doc import extract_text_from_zip

        return extract_text_from_zip(zip_data)

    async def _process_item(
        self, page: Page, item: dict, notice_type: NoticeType
    ) -> BidNotice | None:
        title = (item.get("title") or "").strip()
        if not title:
            return None

        notice_id = str(item.get("noticeId", ""))
        menu_id = str(item.get("firstPageMenuId", ""))
        doctype = item.get("doctype", _DOC_TYPES.get(notice_type, "doci-bid"))

        source_url = f"{_PORTAL}/#/doc/{doctype}/{notice_id}_{menu_id}"
        publish_date = _parse_date(item.get("noticePublishTime"))

        detail = await self._fetch_detail(page, notice_id, doctype)
        content_parts = []
        deadline = None
        purchaser = item.get("publishOrgName")
        agency = None
        agency_contact = None
        project_category = None
        code = item.get("code")
        winner = None
        win_amount = None
        content_html = None

        if detail:
            notice_data = detail.get("notice", {})

            purchaser = notice_data.get("BID_ORG") or notice_data.get("ORG_NAME") or purchaser
            agency = notice_data.get("BID_AGT") or notice_data.get("bidagtName")
            contact = notice_data.get("CONTACT")
            tel = notice_data.get("TEL")
            email = notice_data.get("E_MAIL")
            if contact or tel:
                agency_contact = " ".join(filter(None, [contact, tel, email]))

            deadline = _parse_datetime(notice_data.get("OPENBID_TIME"))
            bidbook_end = _parse_datetime(notice_data.get("BIDBOOK_BUY_END_TIME"))
            if not deadline and bidbook_end:
                deadline = bidbook_end

            pur_type_name = notice_data.get("PUR_TYPE_NAME", "")
            for key, cat in _PUR_TYPE_MAP.items():
                if key in pur_type_name:
                    project_category = cat
                    break

            code = notice_data.get("PURPRJ_CODE") or code

            if notice_data.get("PRJ_INTRODUCE"):
                content_parts.append(f"项目介绍：{notice_data['PRJ_INTRODUCE']}")

            raw_html = notice_data.get("CONT")
            if raw_html:
                content_html = raw_html
                clean_text = _clean_html(raw_html)
                if clean_text:
                    content_parts.append(clean_text)

            if notice_data.get("OPENBID_ADDR"):
                content_parts.append(f"开标地点：{notice_data['OPENBID_ADDR']}")
            if notice_data.get("BID_AGT_ADDR"):
                content_parts.append(f"代理机构地址：{notice_data['BID_AGT_ADDR']}")
            if bidbook_end:
                content_parts.append(f"招标文件获取截止：{bidbook_end.strftime('%Y-%m-%d %H:%M')}")
            if deadline:
                content_parts.append(f"开标时间：{deadline.strftime('%Y-%m-%d %H:%M')}")

            bid_org_name = notice_data.get("bidOrgName") or notice_data.get("BID_ORG")
            if bid_org_name:
                winner = bid_org_name if notice_type == NoticeType.WIN_ANNOUNCEMENT else None

        attachments = []
        file_api = _FILE_APIS.get(doctype)
        if file_api:
            file_rv = await self._api_post(page, file_api, notice_id)
            if file_rv:
                files = file_rv.get("files", [])
                for f in files:
                    fname = f.get("FILE_NAME", "")
                    if fname:
                        attachments.append(fname)

        doc_path = None
        if doctype == "doci-bid":
            zip_data = await self._download_bid_zip(page, notice_id)
            if zip_data:
                saved_name, doc_text = await self._extract_doc_from_zip(zip_data)
                if saved_name:
                    doc_path = saved_name
                if doc_text:
                    content_parts.insert(0, doc_text)

        return BidNotice(
            title=title,
            source_site=self.meta.name,
            source_url=source_url,
            notice_type=notice_type,
            notice_id=code,
            publish_date=publish_date,
            deadline=deadline,
            project_category=project_category,
            purchaser=purchaser,
            agency=agency,
            agency_contact=agency_contact,
            content="\n".join(content_parts) if content_parts else None,
            content_html=content_html,
            attachments=attachments if attachments else [],
            winner=winner,
            raw_data=item,
        )

    async def _fetch_detail(
        self, page: Page, notice_id: str, doctype: str
    ) -> dict | None:
        api_url = _DETAIL_APIS.get(doctype)
        if not api_url:
            return None
        try:
            return await self._api_post(page, api_url, notice_id)
        except Exception:
            logger.warning("sgcc_ecp.detail_failed", notice_id=notice_id)
            return None

    async def scrape_detail(self, page: Page, url: str) -> BidNotice | None:
        return None
