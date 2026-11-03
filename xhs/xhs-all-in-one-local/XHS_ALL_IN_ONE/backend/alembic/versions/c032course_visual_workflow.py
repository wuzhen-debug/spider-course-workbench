"""Owner-scoped human-reviewed visual workflow. No legacy row mutations."""
revision = 'c032visualflow'
down_revision = 'c031research'
branch_labels = None
depends_on = None


def upgrade():
    from alembic import op
    from backend.app.models.course_visual_workflow import CourseVisualWorkflow
    CourseVisualWorkflow.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError('功能开关回退：回退入口代码即可；保留工作台审核记录，不自动删除数据表')
