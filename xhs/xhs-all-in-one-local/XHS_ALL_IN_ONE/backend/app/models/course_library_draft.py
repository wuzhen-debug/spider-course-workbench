"""Manual review packages; no publishing or scheduled task relationship."""
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class CourseLibraryDraft(Base):
    __tablename__ = 'course_library_drafts'
    __table_args__ = (UniqueConstraint('user_id', 'request_key', name='uq_library_draft_request'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    file_id: Mapped[int] = mapped_column(ForeignKey('course_library_files.id'), index=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey('course_library_revisions.id'))
    request_key: Mapped[str] = mapped_column(String(36))
    plan_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default='pending')
    generation_mode: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    source_snapshot: Mapped[dict] = mapped_column(JSON)
    page_texts: Mapped[list] = mapped_column(JSON)
    images: Mapped[list] = mapped_column(JSON)
    model_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    instruction: Mapped[str] = mapped_column(Text, default='')
    draft_id: Mapped[Optional[int]] = mapped_column(ForeignKey('ai_drafts.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
