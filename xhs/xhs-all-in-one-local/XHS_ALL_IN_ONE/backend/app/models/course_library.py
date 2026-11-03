"""Read-only local PDF inventory and content revisions; no original bytes stored."""
from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class CourseLibraryRoot(Base):
    __tablename__ = "course_library_roots"
    __table_args__ = (UniqueConstraint("user_id", "path", name="uq_library_owner_root"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    path: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(30), default="starting")
    watch_backend: Mapped[str] = mapped_column(String(40), default="reconcile")
    last_scan_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)


class CourseLibraryFile(Base):
    __tablename__ = "course_library_files"
    __table_args__ = (UniqueConstraint("root_id", "relative_path", name="uq_library_file_path"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    root_id: Mapped[int] = mapped_column(ForeignKey("course_library_roots.id"), index=True)
    relative_path: Mapped[str] = mapped_column(String(1600))
    filename: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    mtime_ns: Mapped[int] = mapped_column(BigInteger, default=0)
    signature: Mapped[str] = mapped_column(String(180), default="")
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    university: Mapped[str] = mapped_column(String(180), default="")
    course_code: Mapped[str] = mapped_column(String(40), default="")
    term: Mapped[str] = mapped_column(String(40), default="未标注")
    material_type: Mapped[str] = mapped_column(String(80), default="")
    classification_status: Mapped[str] = mapped_column(String(40), default="needs_confirmation")
    classification_reason: Mapped[str] = mapped_column(Text, default="")
    course_id: Mapped[Optional[int]] = mapped_column(ForeignKey("course_offerings.id"), nullable=True)
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("course_material_products.id"), nullable=True)
    current_revision_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    revision_count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now)


class CourseLibraryRevision(Base):
    __tablename__ = "course_library_revisions"
    __table_args__ = (UniqueConstraint("file_id", "sha256", name="uq_library_content_revision"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("course_library_files.id"), index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    mtime_ns: Mapped[int] = mapped_column(BigInteger)
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pdf_status: Mapped[str] = mapped_column(String(30), default="not_checked")
    preview_error: Mapped[str] = mapped_column(Text, default="")
    version_id: Mapped[Optional[int]] = mapped_column(ForeignKey("course_material_versions.id"), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)


LIBRARY_MODELS = (CourseLibraryRoot, CourseLibraryFile, CourseLibraryRevision)
