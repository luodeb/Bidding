from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from bidding.models.db import BidNoticeRecord
from bidding.models.schema import BidNotice
from bidding.storage.database import get_session_factory


class NoticeRepository:
    async def exists_by_hash(self, content_hash: str) -> bool:
        factory = get_session_factory()
        async with factory() as session:
            stmt = select(BidNoticeRecord.id).where(
                BidNoticeRecord.content_hash == content_hash
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    async def save(self, notice: BidNotice) -> BidNoticeRecord | None:
        factory = get_session_factory()
        async with factory() as session:
            existing = await session.execute(
                select(BidNoticeRecord.id).where(
                    BidNoticeRecord.source_url == notice.source_url
                )
            )
            if existing.scalar_one_or_none() is not None:
                return None

            record = BidNoticeRecord(
                content_hash=notice.content_hash,
                title=notice.title,
                source_site=notice.source_site,
                source_url=notice.source_url,
                notice_type=notice.notice_type.value,
                notice_id=notice.notice_id,
                publish_date=notice.publish_date,
                deadline=notice.deadline,
                procurement_method=(
                    notice.procurement_method.value
                    if notice.procurement_method
                    else None
                ),
                project_category=(
                    notice.project_category.value
                    if notice.project_category
                    else None
                ),
                purchaser=notice.purchaser,
                purchaser_contact=notice.purchaser_contact,
                agency=notice.agency,
                agency_contact=notice.agency_contact,
                project_name=notice.project_name,
                project_location=notice.project_location,
                budget=notice.budget,
                content=notice.content,
                content_html=notice.content_html,
                attachments=notice.attachments or None,
                pdf_path=notice.pdf_path,
                winner=notice.winner,
                win_amount=notice.win_amount,
                scraped_at=notice.scraped_at,
                raw_data=notice.raw_data,
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

    async def get_recent_hashes(self, site_name: str, days: int = 30) -> set[str]:
        factory = get_session_factory()
        cutoff = datetime.now() - timedelta(days=days)
        async with factory() as session:
            stmt = select(BidNoticeRecord.content_hash).where(
                BidNoticeRecord.source_site == site_name,
                BidNoticeRecord.scraped_at >= cutoff,
            )
            result = await session.execute(stmt)
            return {row[0] for row in result.all()}

    async def count(self, site_name: str | None = None) -> int:
        from sqlalchemy import func

        factory = get_session_factory()
        async with factory() as session:
            stmt = select(func.count(BidNoticeRecord.id))
            if site_name:
                stmt = stmt.where(BidNoticeRecord.source_site == site_name)
            result = await session.execute(stmt)
            return result.scalar_one()
