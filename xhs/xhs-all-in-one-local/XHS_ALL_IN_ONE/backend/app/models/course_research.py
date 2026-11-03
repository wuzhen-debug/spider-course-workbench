"""Course-wide research and pending copy. Never creates publishing/scheduler records."""
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class CourseResearch(Base):
    __tablename__ = 'course_research'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    searches: Mapped[list] = mapped_column(JSON, default=list)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {'version_id_col': row_version}
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now)


class CourseResearchDraft(Base):
    __tablename__ = 'course_research_drafts'
    __table_args__ = (UniqueConstraint('user_id', 'request_key', name='uq_course_research_request'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    research_id: Mapped[int] = mapped_column(ForeignKey('course_research.id'), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    request_digest: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    prompt: Mapped[str] = mapped_column(Text)
    brief: Mapped[dict] = mapped_column(JSON, default=dict)
    mode: Mapped[str] = mapped_column(String(20), default='outline')
    status: Mapped[str] = mapped_column(String(20), default='pending')
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {'version_id_col': row_version}
    draft_id: Mapped[Optional[int]] = mapped_column(ForeignKey('ai_drafts.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


RESEARCH_MODELS = (CourseResearch, CourseResearchDraft)
