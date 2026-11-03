"""Add isolated course center tables; logical rollback preserves data."""
from alembic import op
import sqlalchemy as sa

revision = 'c028coursep1'
down_revision = '60cd5c95fde1'
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table('course_offerings'):
        op.create_table('course_offerings',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=False, nullable=False),
            sa.Column('university', sa.String(180), primary_key=False, nullable=False),
            sa.Column('university_key', sa.String(180), primary_key=False, nullable=False),
            sa.Column('course_code', sa.String(40), primary_key=False, nullable=False),
            sa.Column('code_key', sa.String(40), primary_key=False, nullable=False),
            sa.Column('course_name', sa.String(240), primary_key=False, nullable=False),
            sa.Column('term', sa.String(40), primary_key=False, nullable=False),
            sa.Column('term_key', sa.String(40), primary_key=False, nullable=False),
            sa.Column('language', sa.String(40), primary_key=False, nullable=False),
            sa.Column('aliases', sa.JSON(), primary_key=False, nullable=False),
            sa.Column('aliases_search', sa.Text(), primary_key=False, nullable=False),
            sa.Column('exam_date', sa.String(20), primary_key=False, nullable=True),
            sa.Column('source_reference', sa.Text(), primary_key=False, nullable=False),
            sa.Column('priority', sa.String(20), primary_key=False, nullable=False),
            sa.Column('notes', sa.Text(), primary_key=False, nullable=False),
            sa.Column('archived', sa.Boolean(), primary_key=False, nullable=False),
            sa.Column('is_demo', sa.Boolean(), primary_key=False, nullable=False),
            sa.Column('seed_key', sa.String(100), primary_key=False, nullable=True),
            sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
            sa.Column('updated_at', sa.DateTime(), primary_key=False, nullable=False),
            sa.UniqueConstraint('user_id', 'university_key', 'code_key', 'term_key', 'is_demo', name='uq_course_identity'),
            sa.UniqueConstraint('user_id', 'seed_key', name='uq_course_seed'),
        )
        op.create_index('ix_course_offerings_is_demo', 'course_offerings', ['is_demo'], unique=False)
        op.create_index('ix_course_offerings_user_id', 'course_offerings', ['user_id'], unique=False)
    if not sa.inspect(bind).has_table('course_material_products'):
        op.create_table('course_material_products',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=False, nullable=False),
            sa.Column('course_id', sa.Integer(), sa.ForeignKey('course_offerings.id'), primary_key=False, nullable=False),
            sa.Column('title', sa.String(240), primary_key=False, nullable=False),
            sa.Column('material_type', sa.String(80), primary_key=False, nullable=False),
            sa.Column('coverage', sa.Text(), primary_key=False, nullable=False),
            sa.Column('owner', sa.String(120), primary_key=False, nullable=False),
            sa.Column('listing_status', sa.String(24), primary_key=False, nullable=False),
            sa.Column('notes', sa.Text(), primary_key=False, nullable=False),
            sa.Column('seed_key', sa.String(100), primary_key=False, nullable=True),
            sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
            sa.UniqueConstraint('user_id', 'seed_key', name='uq_course_product_seed'),
        )
        op.create_index('ix_course_material_products_course_id', 'course_material_products', ['course_id'], unique=False)
        op.create_index('ix_course_material_products_user_id', 'course_material_products', ['user_id'], unique=False)
    if not sa.inspect(bind).has_table('course_material_versions'):
        op.create_table('course_material_versions',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=False, nullable=False),
            sa.Column('product_id', sa.Integer(), sa.ForeignKey('course_material_products.id'), primary_key=False, nullable=False),
            sa.Column('version', sa.String(60), primary_key=False, nullable=False),
            sa.Column('language', sa.String(40), primary_key=False, nullable=False),
            sa.Column('source_reference', sa.Text(), primary_key=False, nullable=False),
            sa.Column('sha256', sa.String(64), primary_key=False, nullable=False),
            sa.Column('file_status', sa.String(24), primary_key=False, nullable=False),
            sa.Column('qa_status', sa.String(24), primary_key=False, nullable=False),
            sa.Column('notes', sa.Text(), primary_key=False, nullable=False),
            sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
            sa.UniqueConstraint('product_id', 'version', 'language', name='uq_course_material_version'),
        )
        op.create_index('ix_course_material_versions_product_id', 'course_material_versions', ['product_id'], unique=False)
        op.create_index('ix_course_material_versions_user_id', 'course_material_versions', ['user_id'], unique=False)
    if not sa.inspect(bind).has_table('course_assets'):
        op.create_table('course_assets',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=False, nullable=False),
            sa.Column('course_id', sa.Integer(), sa.ForeignKey('course_offerings.id'), primary_key=False, nullable=False),
            sa.Column('version_id', sa.Integer(), sa.ForeignKey('course_material_versions.id'), primary_key=False, nullable=True),
            sa.Column('title', sa.String(180), primary_key=False, nullable=False),
            sa.Column('asset_kind', sa.String(24), primary_key=False, nullable=False),
            sa.Column('reference', sa.Text(), primary_key=False, nullable=False),
            sa.Column('source_notes', sa.Text(), primary_key=False, nullable=False),
            sa.Column('page_reference', sa.String(80), primary_key=False, nullable=False),
            sa.Column('watermarked', sa.Boolean(), primary_key=False, nullable=False),
            sa.Column('rights_confirmed', sa.Boolean(), primary_key=False, nullable=False),
            sa.Column('usage_status', sa.String(24), primary_key=False, nullable=False),
            sa.Column('seed_key', sa.String(100), primary_key=False, nullable=True),
            sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
            sa.UniqueConstraint('user_id', 'seed_key', name='uq_course_asset_seed'),
        )
        op.create_index('ix_course_assets_course_id', 'course_assets', ['course_id'], unique=False)
        op.create_index('ix_course_assets_user_id', 'course_assets', ['user_id'], unique=False)
    if not sa.inspect(bind).has_table('course_demo_contents'):
        op.create_table('course_demo_contents',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=False, nullable=False),
            sa.Column('content_kind', sa.String(24), primary_key=False, nullable=False),
            sa.Column('title', sa.String(240), primary_key=False, nullable=False),
            sa.Column('body', sa.Text(), primary_key=False, nullable=False),
            sa.Column('seed_key', sa.String(100), primary_key=False, nullable=False),
            sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
            sa.UniqueConstraint('user_id', 'seed_key', name='uq_course_demo_content_seed'),
        )
        op.create_index('ix_course_demo_contents_user_id', 'course_demo_contents', ['user_id'], unique=False)
    if not sa.inspect(bind).has_table('course_content_links'):
        op.create_table('course_content_links',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=False, nullable=False),
            sa.Column('course_id', sa.Integer(), sa.ForeignKey('course_offerings.id'), primary_key=False, nullable=False),
            sa.Column('version_id', sa.Integer(), sa.ForeignKey('course_material_versions.id'), primary_key=False, nullable=True),
            sa.Column('target_kind', sa.String(24), primary_key=False, nullable=False),
            sa.Column('target_id', sa.Integer(), primary_key=False, nullable=False),
            sa.Column('target_is_demo', sa.Boolean(), primary_key=False, nullable=False),
            sa.Column('active', sa.Boolean(), primary_key=False, nullable=False),
            sa.Column('notes', sa.Text(), primary_key=False, nullable=False),
            sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
            sa.UniqueConstraint('course_id', 'target_kind', 'target_id', 'target_is_demo', name='uq_course_content_target'),
        )
        op.create_index('ix_course_content_links_course_id', 'course_content_links', ['course_id'], unique=False)
        op.create_index('ix_course_content_links_user_id', 'course_content_links', ['user_id'], unique=False)

def downgrade():
    raise RuntimeError("课程模块使用功能开关回退，保留新增数据；禁止自动删除课程表。")
