from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from typing import AsyncIterator

import structlog
from playwright.async_api import BrowserContext, Page

from bidding.adapters.base import AdapterMeta, SiteAdapter
from bidding.adapters.registry import register
from bidding.models.enums import NoticeType, ProcurementMethod
from bidding.models.schema import BidNotice

logger = structlog.get_logger()

_METHOD_MAP = {
    "公开招标": ProcurementMethod.PUBLIC_BID,
    "邀请招标": ProcurementMethod.INVITED_BID,
    "询价采购": ProcurementMethod.INQUIRY,
    "竞价采购": ProcurementMethod.COMPETITIVE_PRICE,
    "竞争性谈判": ProcurementMethod.COMPETITIVE_TALK,
    "单一来源": ProcurementMethod.SOLE_SOURCE,
}

_NOTICE_TYPE_PARAMS = {
    NoticeType.BID_ANNOUNCEMENT: "0",
    NoticeType.NON_BID_ANNOUNCEMENT: "1",
}

_CWEME_BASE = "https://www.cweme.cn"
_PORTAL_BASE = "https://www.cdt-ec.com"


def _ts_to_date(ts: int | None) -> date | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts / 1000).date()


def _ts_to_datetime(ts: int | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts / 1000)


@register
class CdtEcAdapter(SiteAdapter):
    meta = AdapterMeta(
        name="cdt_ec",
        display_name="大唐集团",
        base_url=_PORTAL_BASE,
        notice_types=[
            NoticeType.BID_ANNOUNCEMENT,
            NoticeType.NON_BID_ANNOUNCEMENT,
        ],
        requires_login=False,
        rate_limit=1.5,
    )

    async def on_context_created(self, context: BrowserContext) -> None:
        pass

    async def _api_fetch(self, page: Page, url: str) -> str:
        return await page.evaluate(
            "async (url) => { const r = await fetch(url); return await r.text(); }",
            url,
        )

    async def scrape_list(
        self, page: Page, notice_type: NoticeType
    ) -> AsyncIterator[BidNotice]:
        # Navigate to cweme.cn to establish same-origin context for fetch()
        await page.goto(
            f"{_CWEME_BASE}/cweme-index/webpage/jsp/fzbggList.jsp",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await asyncio.sleep(3)

        nt = _NOTICE_TYPE_PARAMS.get(notice_type, "")
        url = f"{_CWEME_BASE}/potal-web/pendingGxnotice/selectall?pagesize=20"
        if nt:
            url += f"&noticeType={nt}"

        body = await self._api_fetch(page, url)
        try:
            items = json.loads(body)
        except json.JSONDecodeError:
            logger.error("cdt_ec.json_parse_failed", body_preview=body[:300])
            return

        if not items:
            return

        logger.info("cdt_ec.list", notice_type=notice_type.value, count=len(items))

        for i, item in enumerate(items):
            record_id = item.get("id")
            detail = await self._fetch_detail(page, record_id) if record_id else None
            merged = {**item, **(detail or {})}

            notice = self._parse_item(merged, notice_type)
            if notice:
                pdf_url = merged.get("pdf_url")
                if pdf_url:
                    pdf_filename, pdf_text = await self._extract_pdf(pdf_url)
                    if pdf_filename:
                        notice.pdf_path = pdf_filename
                    if pdf_text:
                        notice.content = pdf_text

                yield notice

            if (i + 1) % 10 == 0:
                await asyncio.sleep(self.meta.rate_limit)

    async def _fetch_detail(self, page: Page, record_id: int) -> dict | None:
        url = f"{_CWEME_BASE}/potal-web/pendingGxnotice/selectbyid?id={record_id}"
        try:
            body = await self._api_fetch(page, url)
            return json.loads(body)
        except Exception:
            logger.warning("cdt_ec.detail_failed", id=record_id)
            return None

    async def _extract_pdf(self, url: str) -> tuple[str | None, str | None]:
        from bidding.utils.pdf import download_and_extract_pdf

        return await download_and_extract_pdf(url)

    async def scrape_detail(self, page: Page, url: str) -> BidNotice | None:
        return None

    def _parse_item(self, item: dict, notice_type: NoticeType) -> BidNotice | None:
        title = (item.get("message_title") or "").strip()
        if not title:
            return None

        gg_id = item.get("gg_id")
        source_url = f"{_CWEME_BASE}/cweme-index/webpage/jsp/fzbggList.jsp"
        if gg_id:
            source_url = f"{_PORTAL_BASE}/tangyhtsso/bip/sso/auth?service={_CWEME_BASE}/cweme-index/webpage/jsp/fzbggDetail.jsp?id={gg_id}"

        attachments = []
        pdf_url = item.get("pdf_url")
        if pdf_url:
            attachments.append(pdf_url)

        method_str = item.get("pro_bidding_mothod") or ""
        method = _METHOD_MAP.get(method_str)

        content_parts = []
        if item.get("pro_overvier"):
            content_parts.append(f"项目概况：{item['pro_overvier']}")
        if item.get("pro_area"):
            content_parts.append(f"项目地区：{item['pro_area']}")
        if item.get("bid_tenderer"):
            content_parts.append(f"招标人：{item['bid_tenderer']}")
        if item.get("bid_address"):
            content_parts.append(f"招标人地址：{item['bid_address']}")
        if item.get("bid_agency"):
            content_parts.append(f"代理机构：{item['bid_agency']}")
        if item.get("bid_agency_address"):
            content_parts.append(f"代理机构地址：{item['bid_agency_address']}")
        if item.get("pro_quali_examin"):
            content_parts.append(f"资格审查：{item['pro_quali_examin']}")
        deadline = _ts_to_datetime(item.get("deadline"))
        if deadline:
            content_parts.append(f"投标截止时间：{deadline.strftime('%Y-%m-%d %H:%M')}")
        signup_url = item.get("signup_url")
        if signup_url:
            content_parts.append(f"报名链接：{signup_url}")
        if pdf_url:
            content_parts.append(f"公告文件：{pdf_url}")

        return BidNotice(
            title=title,
            source_site=self.meta.name,
            source_url=source_url,
            notice_type=notice_type,
            notice_id=item.get("message_no"),
            publish_date=_ts_to_date(item.get("publish_time")),
            deadline=deadline,
            procurement_method=method,
            purchaser=item.get("bid_tenderer"),
            agency=item.get("bid_agency"),
            project_name=item.get("pro_name") or None,
            project_location=item.get("pro_area"),
            content="\n".join(content_parts) if content_parts else None,
            attachments=attachments,
            raw_data=item,
        )
