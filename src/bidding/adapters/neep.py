from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime
from typing import AsyncIterator

import structlog
from playwright.async_api import Page

from bidding.adapters.base import AdapterMeta, SiteAdapter
from bidding.adapters.registry import register
from bidding.models.enums import NoticeType, ProcurementMethod
from bidding.models.schema import BidNotice

logger = structlog.get_logger()

_BASE_URL = "https://www.neep.shop"

_NOTICE_TYPES: dict[NoticeType, list[tuple[int, str, ProcurementMethod | None]]] = {
    NoticeType.NON_BID_ANNOUNCEMENT: [
        (1, "询价采购公告", ProcurementMethod.INQUIRY),
        (2, "竞争性谈判公告", ProcurementMethod.COMPETITIVE_TALK),
    ],
    NoticeType.WIN_ANNOUNCEMENT: [
        (4, "采购结果公告", None),
    ],
}


def _parse_datetime_ms(ts: int | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(ts / 1000)
    except (ValueError, OSError):
        return None


def _parse_date_str(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _clean_html(text: str | None) -> str | None:
    if not text:
        return None
    clean = re.sub(r"<[^>]+>", "", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean or None


@register
class NeepAdapter(SiteAdapter):
    meta = AdapterMeta(
        name="neep",
        display_name="国能e购",
        base_url=_BASE_URL,
        notice_types=[
            NoticeType.NON_BID_ANNOUNCEMENT,
            NoticeType.WIN_ANNOUNCEMENT,
        ],
        requires_login=False,
        rate_limit=0.5,
    )

    async def _jsonp_call(self, page: Page, params: dict) -> dict | None:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        result = await page.evaluate(
            """([qs]) => {
                return new Promise((resolve) => {
                    const cbName = 'cb_' + Math.random().toString(36).substr(2, 9);
                    window[cbName] = function(data) {
                        delete window[cbName];
                        resolve(JSON.stringify(data));
                    };
                    const script = document.createElement('script');
                    script.src = '/rest/service/routing/nouser/inquiry/quote/searchCmsArticleList?callback=' + cbName + '&' + qs;
                    script.onerror = function() {
                        delete window[cbName];
                        resolve(null);
                    };
                    document.head.appendChild(script);
                    setTimeout(() => {
                        delete window[cbName];
                        resolve(null);
                    }, 15000);
                });
            }""",
            [qs],
        )
        if not result:
            return None
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return None

    async def scrape_list(
        self, page: Page, notice_type: NoticeType
    ) -> AsyncIterator[BidNotice]:
        sub_types = _NOTICE_TYPES.get(notice_type)
        if not sub_types:
            return

        await page.goto(
            f"{_BASE_URL}/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await asyncio.sleep(3)

        for api_type, type_label, procurement_method in sub_types:
            logger.info(
                "neep.scrape_subtype",
                notice_type=notice_type.value,
                sub_type=type_label,
                api_type=api_type,
            )
            page_no = 1
            while True:
                rv = await self._jsonp_call(
                    page,
                    {
                        "noticeType": api_type,
                        "pageNo": page_no,
                        "pageSize": 20,
                    },
                )
                if not rv or rv.get("respCode") != "0000":
                    logger.warning("neep.api_error", page=page_no, sub_type=type_label)
                    break

                data = rv.get("data", {})
                rows = data.get("rows", [])
                if not rows:
                    break

                total_pages = data.get("total", 0)
                total_records = data.get("recordsTotal", 0)
                logger.info(
                    "neep.list_page",
                    sub_type=type_label,
                    page=page_no,
                    items=len(rows),
                    total_pages=total_pages,
                    total_records=total_records,
                )

                for item in rows:
                    notice = await self._process_item(
                        page, item, notice_type, procurement_method
                    )
                    if notice:
                        yield notice
                    await asyncio.sleep(self.meta.rate_limit)

                if page_no >= total_pages:
                    break
                page_no += 1

    async def _process_item(
        self,
        page: Page,
        item: dict,
        notice_type: NoticeType,
        procurement_method: ProcurementMethod | None,
    ) -> BidNotice | None:
        title = (item.get("inquireName") or "").strip()
        if not title:
            return None

        article_url = item.get("articleUrl", "")
        notice_id = item.get("inquireCode") or item.get("articleCode")
        publish_date = _parse_date_str(item.get("publishTimeString"))
        deadline = _parse_datetime_ms(item.get("quotDeadline"))
        purchaser_area = item.get("publishArea")

        content = await self._fetch_detail_content(page, article_url)

        purchaser = None
        agency = None
        agency_contact = None
        if content:
            purchaser = self._extract_field(content, "采购人")
            agency = self._extract_field(content, "采购机构")
            contact_phone = self._extract_field(content, "联系电话")
            if contact_phone:
                agency_contact = contact_phone

        return BidNotice(
            title=title,
            source_site=self.meta.name,
            source_url=article_url or f"{_BASE_URL}/html/portal/index-Inquiries.html",
            notice_type=notice_type,
            notice_id=notice_id,
            publish_date=publish_date,
            deadline=deadline,
            procurement_method=procurement_method,
            purchaser=purchaser or purchaser_area,
            agency=agency,
            agency_contact=agency_contact,
            content=content,
            raw_data=item,
        )

    async def _fetch_detail_content(self, page: Page, url: str) -> str | None:
        if not url:
            return None
        try:
            html = await page.evaluate(
                """async (url) => {
                    try {
                        const r = await fetch(url);
                        if (!r.ok) return null;
                        return await r.text();
                    } catch(e) { return null; }
                }""",
                url,
            )
            if not html:
                return None

            clean = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
            clean = re.sub(r"<style[^>]*>.*?</style>", "", clean, flags=re.DOTALL)
            clean = re.sub(r"<head[^>]*>.*?</head>", "", clean, flags=re.DOTALL)

            menu_pattern = r"<div[^>]*class=[\"'][^\"']*left-menu[^\"']*[\"'][^>]*>.*?</div>\s*</div>"
            clean = re.sub(menu_pattern, "", clean, flags=re.DOTALL)

            clean = re.sub(r"<[^>]+>", "\n", clean)
            clean = re.sub(r"[ \t]+", " ", clean)
            clean = re.sub(r"\n\s*\n+", "\n", clean)
            text = clean.strip()

            lines = []
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line in ("公告", "当前位置："):
                    continue
                if line.startswith("询比价信息") or line.startswith(">"):
                    continue
                lines.append(line)

            return "\n".join(lines) if lines else None

        except Exception:
            logger.debug("neep.detail_fetch_failed", url=url)
            return None

    @staticmethod
    def _extract_field(content: str, field_name: str) -> str | None:
        pattern = rf"{field_name}[：:]\s*(.+)"
        match = re.search(pattern, content)
        if match:
            value = match.group(1).strip()
            return value if value else None
        return None

    async def scrape_detail(self, page: Page, url: str) -> BidNotice | None:
        return None
