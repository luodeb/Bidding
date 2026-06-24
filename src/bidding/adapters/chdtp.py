from __future__ import annotations

import asyncio
import re
from datetime import date
from typing import AsyncIterator

import structlog
from playwright.async_api import Page

from bidding.adapters.base import AdapterMeta, SiteAdapter
from bidding.adapters.registry import register
from bidding.models.enums import NoticeType, ProjectCategory
from bidding.models.schema import BidNotice

logger = structlog.get_logger()

_BASE_URL = "https://www.chdtp.com.cn"

_BIZ_TYPE_MAP: dict[str, ProjectCategory] = {
    "货物": ProjectCategory.GOODS,
    "工程": ProjectCategory.ENGINEERING,
    "服务": ProjectCategory.SERVICE,
}

_PAGE_SIZE = 20

_CATEGORY_CONFIG: dict[NoticeType, list[dict]] = {
    NoticeType.BID_ANNOUNCEMENT: [
        {
            "label": "招标公告",
            "action": "/webs/queryWebZbgg.action",
            "params": {"zbggType": "1"},
            "detail_mode": "static",
        },
    ],
    NoticeType.NON_BID_ANNOUNCEMENT: [
        {
            "label": "询比采购公告",
            "action": "/webs/displayNewsCgxxAction.action",
            "params": {"cgggtype": "1"},
            "detail_mode": "static",
        },
        {
            "label": "谈判采购公告",
            "action": "/webs/displayNewsCgxxAction.action",
            "params": {"cgggtype": "0"},
            "detail_mode": "static",
        },
        {
            "label": "竞价采购公告",
            "action": "/webs/displayJjgg.action",
            "params": {},
            "detail_mode": "detail",
            "detail_action": "/webs/detailJjgg.action",
            "detail_param": "chkedId",
        },
    ],
    NoticeType.WIN_ANNOUNCEMENT: [
        {
            "label": "中标结果公告",
            "action": "/webs/displayNewZbhxrgsZxzxAction.action",
            "params": {"zbtype": "1"},
            "detail_mode": "detail",
            "detail_action": "/webs/detailNewZbhxrgsZxzxAction.action",
            "detail_param": "chkedId",
            "has_cminid": True,
        },
        {
            "label": "成交结果公告",
            "action": "/webs/displayCjgg.action",
            "params": {},
            "detail_mode": "detail",
            "detail_action": "/webs/detailCjgg.action",
            "detail_param": "chkedId",
        },
    ],
    NoticeType.CANDIDATE_PUBLICITY: [
        {
            "label": "中标候选人公示",
            "action": "/webs/displayNewZbhxrgsZxzxAction.action",
            "params": {"zbtype": "2"},
            "detail_mode": "detail",
            "detail_action": "/webs/detailNewZbhxrgsZxzxAction.action",
            "detail_param": "chkedId",
            "has_cminid": True,
        },
        {
            "label": "预成交公示",
            "action": "/webs/displayYcjgs.action",
            "params": {},
            "detail_mode": "detail",
            "detail_action": "/webs/detailYcjgs.action",
            "detail_param": "chkedId",
        },
    ],
    NoticeType.TERMINATION: [
        {
            "label": "终止招标公告",
            "action": "/webs/indexZzzbgg.action",
            "params": {},
            "detail_mode": "detail",
            "detail_action": "/webs/detailZzzbgg.action",
            "detail_param": "chkedId",
        },
    ],
}

_RE_TOGETCONTENT = re.compile(r"toGetContent\('([^']+)'\)")
_RE_TODETAIL_2 = re.compile(r"todetail\('([^']+)'\s*,\s*'([^']+)'\)")
_RE_TODETAIL_1 = re.compile(r"todetail\('([^']+)'\)")
_RE_DATE = re.compile(r"\[?(\d{4}-\d{2}-\d{2})\]?")


def _parse_date(s: str) -> date | None:
    m = _RE_DATE.search(s)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    return None


