from __future__ import annotations

import asyncio

import structlog
from playwright.async_api import async_playwright

from bidding.adapters.base import SiteAdapter
from bidding.adapters.registry import auto_discover, get_adapter, list_adapters
from bidding.core.dedup import DedupChecker
from bidding.core.pipeline import Pipeline
from bidding.storage.database import init_db

logger = structlog.get_logger()

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


class ScrapingEngine:
    def __init__(
        self,
        *,
        headless: bool = True,
        max_pages: int = 50,
        incremental_stop: int = 10,
    ):
        self.headless = headless
        self.max_pages = max_pages
        self.incremental_stop = incremental_stop
        self.dedup = DedupChecker()
        self.pipeline = Pipeline()

    async def run(self, site_names: list[str] | None = None):
        auto_discover()
        await init_db()

        all_adapters = list_adapters()
        if site_names:
            all_adapters = {k: v for k, v in all_adapters.items() if k in site_names}

        if not all_adapters:
            logger.error("engine.no_adapters", requested=site_names)
            return

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                for name, adapter_cls in all_adapters.items():
                    adapter = adapter_cls()
                    logger.info("engine.start_site", site=name)
                    await self._scrape_site(browser, adapter)
                    logger.info(
                        "engine.done_site",
                        site=name,
                        saved=self.pipeline.saved_count,
                    )
            finally:
                await browser.close()

    async def _scrape_site(self, browser, adapter: SiteAdapter):
        await self.dedup.warm_up(adapter.meta.name)

        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=_DEFAULT_UA,
        )

        try:
            await adapter.on_context_created(context)

            if adapter.meta.requires_login:
                login_page = await context.new_page()
                ok = await adapter.login(login_page)
                await login_page.close()
                if not ok:
                    logger.error("engine.login_failed", site=adapter.meta.name)
                    return

            for notice_type in adapter.meta.notice_types:
                page = await context.new_page()
                try:
                    dup_streak = 0
                    page_count = 0
                    async for notice in adapter.scrape_list(page, notice_type):
                        if await self.dedup.is_duplicate(notice.content_hash):
                            dup_streak += 1
                            if dup_streak >= self.incremental_stop:
                                logger.info(
                                    "engine.incremental_stop",
                                    site=adapter.meta.name,
                                    type=notice_type.value,
                                    streak=dup_streak,
                                )
                                break
                            continue
                        dup_streak = 0
                        await self.pipeline.process(notice)
                        await asyncio.sleep(adapter.meta.rate_limit)

                        page_count += 1
                        if page_count >= self.max_pages * adapter._pagination.page_size:
                            logger.info(
                                "engine.max_pages_reached",
                                site=adapter.meta.name,
                                pages=self.max_pages,
                            )
                            break
                except Exception:
                    logger.exception(
                        "engine.scrape_error",
                        site=adapter.meta.name,
                        type=notice_type.value,
                    )
                finally:
                    await page.close()
        finally:
            await context.close()
