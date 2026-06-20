from __future__ import annotations

import structlog
from sqlalchemy import select, update

from bidding.models.db import BidNoticeRecord
from bidding.storage.database import get_session_factory, init_db
from bidding.utils.pdf import download_and_extract_pdf

logger = structlog.get_logger()


class PdfFetcher:
    def __init__(self, *, limit: int = 50):
        self.limit = limit
        self.updated_count = 0

    async def run(self, site_names: list[str] | None = None):
        await init_db()
        factory = get_session_factory()

        async with factory() as session:
            stmt = (
                select(BidNoticeRecord)
                .where(BidNoticeRecord.attachments.isnot(None))
                .where(BidNoticeRecord.pdf_path.is_(None))
                .order_by(BidNoticeRecord.id)
                .limit(self.limit)
            )
            if site_names:
                stmt = stmt.where(BidNoticeRecord.source_site.in_(site_names))
            result = await session.execute(stmt)
            records = result.scalars().all()

        candidates = []
        for r in records:
            if not r.attachments:
                continue
            pdf_urls = [u for u in r.attachments if "pdf" in u.lower()]
            if not pdf_urls:
                continue
            candidates.append((r, pdf_urls[0]))

        if not candidates:
            logger.info("pdf_fetcher.nothing_to_do")
            return

        logger.info("pdf_fetcher.start", total=len(candidates))

        for i, (record, pdf_url) in enumerate(candidates):
            logger.info(
                "pdf_fetcher.processing",
                progress=f"{i + 1}/{len(candidates)}",
                title=record.title[:50],
            )
            pdf_filename, text = await download_and_extract_pdf(pdf_url)
            if pdf_filename:
                values = {"pdf_path": pdf_filename}
                if text:
                    values["content"] = text
                async with factory() as session:
                    await session.execute(
                        update(BidNoticeRecord)
                        .where(BidNoticeRecord.id == record.id)
                        .values(**values)
                    )
                    await session.commit()
                self.updated_count += 1
                logger.info(
                    "pdf_fetcher.saved",
                    id=record.id,
                    pdf=pdf_filename,
                    chars=len(text) if text else 0,
                )
