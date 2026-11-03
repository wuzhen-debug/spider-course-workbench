"""Add read-only PDF inventory without altering existing course or XHS rows."""
from alembic import op
import sqlalchemy as s
revision = 'c029pdflibrary'
down_revision = 'c028coursep1'
branch_labels = None
depends_on = None


def upgrade():
    if not s.inspect(op.get_bind()).has_table('course_library_roots'):
        op.create_table('course_library_roots',s.Column('id',s.Integer(),primary_key=True),
            s.Column('user_id',s.Integer(),s.ForeignKey('users.id'),nullable=False),s.Column('path',s.String(1000),nullable=False),
            s.Column('status',s.String(30),nullable=False),s.Column('watch_backend',s.String(40),nullable=False),
            s.Column('last_scan_at',s.DateTime()),s.Column('heartbeat_at',s.DateTime()),s.Column('last_error',s.Text(),nullable=False),
            s.Column('created_at',s.DateTime(),nullable=False),s.UniqueConstraint('user_id','path',name='uq_library_owner_root'))
        op.create_index('ix_course_library_roots_user_id','course_library_roots',['user_id'])
    if not s.inspect(op.get_bind()).has_table('course_library_files'):
        op.create_table('course_library_files',s.Column('id',s.Integer(),primary_key=True),
            s.Column('user_id',s.Integer(),s.ForeignKey('users.id'),nullable=False),s.Column('root_id',s.Integer(),s.ForeignKey('course_library_roots.id'),nullable=False),
            s.Column('relative_path',s.String(1600),nullable=False),s.Column('filename',s.String(500),nullable=False),
            s.Column('size_bytes',s.BigInteger(),nullable=False),s.Column('mtime_ns',s.BigInteger(),nullable=False),s.Column('signature',s.String(180),nullable=False),
            s.Column('status',s.String(30),nullable=False),s.Column('error',s.Text(),nullable=False),
            s.Column('university',s.String(180),nullable=False),s.Column('course_code',s.String(40),nullable=False),s.Column('term',s.String(40),nullable=False),
            s.Column('material_type',s.String(80),nullable=False),s.Column('classification_status',s.String(40),nullable=False),s.Column('classification_reason',s.Text(),nullable=False),
            s.Column('course_id',s.Integer(),s.ForeignKey('course_offerings.id')),s.Column('product_id',s.Integer(),s.ForeignKey('course_material_products.id')),
            s.Column('current_revision_id',s.Integer()),s.Column('revision_count',s.Integer(),nullable=False),
            s.Column('first_seen_at',s.DateTime(),nullable=False),s.Column('updated_at',s.DateTime(),nullable=False),
            s.UniqueConstraint('root_id','relative_path',name='uq_library_file_path'))
        for column in ['user_id','root_id','status']: op.create_index('ix_course_library_files_'+column,'course_library_files',[column])
    if not s.inspect(op.get_bind()).has_table('course_library_revisions'):
        op.create_table('course_library_revisions',s.Column('id',s.Integer(),primary_key=True),
            s.Column('user_id',s.Integer(),s.ForeignKey('users.id'),nullable=False),s.Column('file_id',s.Integer(),s.ForeignKey('course_library_files.id'),nullable=False),
            s.Column('sha256',s.String(64),nullable=False),s.Column('size_bytes',s.BigInteger(),nullable=False),s.Column('mtime_ns',s.BigInteger(),nullable=False),
            s.Column('page_count',s.Integer()),s.Column('pdf_status',s.String(30),nullable=False),s.Column('preview_error',s.Text(),nullable=False),
            s.Column('version_id',s.Integer(),s.ForeignKey('course_material_versions.id')),s.Column('observed_at',s.DateTime(),nullable=False),
            s.UniqueConstraint('file_id','sha256',name='uq_library_content_revision'))
        for column in ['user_id','file_id']: op.create_index('ix_course_library_revisions_'+column,'course_library_revisions',[column])


def downgrade():
    raise RuntimeError('功能开关回退：使用 course_library.enabled=false 停止本地监测，保留索引及历史，不自动删除表')
