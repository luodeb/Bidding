from __future__ import annotations

import asyncio
import re
from datetime import date, datetime
from typing import AsyncIterator

import structlog
from playwright.async_api import Page

from bidding.adapters.base import AdapterMeta, PaginationState, SiteAdapter
from bidding.adapters.registry import register
from bidding.models.enums import NoticeType
from bidding.models.schema import BidNotice

logger = structlog.get_logger()

_BASE_URL = "https://www.hydlcg.com"

# 华源电力采购网（Struts2 老站，GBK 编码）。Playwright 会自动处理 GBK charset。
# 列表页：/auctionActiveController!list.action（竞拍）/negoActiveController!list.action（谈判）
# 详情页：/html/article/YYYY/MM/DD/<id>_0.html 或 /negoActiveController!show.action?ebpNegoActiveView.rfqId=<id>
# ⚠️ 待联网校验：各列表端点对应的公告类型、分页方式、条目选择器需从真实页面确认。
_LIST_ENDPOINTS: dict[NoticeType, list[tuple[str, str]]] = {
    NoticeType.BID_ANNOUNCEMENT: [
        ("/auctionActiveController!list.action", "竞拍公告"),
    ],
    NoticeType.NON_BID_ANNOUNCEMENT: [
        ("/negoActiveController!list.action", "谈判公告"),
    ],
    # TODO(联网校验): 补充 htmlController!articleList.action?cmsTreeVo.id=<N> 对应的文章分类
}


def _parse_date_str(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _date_from_path(href: str) -> date | None:
    m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", href)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    return None


@register
class HydlAdapter(SiteAdapter):
    meta = AdapterMeta(
        name="hydl",
        display_name="华源电力采购网",
        base_url=_BASE_URL,
        notice_types=list(_LIST_ENDPOINTS.keys()),
        requires_login=False,
        rate_limit=1.0,
    )

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._pagination = PaginationState(page_size=20)

    async def scrape_list(self, page: Page, notice_type: NoticeType) -> AsyncIterator[BidNotice]:
        endpoints = _LIST_ENDPOINTS.get(notice_type)
        if not endpoints:
            return
        for path, label in endpoints:
            url = self._resolve_url(path)
            logger.info("hydl.scrape_list", notice_type=notice_type.value, label=label, url=url)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(1)
            except Exception:
                logger.warning("hydl.goto_failed", url=url)
                return
            items = await self._extract_list_items(page)
            logger.info("hydl.list_page", label=label, items=len(items))
            for item in items:
                notice = self._build_notice(item, notice_type)
                if notice:
                    detail = await self._fetch_detail(page, notice.source_url)
                    if detail:
                        notice = notice.merge(detail)
                    yield notice
            # ⚠️ 待联网校验：分页结构。先只取首页。

    async def _extract_list_items(self, page: Page) -> list[dict]:
        # 通用兜底：取 <a> 指向详情页（/html/article/ 或 show.action）
        # ⚠️ 待联网校验：真实列表项 DOM 结构
        return await page.evaluate(
            """() => {
                const re = /\\d{4}-\\d{1,2}-\\d{1,2}/;
                const seen = new Set();
                const out = [];
                document.querySelectorAll('a[href]').forEach(a => {
                    const href = a.getAttribute('href') || '';
                    if (!href || href === '#' || href.startsWith('javascript')) return;
                    if (seen.has(href)) return;
                    seen.add(href);
                    const title = (a.getAttribute('title') || a.innerText || '').trim();
                    if (!title || title.length < 4) return;
                    const ctx = (a.closest('li,tr,dd,div') || a.parentElement || a).innerText || '';
                    const dm = ctx.match(re);
                    out.push({href, title, date: dm ? dm[0] : null});
                });
                return out;
            }"""
        )

    def _build_notice(self, item: dict, notice_type: NoticeType) -> BidNotice | None:
        title = (item.get("title") or "").strip()
        if not title:
            return None
        href = item.get("href") or ""
        return BidNotice(
            title=title, source_site=self.meta.name, source_url=self._resolve_url(href),
            notice_type=notice_type, notice_id=None,
            publish_date=_parse_date_str(item.get("date")) or _date_from_path(href),
            content=None, raw_data=item,
        )

    async def _fetch_detail(self, page: Page, url: str) -> BidNotice | None:
        if not url:
            return None
        dp = await page.context.new_page()
        try:
            await dp.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(0.5)
            content = await self._extract_content(dp)
            if not content:
                return None
            return BidNotice(title="", source_site=self.meta.name, source_url=url, notice_type=NoticeType.BID_ANNOUNCEMENT, content=content)
        except Exception:
            logger.debug("hydl.detail_failed", url=url[:80])
            return None
        finally:
            await dp.close()

    async def _extract_content(self, page: Page) -> str | None:
        for sel in [".content", ".article-content", "#content", ".detail-content"]:
            el = await page.query_selector(sel)
            if el:
                text = await el.inner_text()
                if text and len(text.strip()) > 20:
                    return text.strip()
        return None

    async def scrape_detail(self, page: Page, url: str) -> BidNotice | None:
        return await self._fetch_detail(page, url)
