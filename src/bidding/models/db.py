from datetime import date, datetime

from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class BidNoticeRecord(Base):
    __tablename__ = "bid_notices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    content_hash: Mapped[str] = mapped_column(String(16), unique=True, index=True)

    title: Mapped[str] = mapped_column(String(500))
    source_site: Mapped[str] = mapped_column(String(50), index=True)
    source_url: Mapped[str] = mapped_column(String(1000), unique=True)
    notice_type: Mapped[str] = mapped_column(String(50), index=True)
    notice_id: Mapped[str | None] = mapped_column(String(100), index=True)

    publish_date: Mapped[date | None] = mapped_column()
    deadline: Mapped[datetime | None] = mapped_column(DateTime)

    procurement_method: Mapped[str | None] = mapped_column(String(50))
    project_category: Mapped[str | None] = mapped_column(String(50))

    purchaser: Mapped[str | None] = mapped_column(String(200))
    purchaser_contact: Mapped[str | None] = mapped_column(String(200))
    agency: Mapped[str | None] = mapped_column(String(200))
    agency_contact: Mapped[str | None] = mapped_column(String(200))

    project_name: Mapped[str | None] = mapped_column(String(500))
    project_location: Mapped[str | None] = mapped_column(String(200))
    budget: Mapped[str | None] = mapped_column(String(100))

    content: Mapped[str | None] = mapped_column(Text)
    content_html: Mapped[str | None] = mapped_column(Text)
    attachments: Mapped[list | None] = mapped_column(JSON)
    pdf_path: Mapped[str | None] = mapped_column(String(500))

    winner: Mapped[str | None] = mapped_column(String(200))
    win_amount: Mapped[str | None] = mapped_column(String(100))

    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )
    raw_data: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        Index("idx_site_type_date", "source_site", "notice_type", "publish_date"),
    )
