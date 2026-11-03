"""Owner-scoped, read-only index of course copy and image work.

This index links to the existing review records; it never creates, approves,
exports or publishes content while listing it.
"""
from datetime import datetime
from pathlib import PurePosixPath
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.course_library import require_library
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import AiDraft, User
from backend.app.models.course_library import CourseLibraryFile
from backend.app.models.course_library_draft import CourseLibraryDraft
from backend.app.models.course_platform_pair import CoursePlatformPair
from backend.app.models.course_research import CourseResearch, CourseResearchDraft
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.services import course_visual_workflow as flow
from backend.app.services.course_draft_origin import linked_draft_is_current

router = APIRouter(prefix='/course-center', tags=['course-creations'])


def relative_path(value):
    value = str(value or '')
    path = PurePosixPath(value)
    if path.is_absolute() or '\\' in value or '\x00' in value or any(p in {'.', '..'} for p in value.split('/')):
        return ''
    return value.rstrip('/')


def library_url(path='', **params):
    parent = str(PurePosixPath(path).parent) if path else ''
    return '/platforms/xhs/course-center?' + urlencode({'library_dir': '' if parent == '.' else parent, **params})


def in_directory(path, directory):
    return not directory or path == directory or path.startswith(directory + '/')


def is_approved(data, stage):
    try:
        return flow.approved(data, stage)
    except (KeyError, TypeError, ValueError):
        return False


def visual_status(data, available):
    operation = data.get('operation') or {}
    if operation.get('status') == 'generating':
        return 'processing'
    if operation.get('status') == 'failed':
        return 'failed'
    if available:
        return 'draft_saved'
    if data.get('images'):
        return 'images_reviewed' if is_approved(data, 'set') else 'images_pending'
    if data.get('cover'):
        return 'cover_reviewed' if is_approved(data, 'cover') else 'cover_pending'
    return 'visual_planned' if is_approved(data, 'copy') else 'copy_pending'


