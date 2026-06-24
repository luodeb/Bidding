from __future__ import annotations

import asyncio
import html
import re
from datetime import date, datetime
from typing import AsyncIterator

import structlog
from playwright.async_api import Page

from bidding.adapters.base import AdapterMeta, SiteAdapter
from bidding.adapters.registry import register
from bidding.models.enums import NoticeType, ProjectCategory
from bidding.models.schema import BidNotice

logger = structlog.get_logger()

_BASE_URL = "https://www.szecp.com.cn"
_API = "/rcms-external-rest/content/getSZExtData"
_PAGE_SIZE = 20

_CATEGORY_MAP: dict[NoticeType, list[int]] = {
    NoticeType.BID_ANNOUNCEMENT: [26909],
    NoticeType.CHANGE_ANNOUNCEMENT: [26910, 26917],
    NoticeType.CANDIDATE_PUBLICITY: [26911],
    NoticeType.WIN_ANNOUNCEMENT: [26912, 26918],
    NoticeType.TERMINATION: [26913],
    NoticeType.NON_BID_ANNOUNCEMENT: [26915],
}

_CHANNEL_LABELS = {
    26909: "招标公告",
    26910: "更正公告",
    26911: "中标候选人公示",
    26912: "中标公告",
    26913: "终止公告",
    26915: "非招标采购公告",
    26917: "变更公告",
    26918: "结果公告",
}

_PURCHASE_TYPE_MAP: dict[str, ProjectCategory] = {
    "货物": ProjectCategory.GOODS,
    "工程": ProjectCategory.ENGINEERING,
    "服务": ProjectCategory.SERVICE,
}


