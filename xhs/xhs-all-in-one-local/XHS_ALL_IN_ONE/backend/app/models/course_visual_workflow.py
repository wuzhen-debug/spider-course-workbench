"""Additive, owner-scoped course marketing workflow; never schedules publication."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class CourseVisualWorkflow(Base):
    __tablename__ = 'course_visual_workflows'
    __table_args__ = (UniqueConstraint('user_id', 'request_key', name='uq_course_visual_request'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    file_id: Mapped[int] = mapped_column(ForeignKey('course_library_files.id'), index=True)
    request_key: Mapped[str] = mapped_column(String(80))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {'version_id_col': row_version}
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now)
