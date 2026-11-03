"""A PDF's two independent review drafts; no automatic publication relationship."""
from datetime import datetime
from sqlalchemy import DateTime,ForeignKey,Integer,JSON,String,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class CoursePlatformPair(Base):
    __tablename__='course_platform_pairs'
    __table_args__=(UniqueConstraint('user_id','request_key',name='uq_platform_pair_request'),)
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    file_id:Mapped[int]=mapped_column(ForeignKey('course_library_files.id'),index=True)
    revision_id:Mapped[int]=mapped_column(ForeignKey('course_library_revisions.id'))
    request_key:Mapped[str]=mapped_column(String(36))
    request_digest:Mapped[str]=mapped_column(String(64))
    xhs_package_id:Mapped[int]=mapped_column(ForeignKey('course_library_drafts.id'))
    xhs_history:Mapped[list]=mapped_column(JSON,default=list)
    xianyu:Mapped[dict]=mapped_column(JSON)
    xianyu_history:Mapped[list]=mapped_column(JSON,default=list)
    created_at:Mapped[datetime]=mapped_column(DateTime,default=shanghai_now)
    updated_at:Mapped[datetime]=mapped_column(DateTime,default=shanghai_now)