def _parse_publish_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _parse_deadline(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s[:16], "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return None


def _html_to_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _build_detail_url(relative_url: str) -> str:
    if not relative_url:
        return ""
    path = relative_url.replace("../", "/")
    return f"{_BASE_URL}{path}"


@register
class SzecpAdapter(SiteAdapter):
    meta = AdapterMeta(
        name="szecp",
        display_name="华润守正",
        base_url=_BASE_URL,
        notice_types=[
            NoticeType.BID_ANNOUNCEMENT,
            NoticeType.CHANGE_ANNOUNCEMENT,
            NoticeType.CANDIDATE_PUBLICITY,
            NoticeType.WIN_ANNOUNCEMENT,
            NoticeType.TERMINATION,
            NoticeType.NON_BID_ANNOUNCEMENT,
        ],
        requires_login=False,
        rate_limit=1.0,
    )

    async def scrape_list(
        self, page: Page, notice_type: NoticeType
    ) -> AsyncIterator[BidNotice]:
        channels = _CATEGORY_MAP.get(notice_type)
        if not channels:
            return

        await self._ensure_loaded(page)

        for channel_id in channels:
            label = _CHANNEL_LABELS.get(channel_id, str(channel_id))
            logger.info("szecp.scrape_channel", channel=label, id=channel_id)

            page_no = 1
            while True:
                items, total = await self._fetch_list(page, channel_id, page_no)
                if not items:
                    break

                logger.info(
                    "szecp.list_page",
                    channel=label,
                    page=page_no,
                    items=len(items),
                    total=total,
                )

                for item in items:
                    notice = await self._process_item(page, item, notice_type)
                    if notice:
                        yield notice
                    await asyncio.sleep(self.meta.rate_limit)

                if page_no * _PAGE_SIZE >= total:
                    break
                page_no += 1

    async def _ensure_loaded(self, page: Page) -> None:
        if "szecp.com.cn" in page.url:
            return
        await page.goto(
            f"{_BASE_URL}/first_zbgg/index.html",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await asyncio.sleep(3)

    async def _fetch_list(
        self, page: Page, channel_id: int, page_no: int
    ) -> tuple[list[dict], int]:
        result = await page.evaluate(
            """async ([url, params]) => {
                try {
                    const resp = await fetch(url + '?' + params);
                    return await resp.json();
                } catch(e) { return null; }
            }""",
            [_API, f"channelIds={channel_id}&pageNo={page_no}&pageSize={_PAGE_SIZE}"],
        )
        if not result or result.get("code") != "S1A00000":
            return [], 0
        data = result.get("data", {})
        return data.get("data", []), data.get("totalCount", 0)

    async def _process_item(
        self, page: Page, item: dict, notice_type: NoticeType
    ) -> BidNotice | None:
        title = (item.get("title") or "").strip()
        if not title:
            return None

        content_id = item.get("contentId")
        relative_url = item.get("url") or ""
        detail_url = _build_detail_url(relative_url)
        source_url = detail_url or f"{_BASE_URL}/?contentId={content_id}"

        publish_date = _parse_publish_date(item.get("publishDate"))
        deadline = _parse_deadline(item.get("deadline"))
        notice_id = item.get("number") or None
        purchase_type = item.get("purchaseType") or ""
        project_category = _PURCHASE_TYPE_MAP.get(purchase_type)

        content = None
        purchaser = None
        winner = None
        win_amount = None

        if detail_url:
            content = await self._fetch_detail_content(page, detail_url)

        if content:
            purchaser = self._extract_field(
                content, r"招\s*标\s*人|采\s*购\s*人|项目业主"
            )
            if not purchaser:
                m = re.search(r"招标人为(.+?)[。，,\n]", content)
                if m and 3 < len(m.group(1).strip()) < 80:
                    purchaser = m.group(1).strip()

            if notice_type in (
                NoticeType.WIN_ANNOUNCEMENT,
                NoticeType.CANDIDATE_PUBLICITY,
            ):
                winner = self._extract_field(
                    content, r"中\s*标\s*人\s*名?\s*称?|成交供应商|中标单位"
                )
                win_amount = self._extract_field(
                    content, r"中标价格|中标金额|成交金额|中标价"
                )
                if not winner:
                    winner, win_amount = self._extract_table_winner(content)

        notice = BidNotice(
            title=title,
            source_site=self.meta.name,
            source_url=source_url,
            notice_type=notice_type,
            notice_id=notice_id,
            publish_date=publish_date,
            deadline=deadline,
            project_category=project_category,
            content=content,
            purchaser=purchaser,
            winner=winner,
            win_amount=win_amount,
        )
        return notice

    async def _fetch_detail_content(self, page: Page, url: str) -> str | None:
        detail_page = await page.context.new_page()
        try:
            resp = await detail_page.goto(
                url, wait_until="networkidle", timeout=20000
            )
            if not resp or resp.status != 200:
                return None
            await asyncio.sleep(2)

            content_html = await detail_page.evaluate("""() => {
                const el = document.querySelector('.szb-content-item');
                return el ? el.innerHTML : '';
            }""")

            if not content_html:
                return None

            return _html_to_text(content_html)
        except Exception:
            logger.debug("szecp.detail_error", url=url[:80])
            return None
        finally:
            await detail_page.close()

    async def scrape_detail(self, page: Page, url: str) -> BidNotice | None:
        await self._ensure_loaded(page)
        content = await self._fetch_detail_content(page, url)
        if not content:
            return None
        return BidNotice(
            title="",
            source_site=self.meta.name,
            source_url=url,
            notice_type=NoticeType.BID_ANNOUNCEMENT,
            content=content,
        )

    @staticmethod
    def _extract_table_winner(content: str) -> tuple[str | None, str | None]:
        m = re.search(
            r"中标人\s+(.{3,80}?)\s+(\d[\d,，.]+万?元)",
            content,
        )
        if m:
            return m.group(1).strip(), m.group(2).strip()
        m2 = re.search(
            r"标段\d?\s+中标人\s+(.{3,80}?)\s+(\d[\d,，.]+万?元)",
            content,
        )
        if m2:
            return m2.group(1).strip(), m2.group(2).strip()
        return None, None

    @staticmethod
    def _extract_field(content: str, field_pattern: str) -> str | None:
        pattern = rf"(?:{field_pattern})[：:]\s*(.+?)(?:[,，。\n]|地\s*址|联\s*系|电\s*话|中标金额|标段)"
        match = re.search(pattern, content)
        if match:
            value = match.group(1).strip()
            if value and 3 < len(value) < 80:
                return value
        pattern2 = rf"(?:{field_pattern})[：:]\s*(.{{3,60}})"
        match2 = re.search(pattern2, content)
        if match2:
            value = match2.group(1).strip().split("地")[0].strip()
            if value and 3 < len(value) < 80:
                return value
        return None
