"""Recover course provenance without changing existing drafts or attachments."""
from pathlib import PurePosixPath
from datetime import datetime, timedelta
import re
from urllib.parse import unquote, urlencode, urlsplit
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from backend.app.models import AiDraft, DraftAsset
from backend.app.models.course_center import CourseContentLink
from backend.app.models.course_library import CourseLibraryFile
from backend.app.models.course_library_draft import CourseLibraryDraft
from backend.app.models.course_research import CourseResearch, CourseResearchDraft
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.services import course_visual_workflow as flow


def _tags(values):
    return [str(v.get('name', '') if isinstance(v, dict) else v).strip().lstrip('#') for v in (values or [])]


def _copy(value):
    return {'title': value.get('title', ''), 'body': value.get('body', ''), 'tags': _tags(value.get('tags', []))}


def _assets(values):
    return [{'asset_type': a.get('asset_type', 'image'), 'local_path': a.get('local_path', ''),
             'url': '' if a.get('local_path') else a.get('url', '')} for a in values]


def _timestamp(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.astimezone(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None) if value.tzinfo else value


def draft_binding(draft):
    """Immutable identity stored when a reviewed result creates a draft."""
    return {'draft_id': draft.id, 'user_id': draft.user_id, 'draft_created_at': draft.created_at.isoformat()}


def linked_draft_is_current(draft, linked_at, snapshot=None):
    """Reject a recycled numeric ID; editing copy does not change a new binding.

    Old saves recorded a separate completion timestamp rather than the draft's
    creation timestamp. Accept that weaker evidence only within one second and
    with a complete copy match or the exact protected local asset set. This is
    a conservative same-save window, not a claim about SQLite timestamp precision.
    A legacy draft edited so that neither proof remains is unverified; never use
    a title/course substring or ID precedence to guess its origin.
    Callers must fetch the draft under the source owner's user_id first.
    """
    if draft is None:
        return False
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    if snapshot.get('draft_id', draft.id) != draft.id or snapshot.get('user_id', draft.user_id) != draft.user_id:
        return False
    created_at = _timestamp(draft.created_at)
    if created_at is None:
        return False
    if 'draft_created_at' in snapshot:
        return _timestamp(snapshot['draft_created_at']) == created_at
    completed_at = _timestamp(linked_at)
    if completed_at is None or not timedelta(0) <= completed_at - created_at < timedelta(seconds=1):
        return False
    copy = snapshot.get('copy')
    if isinstance(copy, dict) and all(key in copy for key in ('title', 'body', 'tags')):
        if _copy(copy) == _copy({'title': draft.title, 'body': draft.body, 'tags': draft.tags}):
            return True
    materials, current = snapshot.get('materials'), snapshot.get('current_materials')
    if (isinstance(materials, list) and materials and isinstance(current, list)
            and all(isinstance(a, dict) for a in [*materials, *current])):
        expected = _assets(materials)
        protected = re.compile(rf'^xhs-asset-u{draft.user_id}-(?:workflow|pdf-review)-')
        if all(a['local_path'] and protected.match(a['local_path']) for a in expected):
            # Reordering preserves asset identity while comparison still reports it.
            key = lambda a: (a['asset_type'], a['local_path'], a['url'])
            return sorted(expected, key=key) == sorted(_assets(current), key=key)
    return False


def _review(status='not_recorded', at=None):
    return {'status': status, 'at': at}


def _source(source):
    # Public metadata for this owner; never expose source absolute paths.
    return {k: source.get(k) for k in ('university', 'course_code', 'filename', 'term', 'material_type', 'revision_id', 'sha256') if source.get(k) is not None}


def _comparison(draft, assets, copy=None, materials=None, verified=False):
    changes = []
    if copy is not None:
        expected, current = _copy(copy), _copy({'title': draft.title, 'body': draft.body, 'tags': draft.tags})
        changes += [label for key, label in [('title', '标题'), ('body', '正文'), ('tags', '标签')] if expected[key] != current[key]]
    if materials is not None and _assets(materials) != _assets(assets):
        changes.append('图片或素材顺序')
    return {'status': 'modified' if changes else 'unchanged' if verified and copy is not None and materials is not None else 'unknown',
            'changed_fields': changes}


def _workflow_snapshot(data, exported, user_id, run_id):
    recorded = exported.get('snapshot')
    if isinstance(recorded, dict) and recorded.get('version') == 1:
        approvals = recorded.get('approvals') or {}
        complete = bool(isinstance(recorded.get('source'), dict) and isinstance(recorded.get('copy'), dict)
                        and isinstance(recorded.get('materials'), list)
                        and recorded.get('workflow_digest') and recorded['workflow_digest'] == exported.get('digest')
                        and approvals.get('set', {}).get('digest') == recorded['workflow_digest']
                        and all(approvals.get(stage, {}).get('at') for stage in ('copy', 'cover', 'set')))
        return {'source': recorded.get('source', {}), 'copy': recorded.get('copy'), 'materials': recorded.get('materials'),
                'revision': recorded.get('workflow_revision'), 'research_id': recorded.get('source_research_id'),
                'reviews': {stage: _review('confirmed', approvals[stage].get('at')) if complete else _review() for stage in ('copy', 'cover', 'set')},
                'complete': complete, 'kind': 'export_snapshot'}
    # The pre-existing workflow snapshots retain all content and review fingerprints.
    try:
        complete = bool(exported.get('digest') == flow.fingerprint(data, 'set') and all(
            flow.approved(data, stage) and data['approvals'][stage].get('at') for stage in ('copy', 'cover', 'set')))
    except (KeyError, TypeError):
        complete = False
    images = data.get('images')
    materials = None if not isinstance(images, list) or any(not a.get('id') for a in images) else [
        {'asset_type': 'image', 'url': '', 'local_path': f'xhs-asset-u{user_id}-workflow-{run_id}-{a["id"]}.png'} for a in images]
    return {'source': data.get('source', {}), 'copy': data.get('copy'), 'materials': materials, 'revision': data.get('revision'),
            'research_id': data.get('research_id'), 'reviews': {stage: _review('confirmed', data['approvals'][stage].get('at')) if complete else _review() for stage in ('copy', 'cover', 'set')},
            'complete': complete, 'kind': 'legacy_workflow_snapshot'}


def course_origins(db, user_id, draft_ids):
    # Ignore IDs belonging to another owner even when called outside the list API.
    drafts = {d.id: d for d in db.scalars(select(AiDraft).where(AiDraft.user_id == user_id, AiDraft.id.in_(set(draft_ids))))}
    wanted = set(drafts)
    result = {}
    if not wanted:
        return result
    current_assets = {i: [] for i in wanted}
    for a in db.scalars(select(DraftAsset).where(DraftAsset.draft_id.in_(wanted)).order_by(DraftAsset.sort_order, DraftAsset.id)):
        current_assets[a.draft_id].append({'asset_type': a.asset_type, 'url': a.url, 'local_path': a.local_path})
    # Historical exports remain protected after a later edit clears current export.
    for run in db.scalars(select(CourseVisualWorkflow).where(CourseVisualWorkflow.user_id == user_id)):
        data = run.data or {}
        for snapshot in [data, *reversed(data.get('history', []))]:
            exported = snapshot.get('export') or {}
            draft_id = exported.get('draft_id')
            if draft_id not in wanted or draft_id in result:
                continue
            saved = _workflow_snapshot(snapshot, exported, user_id, run.id)
            binding = exported.get('snapshot') if isinstance(exported.get('snapshot'), dict) else {}
            if not linked_draft_is_current(drafts[draft_id], exported.get('at'), {
                    **binding, 'copy': saved['copy'], 'materials': saved['materials'],
                    'current_materials': current_assets[draft_id]}):
                continue
            source = saved['source'] or {}
            result[draft_id] = {'kind': 'visual_workflow', 'workflow_id': run.id, 'revision': snapshot.get('revision'),
                'brand_name': (snapshot.get('brand') or {}).get('name', ''),
                'file_id': run.file_id, 'course_code': source.get('course_code', ''),
                'label': '课程图文工作台', 'href': f'/platforms/xhs/visual-workbench?run={run.id}',
                'source': _source(source), 'workflow_revision': saved['revision'], 'research_id': saved['research_id'],
                'exported_at': exported.get('at'), 'snapshot_complete': saved['complete'], 'snapshot_kind': saved['kind'],
                'review_snapshot': saved['reviews'], 'snapshot_note': '已保留导出时的审核记录' if saved['complete'] else '旧稿未记录完整快照',
                'comparison': _comparison(drafts[draft_id], current_assets[draft_id],
                    saved['copy'] if saved['complete'] else None, saved['materials'] if saved['complete'] else None, saved['complete'])}
    for package in db.scalars(select(CourseLibraryDraft).where(CourseLibraryDraft.user_id == user_id, CourseLibraryDraft.draft_id.in_(wanted))):
        file = db.get(CourseLibraryFile, package.file_id)
        if not file or file.user_id != user_id:
            continue
        directory = str(PurePosixPath(file.relative_path).parent)
        reviewed = package.status == 'saved' and package.reviewed_at is not None
        materials = [{'asset_type': 'image', 'url': '', 'local_path': f'xhs-asset-u{user_id}-pdf-review-{package.id}-{i}-{a["sha256"][:12]}.png'} for i, a in enumerate(package.images or []) if a.get('sha256')]
        if not linked_draft_is_current(drafts[package.draft_id], package.reviewed_at, {
                **((package.source_snapshot or {}).get('draft_binding') or {}),
                'copy': {'title': package.title, 'body': package.body, 'tags': package.tags},
                'materials': materials, 'current_materials': current_assets[package.draft_id]}):
            continue
        result.setdefault(package.draft_id, {'kind': 'pdf_review', 'file_id': file.id, 'course_code': file.course_code,
            'brand_name': ((package.source_snapshot or {}).get('preview_brand') or {}).get('name', ''),
            'label': '原 PDF 与样张', 'href': '/platforms/xhs/course-center?' + urlencode({'library_dir': directory, 'library_file_id': file.id, 'package_id': package.id}),
            'source': _source(package.source_snapshot or {}), 'package_id': package.id,
            'snapshot_complete': False, 'snapshot_note': '旧样张流程采用文案与样张统一审核，未单独记录封面审核',
            'review_snapshot': {'copy': _review('confirmed' if reviewed else 'not_recorded', package.reviewed_at.isoformat() if reviewed else None),
                'cover': _review(), 'set': _review('confirmed' if reviewed else 'not_recorded', package.reviewed_at.isoformat() if reviewed else None)},
            'comparison': _comparison(drafts[package.draft_id], current_assets[package.draft_id], {'title': package.title, 'body': package.body, 'tags': package.tags}, materials, reviewed)})
    for item in db.scalars(select(CourseResearchDraft).where(CourseResearchDraft.user_id == user_id, CourseResearchDraft.draft_id.in_(wanted))):
        research = db.get(CourseResearch, item.research_id)
        if not research or research.user_id != user_id:
            continue
        context = research.context or {}
        materials = (item.brief or {}).get('materials', [])
        source = materials[0].get('source', {}) if materials else {}
        reviewed = item.status == 'saved' and item.reviewed_at is not None
        if not linked_draft_is_current(drafts[item.draft_id], item.reviewed_at, {
                **((item.brief or {}).get('draft_binding') or {}),
                'copy': {'title': item.title, 'body': item.body, 'tags': item.tags}}):
            continue
        result.setdefault(item.draft_id, {'kind': 'course_research', 'research_id': research.id,
            'brand_name': ((item.brief or {}).get('options') or {}).get('brand', ''),
            'course_code': context.get('course_code', ''), 'label': '课程选题研究',
            'href': '/platforms/xhs/course-center?' + urlencode({'library_dir': context.get('library_directory', ''), 'library_view': 'research',
                'research_id': research.id, 'research_draft_id': item.id, **({'file_id': materials[0]['file_id']} if materials and materials[0].get('file_id') else {})}),
            'source': {**_source(context), **_source(source)}, 'materials': [_source(m.get('source', {})) for m in materials],
            'snapshot_complete': False, 'snapshot_note': '此研究稿仅审核文案，未记录封面与整套图片审核',
            'review_snapshot': {'copy': _review('confirmed' if reviewed else 'not_recorded', item.reviewed_at.isoformat() if reviewed else None), 'cover': _review('not_applicable'), 'set': _review('not_applicable')},
            'comparison': _comparison(drafts[item.draft_id], current_assets[item.draft_id], {'title': item.title, 'body': item.body, 'tags': item.tags}, [], reviewed)})
    for link in db.scalars(select(CourseContentLink).where(CourseContentLink.user_id == user_id,
            CourseContentLink.target_kind == 'draft', CourseContentLink.target_is_demo.is_(False), CourseContentLink.target_id.in_(wanted))):
        # A manual course link has no immutable draft identity/copy snapshot.
        # It cannot safely identify a draft whose integer primary key was reused.
        if not linked_draft_is_current(drafts[link.target_id], link.created_at):
            continue
        result.setdefault(link.target_id, {'kind': 'course', 'label': '课程与资料中心', 'href': '/platforms/xhs/course-center',
            'snapshot_complete': False, 'snapshot_note': '旧稿未记录完整快照', 'comparison': {'status': 'unknown', 'changed_fields': []}})
    return result


def reference_key(reference):
    """Treat local media URLs, filenames and absolute media URLs equivalently."""
    parsed = urlsplit(reference)
    path = unquote(parsed.path)
    name = PurePosixPath(path).name
    if '/api/files/media/' in path or '/' not in path:
        return name
    return reference.split('#', 1)[0]


def ensure_generic_image_allowed(db, user, references, draft_id=None, asset_id=None):
    candidate_ids = set()
    if draft_id is not None:
        draft = db.get(AiDraft, draft_id)
        if not draft or draft.user_id != user.id:
            raise HTTPException(404, 'Draft not found')
        candidate_ids.add(draft.id)
    if asset_id is not None:
        asset = db.get(DraftAsset, asset_id)
        draft = db.get(AiDraft, asset.draft_id) if asset else None
        if not draft or draft.user_id != user.id or (draft_id is not None and draft.id != draft_id):
            raise HTTPException(404, 'Asset not found')
        candidate_ids.add(draft.id)
    keys = {reference_key(ref) for ref in references}
    # Recognize protected exported files even if their draft association was removed.
    protected_path = any(re.search(r'xhs-asset-u\d+-(?:workflow|pdf-review)-', unquote(ref))
        or '/course-center/visual-workflows/' in unquote(ref)
        or '/course-center/library/draft-reviews/' in unquote(ref) for ref in references)
    if keys:
        assets = db.execute(select(DraftAsset, AiDraft.id).join(AiDraft, DraftAsset.draft_id == AiDraft.id).where(AiDraft.user_id == user.id)).all()
        for asset, owner_draft_id in assets:
            if any(value and reference_key(value) in keys for value in (asset.url, asset.local_path)):
                candidate_ids.add(owner_draft_id)
    if protected_path or course_origins(db, user.id, candidate_ids):
        raise HTTPException(409, '课程图片包含真实讲义、公式或品牌，请返回课程制作入口修改；通用图片润色不会发送这些素材')