@router.get('/creations')
def creations(q: str = Query('', max_length=240), file_id: int | None = Query(None, ge=1),
              directory: str = Query('', max_length=1600), limit: int = Query(6, ge=1, le=100),
              offset: int = Query(0, ge=0), user: User = Depends(get_current_user),
              db: Session = Depends(get_db), settings=Depends(require_library)):
    clean_directory = relative_path(directory)
    if directory and not clean_directory:
        raise HTTPException(422, '请选择题库内的相对目录')
    files = {f.id: f for f in db.scalars(select(CourseLibraryFile).where(CourseLibraryFile.user_id == user.id))}
    if file_id is not None and file_id not in files:
        raise HTTPException(404, '所选资料不存在')
    drafts = {d.id: d for d in db.scalars(select(AiDraft).where(AiDraft.user_id == user.id))}
    items = []

    def add(kind, record_id, title, source, file, updated_at, status, image_count, draft_id,
            available, primary_label, primary_url, paths=None):
        path = relative_path(file.relative_path if file else source.get('relative_path'))
        scopes = paths if paths is not None else [path]
        if clean_directory and not any(in_directory(relative_path(p), clean_directory) for p in scopes):
            return
        item = {'id': f'{kind}:{record_id}', 'kind': kind, 'title': title or '未命名课程创作',
                'university': source.get('university') or (file.university if file else ''),
                'course_code': source.get('course_code') or (file.course_code if file else ''),
                'filename': source.get('filename') or (file.filename if file else ''), 'relative_path': path,
                'file_id': file.id if file else None, 'revision_id': source.get('revision_id'),
                'updated_at': updated_at.isoformat() if updated_at else '', 'status': status,
                'image_count': image_count, 'draft_id': draft_id, 'draft_available': available,
                'primary_label': primary_label, 'primary_url': primary_url,
                'source_url': library_url(path, library_file_id=file.id) if file else None}
        needle = q.strip().casefold()
        if needle and needle not in ' '.join(str(item[k] or '') for k in ('title', 'university', 'course_code', 'filename', 'relative_path')).casefold():
            return
        items.append(item)

    pairs = db.execute(select(CourseResearchDraft, CourseResearch).join(CourseResearch,
        CourseResearchDraft.research_id == CourseResearch.id).where(
        CourseResearchDraft.user_id == user.id, CourseResearch.user_id == user.id)).all()
    for row, research in pairs:
        context, brief = research.context or {}, row.brief or {}
        materials = [m for m in brief.get('materials', []) if isinstance(m, dict)]
        owned_materials = [m for m in materials if m.get('file_id') in files]
        if file_id is not None and not any(m.get('file_id') == file_id for m in owned_materials):
            continue
        chosen = next((m for m in owned_materials if m.get('file_id') == file_id), None) if file_id else None
        if chosen is None:
            chosen = next((m for m in owned_materials if in_directory(files[m['file_id']].relative_path, clean_directory)), None)
        chosen = chosen or (owned_materials[0] if owned_materials else {})
        file = files.get(chosen.get('file_id'))
        source = {**context, **(chosen.get('source') or {})}
        source['relative_path'] = file.relative_path if file else relative_path(context.get('library_directory'))
        draft = drafts.get(row.draft_id)
        binding = {'draft_id': row.draft_id, 'user_id': row.user_id,
                   'copy': {'title': row.title, 'body': row.body, 'tags': row.tags},
                   **(brief.get('draft_binding') or {})}
        available = bool(draft and linked_draft_is_current(draft, row.reviewed_at, binding))
        status = {'generating': 'processing', 'failed': 'failed'}.get(row.status,
            'draft_saved' if available else 'copy_saved' if row.status == 'saved' else 'copy_pending')
        directory_path = relative_path(context.get('library_directory'))
        if not directory_path and file:
            directory_path = str(PurePosixPath(file.relative_path).parent)
        url = '/platforms/xhs/course-center?' + urlencode({'library_dir': directory_path,
            'library_view': 'research', 'research_id': research.id, 'research_draft_id': row.id,
            **({'file_id': file.id} if file else {})})
        paths = [files[m['file_id']].relative_path for m in owned_materials] or [directory_path]
        add('research', row.id, row.title, source, file, max(row.created_at, row.reviewed_at or datetime.min),
            status, 0, row.draft_id, available, '继续查看文案', url, paths)

    for row in db.scalars(select(CourseVisualWorkflow).where(CourseVisualWorkflow.user_id == user.id)):
        if file_id is not None and row.file_id != file_id:
            continue
        data = row.data or {}
        file = files.get(row.file_id)
        exported = data.get('export') or {}
        draft_id = exported.get('draft_id')
        draft = drafts.get(draft_id)
        binding = {'draft_id': draft_id, 'user_id': row.user_id, 'copy': data.get('copy'), **(exported.get('snapshot') or {})}
        available = bool(draft and linked_draft_is_current(draft, exported.get('at'), binding))
        images = data.get('images') or []
        add('visual', row.id, (data.get('copy') or {}).get('title') or data.get('label'), data.get('source') or {}, file,
            row.updated_at, visual_status(data, available), len(images) or int(bool(data.get('cover'))),
            draft_id, available, '继续查看图文', '/platforms/xhs/visual-workbench?' + urlencode({'run': row.id}))

    platform_pairs=db.scalars(select(CoursePlatformPair).where(CoursePlatformPair.user_id==user.id).order_by(CoursePlatformPair.id)).all()
    paired={package_id:pair.id for pair in platform_pairs for package_id in pair.xhs_history}
    for row in db.scalars(select(CourseLibraryDraft).where(CourseLibraryDraft.user_id == user.id)):
        if file_id is not None and row.file_id != file_id:
            continue
        file = files.get(row.file_id)
        source = {**(row.source_snapshot or {}), 'revision_id': row.revision_id}
        draft = drafts.get(row.draft_id)
        binding = {'draft_id': row.draft_id, 'user_id': row.user_id,
                   'copy': {'title': row.title, 'body': row.body, 'tags': row.tags},
                   **(source.get('draft_binding') or {})}
        available = bool(draft and linked_draft_is_current(draft, row.reviewed_at, binding))
        status = {'generating': 'processing', 'failed': 'failed'}.get(row.status,
            'draft_saved' if available else 'images_reviewed' if row.status == 'saved' else 'images_pending')
        path = file.relative_path if file else relative_path(source.get('relative_path'))
        url = library_url(path, library_file_id=row.file_id, package_id=row.id)
        if row.id in paired:url=library_url(path,library_file_id=row.file_id,dual_drafts=1,platform_pair_id=paired[row.id])
        add('pdf', row.id, row.title, source, file, max(row.created_at, row.reviewed_at or datetime.min),
            status, len(row.images or []), row.draft_id, available, '查看两平台稿与历史' if row.id in paired else '继续审核文案与样张', url)

    items.sort(key=lambda item: (item['updated_at'], item['id']), reverse=True)
    return {'items': items[offset:offset + limit], 'total': len(items), 'limit': limit, 'offset': offset}