@register
class ChdtpAdapter(SiteAdapter):
    meta = AdapterMeta(
        name="chdtp",
        display_name="华电集团",
        base_url=_BASE_URL,
        notice_types=[
            NoticeType.BID_ANNOUNCEMENT,
            NoticeType.NON_BID_ANNOUNCEMENT,
            NoticeType.WIN_ANNOUNCEMENT,
            NoticeType.CANDIDATE_PUBLICITY,
            NoticeType.TERMINATION,
        ],
        requires_login=False,
        rate_limit=1.0,
    )

    async def scrape_list(
        self, page: Page, notice_type: NoticeType
    ) -> AsyncIterator[BidNotice]:
        cats = _CATEGORY_CONFIG.get(notice_type)
        if not cats:
            return

        await page.goto(
            f"{_BASE_URL}/pages/wzglS/cgxx/caigou.jsp",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await asyncio.sleep(3)

        for cat in cats:
            logger.info("chdtp.scrape_category", category=cat["label"])
            page_no = 1
            while True:
                items, total = await self._fetch_list_page(page, cat, page_no)
                if not items:
                    break

                total_pages = (total + _PAGE_SIZE - 1) // _PAGE_SIZE
                logger.info(
                    "chdtp.list_page",
                    category=cat["label"],
                    page=page_no,
                    items=len(items),
                    total=total,
                )

                for item in items:
                    notice = await self._process_item(page, item, notice_type, cat)
                    if notice:
                        yield notice
                    await asyncio.sleep(self.meta.rate_limit)

                if page_no >= total_pages or page_no >= 5:
                    break
                page_no += 1
                await asyncio.sleep(self.meta.rate_limit)

    async def _fetch_list_page(
        self, page: Page, cat: dict, page_no: int
    ) -> tuple[list[dict], int]:
        action_url = _BASE_URL + cat["action"]

        params = dict(cat["params"])
        params["page.currentpage"] = str(page_no)
        params["page.pageSize"] = str(_PAGE_SIZE)

        html = await page.evaluate(
            """async ([url, params]) => {
                try {
                    const body = new URLSearchParams(params);
                    const resp = await fetch(url, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                        body: body.toString()
                    });
                    return await resp.text();
                } catch(e) { return null; }
            }""",
            [action_url, params],
        )

        if not html:
            return [], 0

        total_match = re.search(r'totalCount[^>]*value="?(\d+)', html, re.IGNORECASE)
        if not total_match:
            total_match = re.search(r'共(\d+)条记录', html)
        total = int(total_match.group(1)) if total_match else 0

        items = self._parse_list_html(html, cat)
        return items, total

    def _parse_list_html(self, html: str, cat: dict) -> list[dict]:
        items = []
        rows = re.findall(
            r'<tr\s+style="height:\s*33px;">(.*?)</tr>', html, re.DOTALL
        )
        for row in rows:
            tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            if len(tds) < 3:
                continue

            # Find the title column (contains <a> with title= attribute)
            title_idx = -1
            href = ""
            title = ""
            for i, td in enumerate(tds):
                a_match = re.search(
                    r'<a[^>]*href="([^"]*)"[^>]*title="([^"]*)"', td
                )
                if not a_match:
                    a_match = re.search(
                        r'<a[^>]*title="([^"]*)"[^>]*href="([^"]*)"', td
                    )
                    if a_match:
                        title = a_match.group(1).strip()
                        href = a_match.group(2).strip()
                        title_idx = i
                        break
                else:
                    href = a_match.group(1).strip()
                    title = a_match.group(2).strip()
                    title_idx = i
                    break

            if title_idx < 0 or not title:
                continue

            # Date is always the last column
            date_str = re.sub(r"<[^>]+>", "", tds[-1]).strip()

            # Business type: column before title (if it exists) or empty
            biz_type = ""
            if title_idx > 0:
                biz_type = re.sub(r"<[^>]+>", "", tds[title_idx - 1]).strip()

            detail_path = None
            detail_id = None
            detail_cminid = None

            if cat["detail_mode"] == "static":
                m = _RE_TOGETCONTENT.search(href)
                if m:
                    detail_path = m.group(1)
            else:
                m2 = _RE_TODETAIL_2.search(href)
                if m2:
                    detail_id = m2.group(1)
                    detail_cminid = m2.group(2)
                else:
                    m1 = _RE_TODETAIL_1.search(href)
                    if m1:
                        detail_id = m1.group(1)

            items.append(
                {
                    "title": title,
                    "biz_type": biz_type,
                    "date": date_str,
                    "detail_path": detail_path,
                    "detail_id": detail_id,
                    "detail_cminid": detail_cminid,
                }
            )
        return items

    async def _process_item(
        self, page: Page, item: dict, notice_type: NoticeType, cat: dict
    ) -> BidNotice | None:
        title = item["title"]
        publish_date = _parse_date(item["date"])
        project_category = _BIZ_TYPE_MAP.get(item["biz_type"])

        if cat["detail_mode"] == "static" and item.get("detail_path"):
            source_url = f"{_BASE_URL}/staticPage/{item['detail_path']}"
        elif cat["detail_mode"] == "detail" and item.get("detail_id"):
            detail_action = cat["detail_action"]
            param_name = cat["detail_param"]
            source_url = f"{_BASE_URL}{detail_action}?{param_name}={item['detail_id']}"
            if item.get("detail_cminid"):
                source_url += f"&cminid={item['detail_cminid']}"
        else:
            source_url = _BASE_URL + cat["action"]

        content = await self._fetch_detail(page, source_url)

        notice = BidNotice(
            title=title,
            source_site=self.meta.name,
            source_url=source_url,
            notice_type=notice_type,
            publish_date=publish_date,
            project_category=project_category,
            content=content,
        )

        if content:
            purchaser = self._extract_field(
                content, r"招\s*标\s*人|采\s*购\s*人|招标采购单位|采购单位"
            )
            if purchaser:
                notice.purchaser = purchaser

        return notice

    async def _fetch_detail(self, page: Page, url: str) -> str | None:
        detail_page = await page.context.new_page()
        try:
            resp = await detail_page.goto(
                url, wait_until="domcontentloaded", timeout=20000
            )
            if not resp or resp.status != 200:
                return None
            await asyncio.sleep(1)

            content = await detail_page.evaluate("""() => {
                const body = document.body.innerText;
                const start = body.indexOf('正文');
                if (start >= 0) {
                    const end = body.indexOf('关于我们', start);
                    if (end > start) return body.substring(start + 2, end).trim();
                    return body.substring(start + 2, start + 15000).trim();
                }
                const footer = body.indexOf('关于我们');
                if (footer > 200) return body.substring(0, footer).trim();
                return body.substring(0, 10000).trim();
            }""")

            if content and len(content) > 50:
                return content
            return None
        except Exception:
            logger.debug("chdtp.detail_error", url=url[:80])
            return None
        finally:
            await detail_page.close()

    async def scrape_detail(self, page: Page, url: str) -> BidNotice | None:
        content = await self._fetch_detail(page, url)
        if not content:
            return None
        purchaser = self._extract_field(content, r"招标人|采购人|招标采购单位")
        return BidNotice(
            title="",
            source_site=self.meta.name,
            source_url=url,
            notice_type=NoticeType.BID_ANNOUNCEMENT,
            content=content,
            purchaser=purchaser,
        )

    @staticmethod
    def _extract_field(content: str, field_pattern: str) -> str | None:
        pattern = rf"(?:{field_pattern})[：:]\s*(.+)"
        match = re.search(pattern, content)
        if match:
            value = match.group(1).strip().split("\n")[0].strip()
            if value and len(value) < 100:
                return value
        return None
