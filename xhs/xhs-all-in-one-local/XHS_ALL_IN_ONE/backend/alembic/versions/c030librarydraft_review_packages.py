"""Add isolated PDF review packages. Preserve all existing tables and rows."""
revision = 'c030librarydraft'
down_revision = 'c029pdflibrary'
branch_labels = None
depends_on = None


def upgrade():
    from alembic import op
    from backend.app.models.course_library_draft import CourseLibraryDraft
    CourseLibraryDraft.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError('功能开关回退：course_library.enabled=false 可停用题库模块；保留草稿审核记录，不自动删除表或数据')
