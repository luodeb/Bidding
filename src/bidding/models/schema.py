from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Self

from pydantic import BaseModel, Field, computed_field

from bidding.models.enums import NoticeType, ProcurementMethod, ProjectCategory


class BidNotice(BaseModel):
    title: str
    source_site: str
    source_url: str
    notice_type: NoticeType

    notice_id: str | None = None
    publish_date: date | None = None
    deadline: datetime | None = None

    procurement_method: ProcurementMethod | None = None
    project_category: ProjectCategory | None = None

    purchaser: str | None = None
    purchaser_contact: str | None = None
    agency: str | None = None
    agency_contact: str | None = None

    project_name: str | None = None
    project_location: str | None = None
    budget: str | None = None

    content: str | None = None
    content_html: str | None = None
    attachments: list[str] = Field(default_factory=list)
    pdf_path: str | None = None

    winner: str | None = None
    win_amount: str | None = None

    scraped_at: datetime = Field(default_factory=datetime.now)
    raw_data: dict | None = None

    @computed_field
    @property
    def content_hash(self) -> str:
        key = f"{self.title}|{self.source_url}|{self.notice_id or ''}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def merge(self, other: BidNotice) -> Self:
        data = self.model_dump()
        for k, v in other.model_dump(exclude_none=True).items():
            if k != "content_hash":
                data[k] = v
        return type(self)(**data)
