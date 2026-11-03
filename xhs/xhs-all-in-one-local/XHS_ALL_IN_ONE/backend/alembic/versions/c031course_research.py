"""Add course research and draft review; no legacy data mutations."""
revision = 'c031research'
down_revision = 'c030librarydraft'
branch_labels = None
depends_on = None


def upgrade():
    from alembic import op
    from backend.app.models.course_research import RESEARCH_MODELS
    for model in RESEARCH_MODELS:
        model.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError('功能开关回退：停用课程选题入口并保留研究/审核数据，不自动删除表')
