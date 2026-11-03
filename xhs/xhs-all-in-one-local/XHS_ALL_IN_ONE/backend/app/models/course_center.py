"""Additive course workspace; demo content never enters publishing tables."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class CourseOffering(Base):
    __tablename__ = "course_offerings"
    __table_args__ = (UniqueConstraint("user_id", "university_key", "code_key", "term_key", "is_demo", name="uq_course_identity"),
                      UniqueConstraint("user_id", "seed_key", name="uq_course_seed"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    university: Mapped[str] = mapped_column(String(180))
    university_key: Mapped[str] = mapped_column(String(180))
    course_code: Mapped[str] = mapped_column(String(40))
    code_key: Mapped[str] = mapped_column(String(40))
    course_name: Mapped[str] = mapped_column(String(240))
    term: Mapped[str] = mapped_column(String(40))
    term_key: Mapped[str] = mapped_column(String(40))
    language: Mapped[str] = mapped_column(String(40), default="中英双语")
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    aliases_search: Mapped[str] = mapped_column(Text, default="")
    exam_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    source_reference: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    notes: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    seed_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now)


class CourseMaterialProduct(Base):
    __tablename__ = "course_material_products"
    __table_args__ = (UniqueConstraint("user_id", "seed_key", name="uq_course_product_seed"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course_offerings.id"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    material_type: Mapped[str] = mapped_column(String(80))
    coverage: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(String(120), default="")
    listing_status: Mapped[str] = mapped_column(String(24), default="not_listed")
    notes: Mapped[str] = mapped_column(Text, default="")
    seed_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)


class CourseMaterialVersion(Base):
    __tablename__ = "course_material_versions"
    __table_args__ = (UniqueConstraint("product_id", "version", "language", name="uq_course_material_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("course_material_products.id"), index=True)
    version: Mapped[str] = mapped_column(String(60))
    language: Mapped[str] = mapped_column(String(40), default="中英双语")
    source_reference: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    file_status: Mapped[str] = mapped_column(String(24), default="registered")
    qa_status: Mapped[str] = mapped_column(String(24), default="pending")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)


class CourseAsset(Base):
    __tablename__ = "course_assets"
    __table_args__ = (UniqueConstraint("user_id", "seed_key", name="uq_course_asset_seed"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course_offerings.id"), index=True)
    version_id: Mapped[Optional[int]] = mapped_column(ForeignKey("course_material_versions.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(180))
    asset_kind: Mapped[str] = mapped_column(String(24))
    reference: Mapped[str] = mapped_column(Text, default="")
    source_notes: Mapped[str] = mapped_column(Text, default="")
    page_reference: Mapped[str] = mapped_column(String(80), default="")
    watermarked: Mapped[bool] = mapped_column(Boolean, default=False)
    rights_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    usage_status: Mapped[str] = mapped_column(String(24), default="pending")
    seed_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)


class CourseDemoContent(Base):
    __tablename__ = "course_demo_contents"
    __table_args__ = (UniqueConstraint("user_id", "seed_key", name="uq_course_demo_content_seed"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    content_kind: Mapped[str] = mapped_column(String(24), default="draft")
    title: Mapped[str] = mapped_column(String(240))
    body: Mapped[str] = mapped_column(Text, default="")
    seed_key: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)


class CourseContentLink(Base):
    __tablename__ = "course_content_links"
    __table_args__ = (UniqueConstraint("course_id", "target_kind", "target_id", "target_is_demo", name="uq_course_content_target"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course_offerings.id"), index=True)
    version_id: Mapped[Optional[int]] = mapped_column(ForeignKey("course_material_versions.id"), nullable=True)
    target_kind: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[int] = mapped_column(Integer)
    target_is_demo: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)


COURSE_MODELS = (CourseOffering, CourseMaterialProduct, CourseMaterialVersion, CourseAsset, CourseDemoContent, CourseContentLink)
