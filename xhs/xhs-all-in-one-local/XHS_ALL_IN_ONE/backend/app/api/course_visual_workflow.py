"""Human-reviewed course → research → copy → visual direction → new local draft."""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import re
import shutil
import subprocess
import sys
from typing import Literal
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session
from sqlalchemy.orm.exc import StaleDataError
from backend.app.api import course_research as research
from backend.app.api.ai import get_text_ai_client
from backend.app.api.course_library import require_library
from backend.app.api.course_library_drafts import PlanRequest, build_plan, stable_source, unchanged, text_model
from backend.app.api.platforms.xhs import pc
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.security import decrypt_text
from backend.app.core.time import shanghai_now
from backend.app.models import AiDraft, DraftAsset, User
from backend.app.models.course_library import CourseLibraryFile
from backend.app.models.course_research import CourseResearch
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.services import course_visual_workflow as flow
from backend.app.services import course_visual_background as background
from backend.app.services import course_visual_presets as presets
from backend.app.services import course_visual_trace as trace
from backend.app.services import course_pdf_analysis as pdf_analysis
from backend.app.services import course_visual_api_images as api_images
from backend.app.services.course_brands import brands, resolve_brand, select_bundle, logo_path
from backend.app.services.course_draft_images import PREVIEW_LAYOUT, PREVIEW_WIDTH, HEADER_HEIGHT, preview_brand

router = APIRouter(prefix='/course-center/visual-workflows', tags=['course-visual-workflow'])


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Create(Strict):
    file_id: int
    revision_id: int
    request_key: UUID
    template_id: Literal['legacy', 'question-led', 'decision-map', 'sample-led', 'magazine-a'] = 'legacy'
    entry_mode: Literal['pdf-driven', 'xhs-research'] = 'xhs-research'
    brand_id: str = Field(default='', max_length=80)


class ResearchTransferPlan(Strict):
    research_id: int
    research_draft_id: int
    file_id: int
    revision_id: int


class ResearchTransfer(ResearchTransferPlan):
    reviewed: bool = False
    limited_sources_reviewed: bool = False
    review_digest: str = Field(min_length=64, max_length=64)
    request_key: UUID


class Version(Strict):
    expected_version: int


class Copy(Strict):
    topic: str = Field(default='', max_length=240)
    title: str = Field(default='', max_length=256)
    body: str = Field(default='', max_length=6000)
    tags: list[str] = Field(default_factory=list, max_length=10)
    takeaway: str = Field(default='', max_length=600)
    goal: Literal['student-question', 'method-save', 'sample-trial'] | None = None


class PdfTopicPlan(Strict):
    file_id: int
    revision_id: int
    topic: str = Field(default='', max_length=240)
    goal: Literal['student-question', 'method-save', 'sample-trial'] = 'student-question'
    brand_id: str = Field(default='', max_length=80)


class Brief(Strict):
    title: str = Field(default='', max_length=60)
    subtitle: str = Field(default='', max_length=80)
    text: str = Field(default='', max_length=800)
    layout: Literal['editorial', 'flow', 'comparison', 'product-hero', 'evidence-grid', 'full-page', 'pdf-grid-2x2'] = 'editorial'
    nodes: list[str] = Field(default_factory=list, max_length=5)


class VisualPlan(Strict):
    cover_lines: list[str] = Field(default_factory=list, max_length=2)
    cover_subtitle: str | None = Field(default=None, max_length=80)
    method_title: str = Field(default='把方法连接到独立解题', max_length=40)
    method_text: str = Field(default='', max_length=800)
    sample_pages: list[int] = Field(min_length=1, max_length=4)
    cover_sample_page: int | None = Field(default=None, ge=2)
    sample_instructions: list[str] = Field(default_factory=list, max_length=4)
    usage_steps: list[str] = Field(min_length=1, max_length=5)
    cta: str = Field(max_length=180)
    style: Literal['product-editorial', 'evidence-editorial'] = 'product-editorial'
    method_layout: Literal['editorial', 'flow', 'comparison'] = 'editorial'
    method_nodes: list[str] = Field(default_factory=list, max_length=4)
    template_id: Literal['legacy', 'question-led', 'decision-map', 'sample-led', 'magazine-a'] = 'legacy'
    density: Literal['compact', 'standard'] = 'standard'


class SetExplanation(Strict):
    title: str = Field(min_length=1, max_length=40)
    subtitle: str = Field(default='', max_length=80)
    text: str = Field(min_length=1, max_length=800)
    layout: Literal['editorial', 'flow', 'comparison'] = 'editorial'
    nodes: list[str] = Field(default_factory=list, max_length=5)

    @field_validator('title', 'text')
    @classmethod
    def meaningful_content(cls, value):
        if not value.strip():
            raise ValueError('补充讲解的标题和正文不能为空')
        return value


class SetPlan(Strict):
    sample_pages: list[int] = Field(min_length=1, max_length=4)
    sample_instructions: list[str] = Field(default_factory=list, max_length=4)
    extra_explanations: list[SetExplanation] = Field(default_factory=list, max_length=3)


class EditableExplanation(Strict):
    title: str = Field(default='', max_length=40)
    subtitle: str = Field(default='', max_length=80)
    text: str = Field(default='', max_length=800)
    layout: Literal['editorial', 'flow', 'comparison'] = 'editorial'
    nodes: list[str] = Field(default_factory=list, max_length=5)


class EditableSetPlan(Strict):
    sample_pages: list[int] = Field(min_length=1, max_length=4)
    sample_instructions: list[str] = Field(default_factory=list, max_length=4)
    extra_explanations: list[EditableExplanation] = Field(default_factory=list, max_length=3)


class CollagePlan(Strict):
    groups: list[list[int]] = Field(min_length=2, max_length=2)

    @field_validator('groups')
    @classmethod
    def distinct_full_groups(cls, groups):
        if any(len(group) != 4 for group in groups):
            raise ValueError('两张四宫格分别需要4个真实PDF页')
        pages = [page for group in groups for page in group]
        if len(set(pages)) != 8 or any(page < 2 for page in pages):
            raise ValueError('两张四宫格共需8个不同的正文页，页码从第2页开始')
        return groups


class PdfPagePlan(Strict):
    pages: list[int] = Field(min_length=8, max_length=9)

    @field_validator('pages')
    @classmethod
    def unique_sorted_pages(cls, pages):
        if len(set(pages)) != len(pages) or any(page < 2 for page in pages):
            raise ValueError('末尾预览需要8或9个不同的真实PDF正文页，页码从第2页开始')
        return sorted(pages)


class Edit(Version):
    visual_candidate_reviewed: bool = False
    copy: Copy | None = None
    visual_plan: VisualPlan | None = None
    set_plan: EditableSetPlan | None = None
    collage_plan: CollagePlan | None = None
    pdf_page_plan: PdfPagePlan | None = None
    selected_source_ids: list[str] | None = Field(default=None, max_length=8)


class Search(Version):
    keyword: str = Field(min_length=1, max_length=120)
    account_id: int
    sort: int = Field(default=2, ge=0, le=4)


class Read(Version):
    source_id: str
    account_id: int


class Generate(Version):
    stage: Literal['cover', 'set']


class GenerateBundle(Version):
    request_key: UUID


class AppendCollages(Version):
    request_key: UUID
    collage_plan: CollagePlan


class AppendPdfPages(Version):
    request_key: UUID
    pdf_page_plan: PdfPagePlan


class Revise(Version):
    asset_id: str
    brief: Brief


class BackgroundPlan(Version):
    slot: str = Field(default='cover', max_length=40)
    style: Literal['paper-depth', 'linear-geometry', 'quiet-paper'] = 'paper-depth'
    strength: Literal['light', 'balanced'] = 'balanced'


class BackgroundGenerate(BackgroundPlan):
    local_only: bool = False
    external_consent: bool = False
    plan_digest: str
    request_key: UUID


class Approve(Version):
    stage: Literal['copy', 'cover', 'set']
    reviewed: bool = False
    limited_sources_reviewed: bool = False
    digest: str
    combined_review: bool = False


class Export(Version):
    reviewed: bool = False
    digest: str


class AiGenerate(Version):
    external_consent: bool = False
    plan_digest: str
    request_key: UUID


class ApiImagePlan(Version):
    target: Literal['bundle', 'cover', 'method', 'method-extra-0', 'method-extra-1'] = 'bundle'


class ApiImageGenerate(ApiImagePlan):
    external_consent: bool = False
    plan_digest: str = Field(min_length=64, max_length=64)
    request_key: UUID


class EntryMode(Version):
    entry_mode: Literal['pdf-driven', 'xhs-research']


class Restore(Version):
    revision: int


class SelectTemplate(Version):
    template_id: Literal['legacy', 'question-led', 'decision-map', 'sample-led', 'magazine-a']


def commit(db):
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise HTTPException(409, '工作台已在其他页面更新，请刷新后重试')


def owned(db, user, run_id, version=None):
    row = db.get(CourseVisualWorkflow, run_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, '图文工作记录不存在')
    if version is not None and row.row_version != version:
        raise HTTPException(409, '当前内容版本已变化，请刷新后重试')
    if version is not None and row.data.get('operation', {}).get('status') == 'generating':
        raise HTTPException(409, '当前内容正在生成，请等待完成后再编辑')
    return row


def directory(settings, user, row):
    return Path(settings.storage_dir) / 'course-visual' / f'u{user.id}' / f'r{row.id}'


def asset_path(settings, user, row, asset):
    root = directory(settings, user, row).resolve()
    path = (root / asset['path']).resolve()
    if not path.is_relative_to(root) or path.suffix != '.png' or not path.is_file() or path.is_symlink():
        raise HTTPException(404, '图稿文件不存在')
    if flow.hash_file(path) != asset['sha256']:
        raise HTTPException(409, '图片指纹已变化，请重新生成并审核')
    return path


def source_fd(db, user, settings, row):
    file, root, revision, fd = stable_source(db, user, settings, row.file_id, row.data['source']['revision_id'])
    if revision.sha256 != row.data['source']['sha256']:
        os.close(fd)
        raise HTTPException(409, '资料版本变化，请新建工作记录，旧稿保留')
    return file, root, fd


def image_view(asset, row):
    return {k: v for k, v in asset.items() if k not in {'path'}} | {'url': f'/course-center/visual-workflows/{row.id}/images/{asset["id"]}'}


def export_draft_available(db, row, state):
    from backend.app.services.course_draft_origin import linked_draft_is_current
    exported = state.get('export') or {}
    draft = db.get(AiDraft, exported.get('draft_id')) if db is not None and exported.get('draft_id') else None
    if draft is None or draft.user_id != row.user_id:
        return False
    snapshot = exported.get('snapshot') if isinstance(exported.get('snapshot'), dict) else {}
    materials = [{'asset_type': 'image', 'url': '', 'local_path': f'xhs-asset-u{row.user_id}-workflow-{row.id}-{a["id"]}.png'}
                 for a in state.get('images', []) if a.get('id')]
    actual = db.scalars(select(DraftAsset).where(DraftAsset.draft_id == draft.id).order_by(DraftAsset.sort_order, DraftAsset.id)).all()
    return linked_draft_is_current(draft, exported.get('at'), {
        'draft_id': exported['draft_id'], 'user_id': row.user_id,
        'copy': state.get('copy'), 'materials': materials, **snapshot,
        'current_materials': [{'asset_type': a.asset_type, 'url': a.url, 'local_path': a.local_path} for a in actual]})


def export_view(db, row, state):
    exported = state.get('export')
    return {**exported, 'draft_available': export_draft_available(db, row, state)} if exported else None


def evidence_review(items):
    """Describe acquired evidence without inventing readers, demand or missing detail.

    A local visual handoff is allowed with a deliberately acknowledged research
    limit. This never upgrades a search excerpt to retrieved note/comment evidence.
    """
    sources = [item for item in items if not item.get('excluded')]
    if sources and all(item.get('evidence_type') == 'pdf-analysis' for item in sources):
        return {'source_count': len(sources), 'detail_count': 0, 'comments_read': 0, 'limited': False,
                'basis': 'pdf-analysis', 'message': '本篇依据同版本PDF提炼学习难点与资料卖点；属于教学分析，未执行小红书评论需求验证。'}
    detail_count = sum(item.get('content_status') == 'detail' for item in sources)
    comments_read = sum(len(item.get('comments') or []) for item in sources)
    limited = detail_count == 0
    if not sources:
        message = '尚未选择参考来源，请先选择本课相关来源。'
    elif limited:
        message = (f'当前参考来源仅有搜索摘要或手动摘录，未读取完整笔记正文；已记录 {comments_read} 条评论。'
                   '摘要只能作为选题线索，不代表已验证的学生问题、全站热榜或购买需求。'
                   '明确接受此范围后可继续制作本机图文，不会补写缺失正文或评论。')
    else:
        message = (f'已读取 {detail_count} 篇笔记正文，已记录 {comments_read} 条评论。'
                   '这些是本次取得的参考样本，不代表已验证的学生身份、全站热榜或购买需求。')
    return {'source_count': len(sources), 'detail_count': detail_count,
            'comments_read': comments_read, 'limited': limited, 'message': message}


def view(row):
    db = object_session(row)
    d = deepcopy(row.data)
    d['evidence_review'] = evidence_review([item for item in d.get('evidence', [])
        if item.get('id') in d.get('selected_source_ids', [])])
    d['export'] = export_view(db, row, row.data)
    d['cover'] = image_view(d['cover'], row) if d.get('cover') else None
    d['images'] = [image_view(a, row) for a in d.get('images', [])]
    d['history'] = [{'revision': h['revision'], 'reason': h['reason'], 'at': h['at'], 'title': h['copy']['title'],
                     'images': [image_view(a, row) for a in h.get('images', [])],
                     'cover': image_view(h['cover'], row) if h.get('cover') else None, 'export': export_view(db, row, h)} for h in d.get('history', [])]
    return {'id': row.id, 'file_id': row.file_id, 'row_version': row.row_version, 'data': d,
            'direction': flow.direct(row.data), 'production': flow.production_status(row.data), 'quality': presets.quality(row.data),
            'collage_status': flow.collage_status(row.data),
            'pdf_page_status': flow.pdf_page_status(row.data),
            'approved': {s: flow.approved(row.data, s) for s in ['copy', 'cover', 'set']},
            'digests': {s: flow.fingerprint(row.data, s) for s in ['copy', 'cover', 'set']},
            'publishing_enabled': False, 'automatic_operations_enabled': False}


@router.get('/catalog')
def get_catalog(q: str = Query('', max_length=180), file_id: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    bundle = flow.catalog()
    query = select(CourseLibraryFile).where(CourseLibraryFile.user_id == user.id, CourseLibraryFile.status == 'ready')
    if q.strip():
        query = query.where(CourseLibraryFile.filename.contains(q.strip()) | CourseLibraryFile.course_code.contains(q.strip()))
    rows = db.scalars(query.order_by(CourseLibraryFile.updated_at.desc()).limit(100)).all()
    if file_id is not None:
        chosen = db.get(CourseLibraryFile, file_id)
        if chosen is None or chosen.user_id != user.id or chosen.status != 'ready': raise HTTPException(404, '所选资料不可用')
        rows = [chosen, *[f for f in rows if f.id != chosen.id]]
    return {**presets.choices(), 'brand': bundle['brand'], 'brands': brands(), 'rules': bundle['rules'], 'version': bundle['version'],
            'skills': bundle['skills'], 'materials': [{'id': f.id, 'filename': f.filename, 'course_code': f.course_code, 'university': f.university, 'revision_id': f.current_revision_id} for f in rows]}


@router.get('/brands')
def brand_choices(user: User = Depends(get_current_user), settings=Depends(require_library)):
    return {'items': brands()}


@router.get('/brand/logo')
def logo(brand_id: str = 'xingtu', user: User = Depends(get_current_user), settings=Depends(require_library)):
    brand = resolve_brand(brand_id)
    return FileResponse(logo_path(brand), media_type='image/png' if brand['logo'].endswith('.png') else 'image/jpeg', headers={'Cache-Control':'private, no-store'})


@router.get('/template-previews/{template_id}')
def template_preview(template_id: str, user: User = Depends(get_current_user), settings=Depends(require_library)):
    path = presets.preview_path(template_id)
    if path is None or not path.is_file() or path.is_symlink() or path.parent.is_symlink():
        raise HTTPException(404, '该模板暂只有版式示意，尚无渲染样例')
    if not path.resolve().is_relative_to(presets.RESOURCES.resolve() / 'template_previews'):
        raise HTTPException(404, '模板预览位置不可用')
    manifest = path.parent / 'manifest.json'
    try:
        content = json.loads(manifest.read_text()) if manifest.is_file() and not manifest.is_symlink() else {}
        entry = content.get(template_id) if isinstance(content, dict) else None
        expected = entry.get('sha256') if isinstance(entry, dict) else None
    except (ValueError, OSError):
        expected = None
    if not expected or flow.hash_file(path) != expected:
        raise HTTPException(409, '模板预览指纹不一致，请核对本机资源')
    return FileResponse(path, media_type='image/png')


@router.post('/{run_id}/fork')
def fork(run_id: int, payload: Version, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    original = owned(db, user, run_id, payload.expected_version)
    if (original.data.get('operation') or {}).get('status') == 'generating':
        raise HTTPException(409, '当前记录仍在生成，请完成后再另建优化版本')
    # One initial optimization record per exact parent version. A repeated click
    # returns its record rather than duplicating a branch or copying approvals.
    key = f'fork-{original.id}-v{original.row_version}'
    previous = db.scalar(select(CourseVisualWorkflow).where(CourseVisualWorkflow.user_id == user.id, CourseVisualWorkflow.request_key == key))
    if previous is not None:
        return view(previous)
    data = deepcopy(original.data)
    data.update(revision=1, history=[], events=[], approvals={}, cover=None, images=[], export=None,
                page_overrides={}, backgrounds={}, background_requests={})
    data.pop('operation', None)
    data.pop('design_report', None)
    data.pop('display_treatment', None)
    for field in ('render_bundle', 'bundle_requests', 'collage_requests', 'pdf_page_requests'):
        data.pop(field, None)
    data.pop('collage_plan', None)
    if not data.get('pdf_page_plan'):
        planned = flow.default_pdf_page_plan(data['source']['page_count'])
        if planned is not None:
            data['pdf_page_plan'] = planned
    bundle = flow.catalog()
    data['rules'] = {'version': bundle['version'], 'skills': bundle['skills'], 'text': bundle['rules'], 'digest': bundle['contract_digest']}
    data['forked_from'] = {'run_id': original.id, 'row_version': original.row_version, 'revision': original.data['revision']}
    flow.event(data, 'fork_for_review', parent_run=original.id)
    result = CourseVisualWorkflow(user_id=user.id, file_id=original.file_id, request_key=key, data=data)
    db.add(result)
    try:
        commit(db)
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(CourseVisualWorkflow).where(CourseVisualWorkflow.user_id == user.id, CourseVisualWorkflow.request_key == key))
        if existing is None:
            raise
        return view(existing)
    return view(result)


@router.get('')
def history(file_id: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    query = select(CourseVisualWorkflow).where(CourseVisualWorkflow.user_id == user.id)
    if file_id is not None:
        file = db.get(CourseLibraryFile, file_id)
        if file is None or file.user_id != user.id:
            raise HTTPException(404, '所选资料不存在')
        query = query.where(CourseVisualWorkflow.file_id == file_id)
    rows = db.scalars(query.order_by(CourseVisualWorkflow.id.desc()).limit(100)).all()
    return {'items': [{'id': r.id, 'file_id': r.file_id, 'course_code': r.data['source']['course_code'], 'title': r.data.get('label') or r.data['copy']['title'] or r.data['source']['filename'], 'draft_id': (r.data.get('export') or {}).get('draft_id'),
                       'entry_mode': r.data.get('entry_mode', 'xhs-research'), 'revision_id': r.data['source']['revision_id']} for r in rows]}


@router.post('/pdf-topic-plan')
def preview_pdf_topics(payload: PdfTopicPlan, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    """Prepare the existing Skill pipeline without creating a run or calling AI."""
    bundle = select_bundle(flow.catalog(), payload.brand_id)
    source = build_plan(db, user, settings, payload.file_id, PlanRequest(revision_id=payload.revision_id, pages=[1], brand_id=payload.brand_id))['source']
    data = flow.initial_data(source, bundle, 'magazine-a', 'pdf-driven')
    data['copy'].update(topic=payload.topic, goal=payload.goal)
    transient = SimpleNamespace(file_id=payload.file_id, row_version=0, data=data)
    plan = pdf_analysis.public_plan(pdf_analysis.prepare(db, user, settings, transient))
    return {**plan, 'file_id': payload.file_id, 'preview_only': True}


@router.post('')
def create(payload: Create, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    bundle = select_bundle(flow.catalog(), payload.brand_id)
    old = db.scalar(select(CourseVisualWorkflow).where(CourseVisualWorkflow.user_id == user.id, CourseVisualWorkflow.request_key == str(payload.request_key)))
    if old:
        if old.file_id != payload.file_id or old.data['source']['revision_id'] != payload.revision_id:
            raise HTTPException(409, '同一请求对应的资料版本不同')
        if old.data.get('entry_mode', 'xhs-research') != payload.entry_mode:
            raise HTTPException(409, '同一创建请求的入口不同，请重新选择或显式切换入口')
        if resolve_brand(old.data['brand'].get('id') or old.data['brand']['name'])['id'] != bundle['brand']['id']:
            raise HTTPException(409, '同一请求的品牌已变化，请重新开始；原稿保留')
        return view(old)
    plan = build_plan(db, user, settings, payload.file_id, PlanRequest(revision_id=payload.revision_id, pages=[1], brand_id=payload.brand_id))
    data = flow.initial_data(plan['source'], bundle, payload.template_id, payload.entry_mode)
    trace.record(data, 'select_pdf', 'local_pdf_extract', inputs={'file_id': payload.file_id, 'revision_id': payload.revision_id},
                 outputs={'source': plan['source']}, scope='local_readonly_pdf; no_external_transfer')
    row = CourseVisualWorkflow(user_id=user.id, file_id=payload.file_id, request_key=str(payload.request_key), data=data)
    db.add(row); commit(db); db.refresh(row)
    return view(row)


def research_transfer_plan(db, user, settings, payload):
    origin = research.owned(db, user, payload.research_id)
    draft = research.owned_draft(db, user, origin.id, payload.research_draft_id)
    if draft.status not in {'pending', 'saved'}:
        raise HTTPException(409, '研究文案仍未完成，请先生成并保存可审核的文字')
    if not draft.title.strip() or not draft.body.strip() or len(draft.title) > 20 or len(draft.body) > 1000:
        raise HTTPException(422, '请先保存完整文案，标题不超过20字、正文不超过1000字，再进入图文制作')
    brief = draft.brief or {}; options = brief.get('options', {})
    bundle = select_bundle(flow.catalog(), options.get('brand'))
    material = build_plan(db, user, settings, payload.file_id, PlanRequest(revision_id=payload.revision_id, pages=[1], brand_id=bundle['brand']['id']))
    source = material['source']; context = origin.context
    normalize = lambda value: re.sub(r'\s+', '', str(value or '')).casefold()
    if not normalize(context.get('university')) or not normalize(context.get('course_code')) or any(
            normalize(context.get(k)) != normalize(source.get(k)) for k in ('university', 'course_code')):
        raise HTTPException(422, '所选PDF与研究的大学或课程代码不一致，请明确选择同校同课的资料')
    original_sources = brief.get('sources', [])
    source_ids = options.get('selected_ids') or [s.get('id') for s in original_sources]
    if not source_ids or len(source_ids) > 8 or len(set(source_ids)) != len(source_ids):
        raise HTTPException(422, '研究文案缺少明确的参考来源，请先核对本稿所用来源')
    by_id = {s['id']: s for s in origin.evidence if not s.get('excluded')}
    if any(s not in by_id for s in source_ids):
        raise HTTPException(409, '本稿所用来源已被排除或不存在，请先在研究中核对并保存新文案')
    evidence = flow.public_evidence([by_id[s] for s in source_ids])
    source_quality = evidence_review(evidence)
    original_by_id = {s.get('id'): s for s in flow.public_evidence(original_sources)}
    changed_sources = [s['id'] for s in evidence if flow.digest(s) != flow.digest(original_by_id.get(s['id']))]
    original_materials = brief.get('materials', [])
    original_material = next((m for m in original_materials if m.get('file_id') == payload.file_id), None)
    changed_material = not original_material or any(original_material.get('source', {}).get(k) != source[k] for k in ('revision_id', 'sha256'))
    copy = {'topic': options.get('topic') or draft.title, 'title': draft.title, 'body': draft.body, 'tags': deepcopy(draft.tags), 'takeaway': ''}
    snapshot = {'research_id': origin.id, 'research_draft_id': draft.id, 'context': deepcopy(context),
                'research_row_version': origin.row_version, 'draft_row_version': draft.row_version,
                'research_draft_digest': research.draft_view(draft, db)['review_digest'], 'research_draft_status': draft.status,
                'source_draft_id': draft.draft_id, 'source': source, 'copy': copy, 'evidence': evidence,
                'selected_source_ids': list(source_ids), 'source_quality': source_quality,
                'brand': bundle['brand'], 'rules_digest': bundle['contract_digest']}
    result = {**snapshot, 'changed_since_draft': {'sources': changed_sources, 'material': changed_material},
              'evidence_review': source_quality,
              'review_digest': flow.digest(snapshot),
              'scope': '承接当前研究文案、已选来源和明确选择的PDF版本；仅保存本机图文工作记录，不调用AI、不发布、不改变原稿。'}
    return result, origin, draft, bundle


@router.post('/from-research/plan')
def transfer_plan(payload: ResearchTransferPlan, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    return research_transfer_plan(db, user, settings, payload)[0]


@router.post('/from-research')
def transfer_research(payload: ResearchTransfer, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    signature = flow.digest(payload.model_dump(mode='json', exclude={'request_key'}))
    def previous():
        old = db.scalar(select(CourseVisualWorkflow).where(CourseVisualWorkflow.user_id == user.id, CourseVisualWorkflow.request_key == str(payload.request_key)))
        if old and old.data.get('research_handoff', {}).get('request_signature') != signature:
            raise HTTPException(409, '同一承接请求内容已变化，请重新核对后进入图文制作')
        return old
    old = previous()
    if old: return view(old)
    plan, origin, draft, bundle = research_transfer_plan(db, user, settings, payload)
    if not payload.reviewed or payload.review_digest != plan['review_digest']:
        raise HTTPException(409, '文案、来源或PDF版本已变化；请重新预览并明确确认本次承接')
    if plan['source_quality']['limited'] and not payload.limited_sources_reviewed:
        raise HTTPException(422, '参考来源只有摘要或摘录，请先明确确认其不代表已验证的学生问题、热榜或购买需求，再继续图文制作')
    data = flow.initial_data(plan['source'], bundle)
    data.update(copy=deepcopy(plan['copy']), evidence=deepcopy(plan['evidence']), selected_source_ids=plan['selected_source_ids'],
                research_id=origin.id, searches=deepcopy(origin.searches), analysis=research.analyze(plan['evidence'], origin.context))
    data['research_handoff'] = {'research_id': origin.id, 'research_draft_id': draft.id, 'source_draft_id': draft.draft_id,
        'research_directory': origin.context.get('library_directory', ''), 'review_digest': plan['review_digest'],
        'request_signature': signature, 'reviewed_at': shanghai_now().isoformat(),
        'limited_sources_reviewed': bool(plan['source_quality']['limited'] and payload.limited_sources_reviewed),
        'original_reviewed_at': draft.reviewed_at.isoformat() if draft.reviewed_at else None,
        'snapshot': deepcopy({k: v for k, v in plan.items() if k not in {'scope', 'review_digest'}})}
    data['approvals']['copy'] = {'digest': flow.fingerprint(data, 'copy'), 'at': shanghai_now().isoformat(),
        'source': 'manual_research_handoff_review', 'source_quality': deepcopy(plan['source_quality']),
        'limited_sources_reviewed': bool(plan['source_quality']['limited'] and payload.limited_sources_reviewed)}
    trace.record(data, 'research_handoff', 'human_research_handoff',
                 inputs={'research_id': origin.id, 'research_draft_id': draft.id, 'review_digest': plan['review_digest']},
                 outputs={'copy_digest': flow.fingerprint(data, 'copy')},
                 scope='explicitly_reviewed_copy_sources_and_pdf; local_only')
    flow.event(data, 'research_handoff', research_id=origin.id, research_draft_id=draft.id, source_draft_id=draft.draft_id)
    row = CourseVisualWorkflow(user_id=user.id, file_id=payload.file_id, request_key=str(payload.request_key), data=data)
    db.add(row)
    try: commit(db)
    except IntegrityError:
        db.rollback(); old = previous()
        if old: return view(old)
        raise HTTPException(409, '本次承接正在保存，请稍后刷新') from None
    db.refresh(row)
    return view(row)


@router.get('/{run_id}')
def detail(run_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    return view(owned(db, user, run_id))


@router.post('/{run_id}/select-template')
def select_template(run_id: int, payload: SelectTemplate, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    row = owned(db, user, run_id, payload.expected_version)
    if row.data['visual_plan'].get('template_id', 'legacy') == payload.template_id:
        return view(row)
    data = flow.checkpoint(row.data, '选择视觉模板，旧版保留')
    if payload.template_id == 'magazine-a':
        data = flow.magazine_defaults(data)
    else:
        data['visual_plan']['template_id'] = payload.template_id
    data['page_overrides'] = {}
    flow.invalidate(data, 'cover')
    flow.event(data, 'select_template', template_id=payload.template_id, human_review_pending=True)
    row.data = data
    commit(db)
    return view(row)


@router.patch('/{run_id}')
def edit(run_id: int, payload: Edit, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    row = owned(db, user, run_id, payload.expected_version); d = deepcopy(row.data)
    incoming = {k: v for k, v in payload.model_dump(exclude={'expected_version', 'visual_candidate_reviewed'}, exclude_none=True).items() if v != d.get(k)}
    if payload.visual_candidate_reviewed:
        flow.require_approved(d, 'copy')
        if payload.visual_plan is None or payload.set_plan is None or 'copy' in incoming or 'selected_source_ids' in incoming:
            raise HTTPException(422, '核对图片候选时请提供当前完整四图方案，不同时修改已审核文案')
        incoming.update(visual_plan=payload.visual_plan.model_dump(exclude_none=True), set_plan=payload.set_plan.model_dump())
    if not incoming:
        return view(row)
    for plan_name in ['visual_plan', 'set_plan']:
        if plan_name in incoming:
            pages = incoming[plan_name]['sample_pages']
            if len(set(pages)) != len(pages) or any(n < 1 or n > d['source']['page_count'] for n in pages):
                raise HTTPException(422, '请选择当前PDF范围内不重复的样页')
            if plan_name == 'visual_plan' and incoming[plan_name].get('cover_sample_page') is not None and incoming[plan_name]['cover_sample_page'] > d['source']['page_count']:
                raise HTTPException(422, '封面正文样张须选择当前PDF第2页及以后的有效页面')
    if 'selected_source_ids' in incoming:
        valid = {e['id'] for e in d['evidence'] if not e.get('excluded')}
        if not set(incoming['selected_source_ids']) <= valid:
            raise HTTPException(422, '所选来源无效')
    if 'set_plan' in incoming:
        template = incoming.get('visual_plan', d['visual_plan']).get('template_id', 'legacy')
        if template != 'magazine-a' and any(len(item.get('nodes', [])) > 3 for item in incoming['set_plan']['extra_explanations']):
            raise HTTPException(422, '当前模板的补充讲解最多3个节点；A杂志版可保留最多5个')
    if 'collage_plan' in incoming:
        if d.get('pdf_page_plan') and 'pdf_page_plan' not in incoming:
            raise HTTPException(409, '当前已采用独立PDF样页，旧拼图仅保留在历史版本；请修改单页预览选页')
        flow.validate_collage_plan(incoming['collage_plan'], d['source']['page_count'])
    if 'pdf_page_plan' in incoming:
        flow.validate_pdf_page_plan(incoming['pdf_page_plan'], d['source']['page_count'])
    inner_only = bool(incoming) and set(incoming) <= {'set_plan', 'collage_plan', 'pdf_page_plan'}
    old_template = d['visual_plan'].get('template_id', 'legacy')
    d = flow.checkpoint(d, '修改末尾独立PDF样页' if set(incoming) == {'pdf_page_plan'} else '修改末尾PDF拼图方案' if set(incoming) == {'collage_plan'} else '修改整套内页方案' if inner_only else '修改文案或视觉方案'); d.update(incoming)
    if old_template != 'magazine-a' and d['visual_plan'].get('template_id') == 'magazine-a':
        d = flow.magazine_defaults(d)
    if 'pdf_page_plan' in incoming:
        d.pop('collage_plan', None)
    if 'visual_plan' in incoming:
        d['page_overrides'] = {}
    elif 'set_plan' in incoming:
        d['page_overrides'] = {k: v for k, v in d.get('page_overrides', {}).items() if k == 'cover'}
    elif 'collage_plan' in incoming:
        d['page_overrides'] = {k: v for k, v in d.get('page_overrides', {}).items() if not k.startswith('collage-')}
    elif 'pdf_page_plan' in incoming:
        d['page_overrides'] = {k: v for k, v in d.get('page_overrides', {}).items() if not k.startswith(('collage-', 'pdf-page-'))}
    flow.invalidate(d, 'set' if inner_only else 'copy' if set(incoming) & {'copy', 'selected_source_ids'} else 'cover')
    if payload.visual_candidate_reviewed:
        flow.bind_visual_candidate(d, 'explicit_manual_visual_candidate_review')
    trace.record(d, 'content_edit', 'human_workbench_editor', inputs={'fields': list(incoming)}, outputs=incoming,
                 scope='local_versioned_edit; no_generation_or_approval')
    flow.event(d, 'edit', fields=list(incoming)); row.data = d; commit(db)
    return view(row)


@router.post('/{run_id}/select-entry-mode')
def select_entry_mode(run_id: int, payload: EntryMode, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    row = owned(db, user, run_id, payload.expected_version)
    if row.data.get('entry_mode', 'xhs-research') == payload.entry_mode:
        return view(row)
    data = flow.checkpoint(row.data, '明确切换资料分析或小红书研究入口，旧版保留')
    data['entry_mode'] = payload.entry_mode
    if payload.entry_mode == 'pdf-driven':
        data = flow.magazine_defaults(data)
        if not data['copy']['title'].strip():
            data['label'] = f'{data["source"]["course_code"]} · PDF资料选题'
    # Retain all acquired evidence, but do not silently turn local inferences into
    # platform observations or mix them into a new line's selected sources.
    allowed = {item['id'] for item in data['evidence']
               if (item.get('evidence_type') == 'pdf-analysis') == (payload.entry_mode == 'pdf-driven')}
    data['selected_source_ids'] = [key for key in data['selected_source_ids'] if key in allowed]
    flow.invalidate(data, 'copy')
    trace.record(data, 'select_entry_mode', 'human_workbench_editor', inputs={'entry_mode': payload.entry_mode},
                 scope='explicit_local_entry_change; old_versions_retained')
    flow.event(data, 'select_entry_mode', entry_mode=payload.entry_mode)
    row.data = data; commit(db)
    return view(row)


@router.post('/{run_id}/pdf-analysis-plan')
def pdf_analysis_plan(run_id: int, payload: Version, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    row = owned(db, user, run_id, payload.expected_version)
    return pdf_analysis.public_plan(pdf_analysis.prepare(db, user, settings, row))


@router.post('/{run_id}/generate-from-pdf')
def generate_from_pdf(run_id: int, payload: AiGenerate, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library), ai=Depends(get_text_ai_client)):
    row = owned(db, user, run_id)
    key = str(payload.request_key)
    previous = row.data.get('pdf_requests', {}).get(key)
    if previous:
        if previous.get('plan_digest') != payload.plan_digest:
            raise HTTPException(409, '同一PDF分析请求的确认范围不同，请重新准备')
        if previous.get('status') == 'completed' and previous.get('copy_digest') == flow.fingerprint(row.data, 'copy'):
            return view(row)
        raise HTTPException(409, '本次PDF分析请求已执行或正在执行，不会再次调用；请刷新，需重试时重新准备并使用新请求')
    row = owned(db, user, run_id, payload.expected_version)
    prepared = pdf_analysis.prepare(db, user, settings, row)
    if not payload.external_consent or payload.plan_digest != prepared['plan_digest']:
        raise HTTPException(422, '请核对PDF摘录页码、实际外发文字、服务商和模型，再明确同意本次分析')
    model, hint = text_model(db, user)
    if not hint or not hint['configured']:
        raise HTTPException(422, '请先完成默认文本模型配置；尚未发送资料')
    try:
        api_key = decrypt_text(model.encrypted_api_key)
    except Exception:
        raise HTTPException(422, '默认文本模型密钥不可用，请在本机模型配置中重新填写；尚未发送资料') from None
    data = deepcopy(row.data)
    data['operation'] = {'key': key, 'kind': 'pdf-analysis', 'status': 'generating'}
    data.setdefault('pdf_requests', {})[key] = {'status': 'generating', 'plan_digest': payload.plan_digest}
    row.data = data; commit(db)
    claim_version = row.row_version

    def current_claim():
        # End the old read transaction and discard ORM identity-map snapshots.
        # A late response must never overwrite a newer operation or edit.
        db.rollback(); db.expire_all()
        fresh = owned(db, user, run_id)
        operation = fresh.data.get('operation') or {}
        if fresh.row_version != claim_version or operation.get('key') != key or operation.get('status') != 'generating':
            raise HTTPException(409, '分析返回时工作记录已变化；旧稿和当前内容保留，请刷新后核对')
        return fresh

    diagnostic_stage = 'model_request'
    try:
        raw = ai.analyze_course_pdf(model_config=model, api_key=api_key, reference=prepared['prompt'])
        diagnostic_stage = 'response_validation'
        parsed = pdf_analysis.parse_result(raw, prepared, data)
        diagnostic_stage = 'workflow_recheck'
        fresh = current_claim()
        # Reopen the current PDF after the network wait; a retained pre-call FD
        # alone cannot detect a newly indexed revision or a replaced source.
        diagnostic_stage = 'source_recheck'
        file, bank, fd = source_fd(db, user, settings, fresh)
        try:
            unchanged(file, bank, fd)
        finally:
            os.close(fd)
        diagnostic_stage = 'recipient_recheck'
        current_model, current_hint = text_model(db, user)
        if pdf_analysis.model_binding(current_model, current_hint) != prepared['_model_binding']:
            raise HTTPException(409, '分析期间文本模型或服务商配置已变化；未保存返回内容，请重新核对外发范围')
        diagnostic_stage = 'persist_result'
        result = flow.checkpoint(fresh.data, 'PDF提炼痛点、资料事实与新待审核文案；旧稿和旧图保留')
        flow.invalidate(result, 'copy')
        source_id = f'pdf-{result["source"]["revision_id"]}-{result["source"]["sha256"][:16]}'
        evidence = {'id': source_id, 'evidence_type': 'pdf-analysis', 'title': result['source']['filename'],
                    'summary': '同版本PDF教学分析；没有小红书笔记、评论或购买需求验证',
                    'source_url': '', 'comments': [], 'metrics': {},
                    'pdf_revision_id': result['source']['revision_id'], 'pdf_sha256': result['source']['sha256']}
        result['evidence'] = [item for item in result['evidence'] if item.get('id') != source_id] + [evidence]
        result['selected_source_ids'] = [source_id]
        result.update({k: v for k, v in parsed.items() if k != 'source_map'})
        result['source_map'] = parsed['source_map']
        result['copy_editorial'] = {'source_map': [{**entry, 'source_ids': [source_id]} for entry in parsed['source_map']],
            'editor_notes': parsed['pdf_analysis']['editor_notes'], 'goal': parsed['copy']['goal'],
            'prompt_digest': prepared['plan_digest'], 'status': 'pending_review', 'basis': 'pdf-analysis'}
        result['label'] = parsed['copy']['title']
        result['page_overrides'] = {}
        flow.bind_visual_candidate(result, 'pdf_analysis_matching_copy_candidate')
        result['operation']['status'] = 'completed'
        result['pdf_requests'][key].update(status='completed', copy_digest=flow.fingerprint(result, 'copy'))
        trace.record(result, 'pdf_analysis_and_copy', 'configured_text_model', model=hint,
                     inputs={'prompt': prepared['prompt'], 'plan_digest': prepared['plan_digest']},
                     outputs=parsed, scope=prepared['scope'])
        flow.event(result, 'generate_from_pdf', destination=hint['destination'], human_review_pending=True)
        fresh.data = result; commit(db)
        return view(fresh)
    except Exception as exc:
        # Persist failure only while our exact claim still owns this version.
        # Same-key failed retries are rejected before any later billable call.
        try:
            fresh = current_claim()
        except HTTPException:
            raise HTTPException(409, '分析期间工作记录已变化；返回内容未覆盖当前内容，请刷新') from None
        failed = deepcopy(fresh.data)
        failed['operation']['status'] = 'failed'
        failed['pdf_requests'][key]['status'] = 'failed'
        diagnostic = pdf_analysis.safe_failure_diagnostic(exc, diagnostic_stage)
        failed['operation']['diagnostic'] = diagnostic
        failed['pdf_requests'][key]['diagnostic'] = diagnostic
        trace.record(failed, 'pdf_analysis_and_copy', 'configured_text_model', model=hint,
                     inputs={'plan_digest': prepared['plan_digest']}, status='failed', scope=prepared['scope'])
        fresh.data = failed; commit(db)
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(502, 'PDF分析未返回完整且有真实引用的可审核结构；旧文案和旧图保留。'
                            f'本机诊断：{diagnostic["code"]}（{diagnostic["stage"]}）。可本机编辑，或重新准备范围后重试。') from None


def ensure_research(db, user, row):
    r = db.get(CourseResearch, row.data.get('research_id')) if row.data.get('research_id') else None
    if r is None:
        s = row.data['source']; r = CourseResearch(user_id=user.id, context={**s, 'library_directory': str(Path(s['relative_path']).parent), 'course_directory': str(Path(s['relative_path']).parent.parent)}, evidence=[], searches=[])
        db.add(r); db.flush()
    if r.user_id != user.id:
        raise HTTPException(404, '研究记录不存在')
    return r


@router.post('/{run_id}/search')
def search(run_id: int, payload: Search, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library), adapter=Depends(pc.get_xhs_pc_api_adapter_factory)):
    row = owned(db, user, run_id, payload.expected_version)
    if row.data.get('entry_mode', 'xhs-research') != 'xhs-research':
        raise HTTPException(422, '请先明确切换到“小红书话题研究”入口，再搜索笔记与评论')
    r = ensure_research(db, user, row)
    result = research.search(r.id, research.Search(source='xhs', keyword=payload.keyword, account_id=payload.account_id, sort=payload.sort), user, db, settings, adapter)
    d = flow.checkpoint(row.data, '重新搜索课程笔记'); flow.invalidate(d, 'copy')
    d.update(research_id=r.id, evidence=flow.public_evidence(result['evidence']), searches=result['searches'], selected_source_ids=[], analysis=result['analysis'])
    trace.record(d, 'research_search', 'spider_xhs_search', inputs={'keyword': payload.keyword, 'sort': payload.sort},
                 outputs={'evidence': d['evidence'], 'searches': d['searches']}, scope='course_keyword_search; retain_public_source_links')
    flow.event(d, 'spider_search', keyword=payload.keyword); row.data = d; commit(db)
    return view(row)


@router.post('/{run_id}/read')
def read(run_id: int, payload: Read, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library), adapter=Depends(pc.get_xhs_pc_api_adapter_factory)):
    row = owned(db, user, run_id, payload.expected_version)
    if row.data.get('entry_mode', 'xhs-research') != 'xhs-research':
        raise HTTPException(422, '请先明确切换到“小红书话题研究”入口，再读取笔记与评论')
    if not row.data.get('research_id'):
        raise HTTPException(422, '请先在本工作记录中搜索，再读取结果')
    result = research.read_source(row.data['research_id'], payload.source_id, research.ReadSource(account_id=payload.account_id), user, db, settings, adapter)
    d = flow.checkpoint(row.data, '读取正文和评论'); flow.invalidate(d, 'copy')
    d.update(evidence=flow.public_evidence(result['evidence']), searches=result['searches'], analysis=result['analysis'])
    trace.record(d, 'research_read', 'spider_xhs_note_comments', inputs={'source_id': payload.source_id},
                 outputs={'evidence': d['evidence']}, scope='read_public_note_and_comments; unknown_data_remains_unknown')
    flow.event(d, 'read_source', source_id=payload.source_id); row.data = d; commit(db)
    return view(row)


def prepare(db, user, settings, row, purpose='copy'):
    from backend.app.services.course_content_editorial import copy_goal, quality_hints
    samples = row.data['visual_plan']['sample_pages'][:2]
    # An untouched legacy plan contains only the PDF cover. Give visual planning
    # actual reading material without making the user pre-plan the plan itself.
    # The exact pages/scope remain visible in the consent prompt before any AI call.
    if purpose == 'visual' and samples == [1]:
        samples = list(range(2, min(row.data['source']['page_count'], 3) + 1)) or [1]
    if purpose == 'visual' and row.data['visual_plan'].get('cover_sample_page') is not None:
        samples = list(dict.fromkeys([row.data['visual_plan']['cover_sample_page'], *samples]))
    material = build_plan(db, user, settings, row.file_id, PlanRequest(revision_id=row.data['source']['revision_id'], pages=list(dict.fromkeys([1, *samples]))))
    facts = {'filename': material['source']['filename'], 'page_count': material['source']['page_count'], 'pages': material['pages']}
    prompt = flow.visual_prompt(row.data, facts) if purpose == 'visual' else flow.writing_prompt(row.data, facts)
    configured_model, model = text_model(db, user)
    selected = [e for e in row.data['evidence'] if e['id'] in row.data['selected_source_ids'] and not e.get('excluded')]
    result = {'prompt': prompt, 'model': model, 'purpose': purpose, 'scope': ('XHS Visual Director编排规范、品牌文字与配色、已确认文案、已选模板和密度、当前视觉方案；PDF物理页 ' + '、'.join(str(p['page']) for p in material['pages']) + ' 的提取文字（尚未选正文样页时先读取前两张正文页）；' if purpose == 'visual' else 'aussie-course-xhs写作规范、已选编辑目标、品牌与课程信息、研究标题/摘要及每条至多8条评论摘录、PDF封面与前两张所选样页的提取文字；') + '不发送完整PDF、图片、Logo原图、绝对路径、Cookie或密钥。', 'allowed_pages': [p['page'] for p in material['pages']],
              'editorial_goal': copy_goal(row.data['copy'].get('goal')),
              'quality_review': quality_hints(row.data['copy'], row.data['brand']['name'], selected, row.data['visual_plan'])}
    result['plan_digest'] = flow.digest({'plan': result, 'model_binding': pdf_analysis.model_binding(configured_model, model)})
    return result


@router.post('/{run_id}/prompts')
def prompts(run_id: int, purpose: Literal['copy','visual'] = 'copy', user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    row = owned(db, user, run_id)
    return {**prepare(db, user, settings, row, purpose), 'visual_direction': flow.direct(row.data), 'rules': row.data['rules']}


class DesignReport(Strict):
    content_type: str = Field(max_length=240)
    goal: str = Field(max_length=240)
    emotion: str = Field(max_length=240)
    density: str = Field(max_length=240)
    primary_style: str = Field(max_length=240)
    supporting_style: str = Field(max_length=240)
    avoid: str = Field(max_length=240)
    reason: str = Field(max_length=240)


class DesignResult(Strict):
    style_report: DesignReport
    visual_plan: VisualPlan
    set_plan: SetPlan | None = None


def visual_intent(data):
    # Images, operation status and review clicks may change after planning. They
    # must not turn a lost response into another billable planning request.
    return flow.digest({key: data.get(key) for key in (
        'source', 'copy', 'brand', 'rules', 'selected_source_ids', 'evidence',
        'visual_plan', 'set_plan', 'pdf_page_plan', 'page_overrides')})


@router.post('/{run_id}/generate-visual-plan')
def generate_visual_plan(run_id: int, payload: AiGenerate, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library), ai=Depends(get_text_ai_client)):
    row = owned(db,user,run_id)
    key = str(payload.request_key)
    previous = row.data.get('visual_plan_requests', {}).get(key)
    if previous:
        if previous.get('plan_digest') != payload.plan_digest or not payload.external_consent:
            raise HTTPException(409, '该图片规划请求的确认范围不同，请重新准备')
        if previous.get('status') == 'completed' and previous.get('result_digest') == visual_intent(row.data):
            return view(row)
        raise HTTPException(409, '本次图片规划已执行或正在执行，不会重复调用；请刷新核对，需新规划时重新准备')
    row = owned(db,user,run_id,payload.expected_version);flow.require_approved(row.data,'copy')
    prepared = prepare(db,user,settings,row,'visual')
    if not payload.external_consent or payload.plan_digest!=prepared['plan_digest']: raise HTTPException(422,'先核对Skill视觉策划提示词、接收方和外发范围，再明确同意')
    model,hint=text_model(db,user)
    if not hint or not hint['configured']: raise HTTPException(422,'请先完成默认文本模型配置')
    binding = pdf_analysis.model_binding(model, hint)
    try:
        api_key = decrypt_text(model.encrypted_api_key)
    except Exception:
        raise HTTPException(422, '默认文本模型密钥不可用，请在本机重新填写；尚未发送资料') from None
    d=deepcopy(row.data)
    d['operation']={'key':key,'kind':'visual-planning','status':'generating'}
    d.setdefault('visual_plan_requests', {})[key] = {'status':'generating', 'plan_digest':payload.plan_digest}
    row.data=d;commit(db)
    claim_version = row.row_version

    def current_claim():
        db.rollback(); db.expire_all()
        fresh = owned(db, user, run_id)
        operation = fresh.data.get('operation') or {}
        if fresh.row_version != claim_version or operation.get('key') != key or operation.get('status') != 'generating':
            raise HTTPException(409, '图片规划期间工作记录已变化；返回内容未覆盖当前文案或图片，请刷新')
        return fresh

    diagnostic_stage = 'model_request'
    try:
        raw=ai.plan_visuals(model_config=model,api_key=api_key,reference=prepared['prompt'])
        diagnostic_stage = 'response_validation'
        if isinstance(raw,str):
            raw=re.sub(r'^```(?:json)?\s*|\s*```$','',raw.strip())
            raw=json.loads(raw)
        parsed=DesignResult.model_validate(raw)
        if any(getattr(parsed.visual_plan, field) != (d['visual_plan'].get(field) or default)
               for field, default in [('template_id', 'legacy'), ('density', 'standard')]):
            raise ValueError('视觉模型擅自改变已选择的模板或密度')
        pages=parsed.visual_plan.sample_pages
        if len(set(pages))!=len(pages) or not set(pages)<=set(prepared['allowed_pages']): raise ValueError('AI所选样页未提供')
        chosen = d['visual_plan'].get('cover_sample_page')
        if parsed.visual_plan.cover_sample_page not in (None, chosen):
            raise ValueError('视觉模型擅自改变已选择的封面正文样张')
        if chosen is not None:
            parsed.visual_plan.cover_sample_page = chosen
        if parsed.visual_plan.template_id == 'magazine-a':
            if parsed.set_plan is None or len(parsed.set_plan.extra_explanations) != 2:
                raise ValueError('A版视觉策划必须包含两张不同的补充干货')
            if not set(parsed.set_plan.sample_pages) <= set(prepared['allowed_pages']):
                raise ValueError('A版样页定位未提供')
        elif parsed.set_plan is not None:
            raise ValueError('旧模板不接受未请求的整套方案覆盖')
        diagnostic_stage = 'workflow_recheck'
        fresh = current_claim()
        diagnostic_stage = 'source_recheck'
        file, bank, fd = source_fd(db, user, settings, fresh)
        try:
            unchanged(file, bank, fd)
        finally:
            os.close(fd)
        diagnostic_stage = 'recipient_recheck'
        current_model, current_hint = text_model(db, user)
        if pdf_analysis.model_binding(current_model, current_hint) != binding:
            raise HTTPException(409, '规划期间文本模型配置已变化，未保存返回方案；请重新核对接收方')
        diagnostic_stage = 'persist_result'
        d=flow.checkpoint(fresh.data,'按XHS Visual Director生成新视觉方案');flow.invalidate(d,'cover')
        d['visual_plan']=parsed.visual_plan.model_dump(exclude_none=True);d['design_report']=parsed.style_report.model_dump();d['page_overrides']={}
        if parsed.set_plan is not None:
            d['set_plan'] = parsed.set_plan.model_dump()
        flow.require_magazine_content(d)
        flow.bind_visual_candidate(d, 'explicit_ai_visual_replanning')
        d['operation']['status']='completed'
        d['visual_plan_requests'][key].update(status='completed', result_digest=visual_intent(d))
        trace.record(d, 'visual_planning', 'configured_text_model', model=hint, inputs={'prompt': prepared['prompt']},
                     outputs={'visual_plan': d['visual_plan'], 'design_report': d['design_report']}, scope=prepared['scope'])
        flow.event(d,'generate_visual_plan',destination=hint['destination']);fresh.data=d;commit(db)
        return view(fresh)
    except Exception as exc:
        fresh = current_claim()
        failed = deepcopy(fresh.data)
        failed['operation']['status']='failed'
        failed['visual_plan_requests'][key]['status'] = 'failed'
        diagnostic = pdf_analysis.safe_failure_diagnostic(exc, diagnostic_stage)
        failed['operation']['diagnostic'] = diagnostic
        failed['visual_plan_requests'][key]['diagnostic'] = diagnostic
        trace.record(failed, 'visual_planning', 'configured_text_model', model=hint, inputs={'prompt': prepared['prompt']},
                     status='failed', scope=prepared['scope'])
        fresh.data=failed;commit(db)
        if isinstance(exc, HTTPException) and exc.status_code == 409:
            raise exc
        reason = (f"文本服务返回 HTTP {diagnostic['http_status']}" if 'http_status' in diagnostic else
                  '连接文本服务超时' if diagnostic['category'] == 'network-timeout' else
                  '未能连接文本服务' if diagnostic['category'] == 'network-connection' else
                  '文本服务返回的图片方案未通过结构校验' if diagnostic['category'].startswith('response-') else
                  '图片内容规划未完成')
        raise HTTPException(502,reason+'；旧文案和旧图保留，未自动重试。已保存脱敏诊断，请核对原因后再决定是否重新调用') from None


class CourseCopySource(Strict):
    claim: str = Field(min_length=1, max_length=600)
    source_ids: list[str] = Field(default_factory=list, max_length=8)
    pdf_pages: list[int] = Field(default_factory=list, max_length=8)


class CourseCopyResult(Strict):
    goal: Literal['student-question', 'method-save', 'sample-trial'] | None = None
    topic: str = Field(min_length=1, max_length=240)
    title: str = Field(min_length=1, max_length=20)
    body: str = Field(min_length=1, max_length=1000)
    tags: list[str] = Field(min_length=1, max_length=8)
    takeaway: str = Field(min_length=1, max_length=240)
    source_map: list[CourseCopySource] = Field(default_factory=list, max_length=16)
    editor_notes: list[str] = Field(default_factory=list, max_length=8)


@router.post('/{run_id}/generate-copy')
def generate_copy(run_id: int, payload: AiGenerate, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library), ai=Depends(get_text_ai_client)):
    from backend.app.services.course_content_editorial import copy_goal
    from backend.app.services.course_research_service import split_editor_notes
    row = owned(db, user, run_id)
    if row.data.get('entry_mode', 'xhs-research') == 'pdf-driven':
        raise HTTPException(422, '当前是PDF资料入口，请先准备PDF分析范围，再生成对应待审核文案')
    if (row.data.get('operation') or {}).get('key') == str(payload.request_key):
        return view(row)
    row = owned(db, user, run_id, payload.expected_version); plan = prepare(db, user, settings, row)
    if not payload.external_consent or payload.plan_digest != plan['plan_digest']:
        raise HTTPException(422, '先检查当前服务商及外发范围，明确同意后生成')
    model, hint = text_model(db, user)
    if not hint or not hint['configured']:
        raise HTTPException(422, '请先完成默认文本模型配置')
    d = deepcopy(row.data); d['operation'] = {'key': str(payload.request_key), 'status': 'generating'}; row.data = d; commit(db)
    try:
        generated = ai.generate_course_copy(model_config=model, api_key=decrypt_text(model.encrypted_api_key), reference=plan['prompt'])
        if isinstance(generated, str):
            generated = json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', generated.strip()))
        parsed = CourseCopyResult.model_validate(generated)
        goal = copy_goal(d['copy'].get('goal'))
        if parsed.goal is not None and parsed.goal != goal:
            raise ValueError('AI changed the selected editorial goal')
        for value in [parsed.topic, parsed.title, parsed.body, parsed.takeaway, *parsed.tags]:
            if not value.strip():
                raise ValueError('Empty course-copy field')
        if any(len(tag) > 40 for tag in parsed.tags) or any(len(note) > 1000 for note in parsed.editor_notes):
            raise ValueError('Course-copy metadata is too long')
        if split_editor_notes(parsed.body)[1]:
            raise ValueError('Internal editor notes must not enter the body')
        for mapping in parsed.source_map:
            if not set(mapping.source_ids) <= set(d['selected_source_ids']) or not set(mapping.pdf_pages) <= set(plan['allowed_pages']):
                raise ValueError('Unknown course-copy evidence reference')
    except Exception:
        d['operation']['status'] = 'failed'
        trace.record(d, 'copy_generation', 'configured_text_model', model=hint, inputs={'prompt': plan['prompt']},
                     status='failed', scope=plan['scope'])
        row.data = d; commit(db)
        raise HTTPException(502, '文案未返回完整可审核结构，或引用了未提供的依据；旧文案和旧图已保留，可重新准备后重试。') from None
    d = flow.checkpoint(d, 'AI生成新的待审核文案'); flow.invalidate(d, 'copy')
    d['copy'] = {key: getattr(parsed, key) for key in ['topic', 'title', 'body', 'tags', 'takeaway']} | {'goal': goal}
    d['copy_editorial'] = {'source_map': [entry.model_dump() for entry in parsed.source_map], 'editor_notes': parsed.editor_notes,
                         'goal': goal, 'prompt_digest': plan['plan_digest'], 'status': 'pending_review'}
    d['operation']['status'] = 'completed'
    trace.record(d, 'copy_generation', 'configured_text_model', model=hint, inputs={'prompt': plan['prompt']},
                 outputs={'copy': d['copy'], 'editorial': d['copy_editorial']}, scope=plan['scope'])
    flow.event(d, 'generate_copy', destination=hint['destination']); row.data = d; commit(db)
    return view(row)


def render_assets(db, user, settings, row, stage, revise=None, render_data=None):
    data = render_data if render_data is not None else row.data
    flow.require_visual_candidate_current(data)
    flow.require_content_sample(data)
    flow.require_magazine_content(data)
    if stage == 'set':
        flow.require_teaching_content(data)
    if data.get('pdf_page_plan'):
        flow.validate_pdf_page_plan(data['pdf_page_plan'], data['source']['page_count'])
    elif data.get('collage_plan'):
        flow.validate_collage_plan(data['collage_plan'], data['source']['page_count'])
    file, bank, fd = source_fd(db, user, settings, row)
    root = directory(settings, user, row); generation = uuid4().hex; out = root / generation; out.mkdir(parents=True)
    try:
        backgrounds = {slot: str(background.local_path(root, entry)) for slot, entry in data.get('backgrounds', {}).items()}
    except Exception:
        os.close(fd)
        raise
    spec = {'data': data, 'catalog': flow.catalog(), 'revise': revise, 'backgrounds': backgrounds}
    config = out / 'direction.json'; config.write_text(json.dumps(spec, ensure_ascii=False))
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        done = subprocess.run([sys.executable, '-m', 'backend.app.services.course_visual_svg', str(fd), str(config), str(out), stage], pass_fds=(fd,), capture_output=True, text=True, timeout=90)
        try: result = json.loads(done.stdout)
        except ValueError: result = {'error': '本地排版未完成，旧图保留'}
        if done.returncode or result.get('error'):
            raise HTTPException(422, result.get('error', '图片制作未完成'))
        unchanged(file, bank, fd)
    except subprocess.TimeoutExpired:
        raise HTTPException(422, '图片制作超时，旧图和原件保留')
    finally:
        os.close(fd)
    assets = []
    from PIL import Image
    for a in result['files']:
        path = out / a['file']
        size = Image.open(path).size if path.parent == out and path.is_file() and not path.is_symlink() else (0, 0)
        raw = data['visual_plan'].get('template_id') == 'magazine-a' and a.get('kind') == 'pdf-page'
        if raw:
            import pypdfium2 as pdfium
            page_number = a.get('source_page')
            if not isinstance(page_number, int) or page_number not in data.get('pdf_page_plan', {}).get('pages', []):
                raise HTTPException(422, '真实PDF样页与当前计划不一致，旧图保留')
            _, _, check_fd = source_fd(db, user, settings, row)
            try:
                with os.fdopen(os.dup(check_fd), 'rb') as stream:
                    document = pdfium.PdfDocument(stream)
                    page = document[page_number - 1]
                    ratio = page.get_width() / page.get_height()
                    page.close(); document.close()
            finally:
                os.close(check_fd)
            if a.get('preview_layout') == PREVIEW_LAYOUT:
                valid_size = (size[0] == PREVIEW_WIDTH and 0 < size[1] - HEADER_HEIGHT <= 12000
                              and abs(size[1] - HEADER_HEIGHT - PREVIEW_WIDTH / ratio) <= 2
                              and a.get('preview_brand') == preview_brand(data['brand']['id']))
            else:
                valid_size = (0 < size[0] <= 6000 and 0 < size[1] <= 10000 and abs(size[0] / size[1] - ratio) < 0.003)
        else:
            valid_size = size == (1080, 1440)
        if path.parent != out or not valid_size:
            raise HTTPException(422, '图片尺寸或来源异常，未替换旧图')
        assets.append({**a, 'id': uuid4().hex, 'path': f'{generation}/{a["file"]}', 'sha256': flow.hash_file(path), 'brief': a.get('brief', {}), 'width': size[0], 'height': size[1],
                       **({'background': deepcopy(data['backgrounds'][a['slot']])} if a['slot'] in data.get('backgrounds', {}) else {})})
    return assets, result.get('direction', {}), result.get('display_treatment', '')


@router.post('/{run_id}/api-image-plan')
def api_image_plan(run_id: int, payload: ApiImagePlan, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    row = owned(db, user, run_id, payload.expected_version)
    file, bank, fd = source_fd(db, user, settings, row); os.close(fd)
    return api_images.prepare(db, user, row, directory(settings, user, row), payload.target)


@router.post('/{run_id}/generate-api-images')
def generate_api_images(run_id: int, payload: ApiImageGenerate, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library), client=Depends(api_images.get_image_client)):
    """User-triggered paid production, atomic activation; never review/export/publish."""
    row = owned(db, user, run_id); key = str(payload.request_key)
    signature = flow.digest(payload.model_dump(exclude={'expected_version', 'request_key'}))
    previous = row.data.get('api_image_requests', {}).get(key)
    if previous:
        if previous['signature'] != signature:
            raise HTTPException(409, '同一API生图请求的确认范围已变化，请重新核对')
        if previous['status'] == 'completed' and previous.get('result_digest') == flow.fingerprint(row.data, 'set'):
            return view(row)
        raise HTTPException(409, '本次API请求已处理或正在处理，不会再次调用；请刷新核对。未完成的原图可在重新准备时复用')
    row = owned(db, user, run_id, payload.expected_version)
    root = directory(settings, user, row)
    plan = api_images.prepare(db, user, row, root, payload.target)
    if not payload.external_consent or payload.plan_digest != plan['plan_digest']:
        raise HTTPException(422, '请先核对逐张提示词、服务商、外发范围及调用张数，再明确同意')
    model, hint = background.model_context(db, user)
    if not background.supported(model) or not hint or not hint['configured']:
        raise HTTPException(422, '请在模型配置中设置火山方舟北京区Seedream 5.0 Flash / Pro及API Key')
    credential_revision = flow.digest(model.encrypted_api_key)
    file, bank, fd = source_fd(db, user, settings, row); os.close(fd)
    original = deepcopy(row.data)
    pages = [p for p in flow.direct(original)['pages'] if p['slot'] in {p['slot'] for p in plan['pages']}]
    cached = deepcopy(original.get('api_image_requests', {}).get(plan['reuse_key'], {}).get('raws', {})) if plan['reuse_key'] else {}
    request = {'status': 'generating', 'signature': signature, 'target': payload.target,
               'input_digest': plan['input_digest'], 'content_digest': plan['content_digest'],
               'consent_digest': plan['plan_digest'], 'model': hint, 'raws': cached, 'assets': [],
               'expected_version': payload.expected_version, 'at': shanghai_now().isoformat()}
    state = deepcopy(original)
    state['api_image_requests'] = {**state.get('api_image_requests', {}), key: request}
    state['operation'] = {'key': key, 'kind': 'api_images', 'status': 'generating',
                          'completed': 0, 'total': len(pages), 'started_at': request['at']}
    row.data = state; commit(db); reserved_version = row.row_version
    out = root / uuid4().hex; out.mkdir(parents=True)

    def current():
        db.refresh(row)
        if (row.row_version != reserved_version or row.data.get('operation', {}).get('key') != key
                or row.data['operation'].get('status') != 'generating'
                or flow.fingerprint(row.data, 'set') != plan['input_digest']):
            raise HTTPException(409, '生成期间工作记录已变化，已返回原图和旧稿保留；未覆盖新修改')
        file, bank, fd = source_fd(db, user, settings, row); os.close(fd)

    def save_progress(**values):
        nonlocal reserved_version
        current()
        state = deepcopy(row.data)
        state['api_image_requests'][key].update(**values)
        state['operation']['completed'] = len(state['api_image_requests'][key].get('assets', []))
        row.data = state; commit(db); reserved_version = row.row_version

    try:
        # Finish/validate the unbilled PDF work before any paid request.
        pdf_assets = []
        if payload.target == 'bundle':
            if flow.complete_set(original):
                pdf_assets = [a for a in original['images'] if a['kind'] == 'pdf-page']
                for asset in pdf_assets:
                    asset_path(settings, user, row, asset)
            else:
                pdf_assets = render_assets(db, user, settings, row, 'pdf-pages')[0]
        assets = []
        for page, prompt in zip(pages, plan['pages']):
            current()
            provider = cached.get(page['slot'])
            if provider is None:
                db.refresh(model)
                _, current_hint = background.model_context(db, user)
                if current_hint != hint or flow.digest(model.encrypted_api_key) != credential_revision:
                    raise HTTPException(409, '图片模型配置在生成期间变化；已返回原图保留，请重新准备剩余范围')
                # Save exact outbound text before the sole attempt; never retry a timed-out POST.
                (out / f'{page["slot"]}-prompt.txt').write_text(prompt['prompt'])
                raw = client.generate(model=model, api_key=decrypt_text(model.encrypted_api_key), prompt=prompt['prompt'])
                provider = api_images.save_provider(raw, out, page['slot'])
                cached[page['slot']] = provider
                save_progress(raws=deepcopy(cached))
            asset = api_images.compose(root, out, provider, page, original, hint, flow.digest(prompt['prompt']))
            assets.append(asset)
            save_progress(assets=deepcopy(assets))
        current()
        cover = next((a for a in assets if a['slot'] == 'cover'), original.get('cover'))
        if payload.target == 'bundle':
            images = [*assets, *pdf_assets]
        elif flow.complete_set(original):
            images = [next((a for a in assets if a['slot'] == old['slot']), old) for old in original['images']]
        else:
            images = []  # First-cover trial; no pretend complete set.
        candidate = {**original, 'cover': cover, 'images': images}
        if images and not flow.complete_set(candidate):
            raise HTTPException(422, 'API整套图与当前内容方案不一致，未替换旧图')
        updated = flow.checkpoint(original, 'API制作完整知识图；原图、旧稿与真实PDF保留')
        updated['api_image_requests'] = deepcopy(row.data['api_image_requests'])
        updated['operation'] = deepcopy(row.data['operation'])
        flow.invalidate(updated, 'cover')
        updated.update(cover=cover, images=images)
        if images:
            flow.mark_bundle(updated, key)
        updated['api_image_requests'][key].update(status='completed', result_digest=flow.fingerprint(updated, 'set'))
        updated['operation']['status'] = 'completed'
        trace.record(updated, 'visual_production', 'seedream_full_page_with_local_identity', model=hint,
                     inputs={'plan_digest': plan['plan_digest'], 'source_sha256': original['source']['sha256']},
                     outputs={'assets': [{'id': a['id'], 'sha256': a['sha256']} for a in assets]},
                     scope=api_images.SCOPE)
        flow.event(updated, 'generate_api_images', target=payload.target, new_api_calls=plan['count'],
                   reused_provider_images=plan['reused_count'], human_review_pending=True)
        row.data = updated; commit(db)
    except Exception as exc:
        db.rollback(); db.refresh(row)
        failed = deepcopy(row.data)
        if failed.get('operation', {}).get('key') == key and failed['operation'].get('status') == 'generating':
            failed['operation']['status'] = 'failed'
            failed['api_image_requests'][key]['status'] = 'failed'
            row.data = failed; commit(db)
        if isinstance(exc, HTTPException):
            raise
        message = (str(exc) if isinstance(exc, ValueError) and str(exc).startswith(('图片接口', '返回图片', '本机大学'))
                   else 'API图文制作未完成；旧稿与已返回原图保留，未自动重试。重新准备会复用已保存原图，只确认尚缺的调用')
        raise HTTPException(502, message) from None
    return view(row)


@router.post('/{run_id}/background-plan')
def background_plan(run_id: int, payload: BackgroundPlan, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    row = owned(db, user, run_id, payload.expected_version)
    if row.data['visual_plan'].get('template_id') == 'magazine-a':
        raise HTTPException(422, 'A版采用已确认白底母版，不需要生成背景；未调用图片模型')
    return background.prepare(db, user, row, payload.slot, payload.style, payload.strength)


@router.post('/{run_id}/generate-background')
def generate_background(run_id: int, payload: BackgroundGenerate, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library), client=Depends(background.get_background_client)):
    row = owned(db, user, run_id); key = str(payload.request_key)
    if row.data['visual_plan'].get('template_id') == 'magazine-a':
        raise HTTPException(422, 'A版采用已确认白底母版，不需要生成背景；未调用图片模型')
    signature = flow.digest(payload.model_dump(exclude={'expected_version', 'request_key', 'local_only'}))
    previous = row.data.get('background_requests', {}).get(key)
    if payload.local_only and not previous:
        raise HTTPException(409, '已保存的背景请求不存在；本机恢复不会调用图片模型')
    if previous:
        if previous['signature'] != signature: raise HTTPException(409, '同一生图请求对应的参数已改变，请重新核对')
        if previous['status'] == 'completed': return view(row)
        if previous['status'] in {'generating', 'rendering'} or row.data.get('operation', {}).get('status') == 'generating':
            raise HTTPException(409, '当前内容仍在生成或合成，请稍后刷新；不会重复调用')
        if not previous.get('asset'): raise HTTPException(409, '上次请求未完成，未重复计费调用；请重新准备提示词后手动重试')
        if previous['input_digest'] != flow.fingerprint(row.data, 'set'): raise HTTPException(409, '生成背景后当前内容已变化，请先核对最新版本')
        entry = previous['asset']
        background.local_path(directory(settings,user,row), entry)
        d=deepcopy(row.data);d['background_requests'][key]['status']='rendering'
        d['operation']={'key':key,'status':'generating','kind':'background','started_at':shanghai_now().isoformat()}
        row.data=d;commit(db)
    else:
        row = owned(db, user, run_id, payload.expected_version)
        prepared = background.prepare(db, user, row, payload.slot, payload.style, payload.strength)
        if not payload.external_consent or payload.plan_digest != prepared['plan_digest']:
            raise HTTPException(422, '先核对背景提示词、接收方和外发范围，再同意生成一张背景')
        model, hint = background.model_context(db, user)
        if not background.supported(model): raise HTTPException(422, '此入口支持火山方舟北京区 Seedream 5.0 Flash / Pro，请检查默认图片模型')
        if not hint['configured']: raise HTTPException(422, '请先在模型配置中保存图片API Key')
        file, bank, fd = source_fd(db,user,settings,row); os.close(fd)
        d = deepcopy(row.data)
        request = {'signature': signature, 'status': 'generating', 'slot': payload.slot, 'input_digest': prepared['input_digest'], 'at': shanghai_now().isoformat(),
                   'consent_digest': payload.plan_digest, 'options': {'slot': payload.slot, 'style': payload.style, 'strength': payload.strength}}
        d['background_requests'] = {**d.get('background_requests', {}), key: request}
        d['operation'] = {'key': key, 'status': 'generating', 'kind': 'background', 'started_at': request['at']}
        row.data = d; commit(db)
        try:
            raw = client.generate(model=model, api_key=decrypt_text(model.encrypted_api_key), prompt=prepared['prompt'])
            root = directory(settings,user,row); generation = uuid4().hex; out = root/generation; out.mkdir(parents=True)
            # Keep provider bytes and prompt for provenance; never replace old backgrounds.
            from PIL import Image
            from io import BytesIO
            with Image.open(BytesIO(raw)) as image:
                if image.width*image.height>5_000_000 or min(image.size)<700 or abs(image.width/image.height-.75)>.025:
                    raise ValueError('返回图片尺寸不符合3:4背景要求')
                image.load(); original_size = image.size
                (out/'provider-original.bin').write_bytes(raw)
                image.convert('RGB').save(out/'background.png')
            entry = {'path': f'{generation}/background.png', 'sha256': flow.hash_file(out/'background.png'), 'width': original_size[0], 'height': original_size[1],
                     'prompt': prepared['prompt'], 'style': payload.style, 'strength': payload.strength, 'model': hint, 'scope': background.SCOPE,
                     'request_key': key, 'created_at': shanghai_now().isoformat(), 'ai_generated': True}
            (out/'provenance.json').write_text(json.dumps(entry,ensure_ascii=False,indent=2))
            d = deepcopy(row.data); d['background_requests'][key].update(status='rendering',asset=entry); row.data=d;commit(db)
        except Exception as exc:
            d=deepcopy(row.data);d['background_requests'][key]['status']='failed';d['operation']['status']='failed';row.data=d;commit(db)
            # Never forward arbitrary provider bodies or credential-bearing exceptions.
            message = str(exc) if isinstance(exc, ValueError) and str(exc).startswith(('图片接口', '返回图片')) else '背景生成未完成，旧图保留；未自动重试'
            raise HTTPException(502, message) from None
    try:
        d=deepcopy(row.data); d['backgrounds']={**d.get('backgrounds',{}),payload.slot:entry}
        combined=flow.bundle_ready(row.data)
        asset=next((a for a in ([d['cover']] if d.get('cover') else [])+d['images'] if a['slot']==payload.slot),None)
        stage='cover' if payload.slot=='cover' else 'revise'
        assets,direction,treatment=render_assets(db,user,settings,row,stage,{'asset':asset,'brief':asset['brief']} if stage=='revise' else None,render_data=d)
        updated=flow.checkpoint(row.data,'AI背景与真实资料本机合成');flow.invalidate(updated,'cover' if stage=='cover' else 'set')
        updated['backgrounds']=d['backgrounds']
        if stage=='cover':
            updated['cover']=assets[0]
            if combined:updated['images']=[assets[0],*d['images'][1:]]
        else:updated['images']=[assets[0] if a['id']==asset['id'] else a for a in d['images']]
        updated['direction']=direction;updated['display_treatment']=treatment
        if combined:flow.mark_bundle(updated)
        updated['background_requests'][key]['status']='completed';updated['operation']['status']='completed'
        flow.event(updated,'generate_background',slot=payload.slot,model=entry['model']['model_name'],external_course_assets_sent=False)
        row.data=updated;commit(db)
    except Exception:
        db.rollback();db.refresh(row)
        d=deepcopy(row.data);d['background_requests'][key]['status']='render_failed'
        if d.get('operation',{}).get('key')==key:d['operation']['status']='failed'
        row.data=d;commit(db)
        raise HTTPException(422,'背景已保存，但本机合成未完成；旧图保留。用同一请求重试只进行本机合成，不再调用生图接口') from None
    return view(row)


@router.post('/{run_id}/render')
def render(run_id: int, payload: Generate, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    row = owned(db, user, run_id, payload.expected_version)
    flow.require_approved(row.data, 'copy' if payload.stage == 'cover' else 'cover')
    assets, direction, treatment = render_assets(db, user, settings, row, payload.stage)
    d = flow.checkpoint(row.data, '生成封面' if payload.stage == 'cover' else '生成整套图')
    flow.invalidate(d, payload.stage)
    if payload.stage == 'cover': d['cover'] = assets[0]
    else: d['images'] = [d['cover'], *assets]
    d['direction'] = direction; d['display_treatment'] = treatment
    trace.record(d, 'image_' + payload.stage, 'local_svg_pdf_renderer', inputs={'direction': direction},
                 outputs={'assets': assets}, scope='local_only; real_pdf_logo_and_text; no_approval_or_export')
    flow.event(d, 'render_' + payload.stage); row.data = d; commit(db)
    return view(row)


@router.post('/{run_id}/render-bundle')
def render_bundle(run_id: int, payload: GenerateBundle, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    """Produce a complete pending set without inventing an intermediate approval."""
    from backend.app.services.course_visual_trace import record
    row = owned(db, user, run_id); key = str(payload.request_key)
    previous = row.data.get('bundle_requests', {}).get(key)
    if previous:
        if previous['status'] == 'completed' and previous.get('result_digest') == flow.fingerprint(row.data, 'set'):
            return view(row)
        if previous['expected_version'] != payload.expected_version:
            raise HTTPException(409, '同一制作请求对应的版本已改变，请刷新后重新制作')
        raise HTTPException(409, '这次制作请求已处理或内容已变化；请刷新后重新制作，旧图仍保留')
    row = owned(db, user, run_id, payload.expected_version)
    flow.require_approved(row.data, 'copy')
    flow.require_visual_candidate_current(row.data)
    flow.require_content_sample(row.data)
    flow.require_magazine_content(row.data)
    flow.require_teaching_content(row.data)
    if row.data.get('pdf_page_plan'):
        flow.validate_pdf_page_plan(row.data['pdf_page_plan'], row.data['source']['page_count'])
    elif row.data.get('collage_plan'):
        flow.validate_collage_plan(row.data['collage_plan'], row.data['source']['page_count'])
    file, bank, fd = source_fd(db, user, settings, row); os.close(fd)
    original = deepcopy(row.data)
    reused_cover = flow.approved(original, 'cover') and bool(original.get('cover'))
    if reused_cover:
        asset_path(settings, user, row, original['cover'])
    d = deepcopy(original)
    d['bundle_requests'] = {**d.get('bundle_requests', {}), key: {
        'status': 'generating', 'expected_version': payload.expected_version,
        'input_digest': flow.fingerprint(original, 'set'), 'at': shanghai_now().isoformat()}}
    d['operation'] = {'key': key, 'status': 'generating', 'kind': 'render_bundle', 'started_at': shanghai_now().isoformat()}
    row.data = d; commit(db); reserved_version = row.row_version
    try:
        cover = original['cover'] if reused_cover else render_assets(db, user, settings, row, 'cover')[0][0]
        staged = {**row.data, 'cover': cover}
        assets, direction, treatment = render_assets(db, user, settings, row, 'set', render_data=staged)
        candidate = {**staged, 'images': [cover, *assets]}
        if not flow.complete_set(candidate):
            raise HTTPException(422, '整套图与当前方案不一致，旧图保留；请重新制作')
        # No image or approval is replaced until every render and source check succeeds.
        file, bank, fd = source_fd(db, user, settings, row); os.close(fd)
        db.refresh(row)
        if row.row_version != reserved_version or row.data.get('operation', {}).get('key') != key:
            raise HTTPException(409, '制作期间工作记录已变化，旧图保留；请刷新核对')
        updated = flow.checkpoint(original, '一次制作封面与整套图，等待成品审核')
        updated['bundle_requests'] = deepcopy(row.data['bundle_requests'])
        updated['operation'] = deepcopy(row.data['operation'])
        flow.invalidate(updated, 'set' if reused_cover else 'cover')
        updated.update(cover=cover, images=[cover, *assets], direction=direction, display_treatment=treatment)
        flow.mark_bundle(updated, key, reused_cover)
        updated['bundle_requests'][key].update(status='completed', result_digest=flow.fingerprint(updated, 'set'))
        updated['operation']['status'] = 'completed'
        flow.event(updated, 'render_bundle', reused_cover=reused_cover, image_count=len(updated['images']), human_review_pending=True)
        record(updated, 'visual_production', tool='deterministic_pdf_svg_renderer',
               inputs={'copy': flow.fingerprint(original, 'copy'), 'source': original['source'], 'plan': original['visual_plan'], 'set_plan': original.get('set_plan')},
               outputs={'set_digest': flow.fingerprint(updated, 'set'), 'assets': [{'id': a['id'], 'sha256': a['sha256']} for a in updated['images']]},
               scope='local_only; cover_and_all_inner_pages; human_review_pending')
        row.data = updated; commit(db)
    except Exception as exc:
        db.rollback(); db.refresh(row)
        failed = deepcopy(row.data)
        if failed.get('operation', {}).get('key') == key and failed['operation'].get('status') == 'generating':
            failed['operation']['status'] = 'failed'
            failed['bundle_requests'][key]['status'] = 'failed'
            record(failed, 'visual_production', tool='deterministic_pdf_svg_renderer', status='failed',
                   inputs={'input_digest': failed['bundle_requests'][key]['input_digest']}, outputs={'previous_images_retained': True}, scope='local_only')
            row.data = failed; commit(db)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(422, '整套制作未完成，原文案、旧图和失败素材均保留；请刷新后重试') from None
    return view(row)


@router.post('/{run_id}/append-collages')
def append_collages(run_id: int, payload: AppendCollages, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    """Append/replace two PDF grids while preserving every existing base asset."""
    row = owned(db, user, run_id); key = str(payload.request_key)
    if row.data.get('pdf_page_plan'):
        raise HTTPException(409, '当前已改为独立PDF样页，不再追加四宫格；旧拼图仍保留在历史版本')
    plan = payload.collage_plan.model_dump(); signature = flow.digest(plan)
    previous = row.data.get('collage_requests', {}).get(key)
    if previous:
        if previous['signature'] != signature:
            raise HTTPException(409, '同一拼图请求的选页已变化，请刷新后重新制作')
        if previous['status'] == 'completed' and previous.get('result_digest') == flow.fingerprint(row.data, 'set'):
            return view(row)
        raise HTTPException(409, '这次拼图请求已处理或内容已变化，请刷新后重试；不会重复追加图片')
    row = owned(db, user, run_id, payload.expected_version)
    flow.require_approved(row.data, 'copy')
    flow.validate_collage_plan(plan, row.data['source']['page_count'])
    original = deepcopy(row.data)
    base = deepcopy(original); base.pop('collage_plan', None)
    base['images'] = [asset for asset in original['images'] if asset['kind'] != 'collage']
    if not flow.complete_set(base):
        raise HTTPException(409, '请先按当前方案生成完整的原封面与内页；追加拼图不会替你重做原图或复用不匹配版本')
    for asset in original['images']:
        asset_path(settings, user, row, asset)
    file, bank, fd = source_fd(db, user, settings, row); os.close(fd)
    if original.get('collage_plan') == plan and flow.complete_set(original):
        return view(row)
    reserved = deepcopy(original)
    reserved['collage_requests'] = {**reserved.get('collage_requests', {}), key: {
        'status': 'generating', 'signature': signature, 'expected_version': payload.expected_version,
        'input_digest': flow.fingerprint(original, 'set'), 'at': shanghai_now().isoformat()}}
    reserved['operation'] = {'key': key, 'status': 'generating', 'kind': 'append_collages', 'started_at': shanghai_now().isoformat()}
    row.data = reserved; commit(db); reserved_version = row.row_version
    try:
        staged = deepcopy(row.data); staged['collage_plan'] = plan
        staged['page_overrides'] = {slot: value for slot, value in staged.get('page_overrides', {}).items() if not slot.startswith('collage-')}
        assets, direction, treatment = render_assets(db, user, settings, row, 'collage', render_data=staged)
        candidate = {**staged, 'images': [*base['images'], *assets]}
        if len(assets) != 2 or any(asset['kind'] != 'collage' for asset in assets) or not flow.complete_set(candidate):
            raise HTTPException(422, '四宫格未按当前8页计划完整生成，原封面和内页均保留')
        file, bank, fd = source_fd(db, user, settings, row); os.close(fd)
        for asset in base['images']:
            asset_path(settings, user, row, asset)
        db.refresh(row)
        if row.row_version != reserved_version or row.data.get('operation', {}).get('key') != key:
            raise HTTPException(409, '制作期间工作记录已变化，未追加或替换图片；请刷新核对')
        updated = flow.checkpoint(original, '末尾追加两张真实PDF四宫格，保留原封面与内页')
        flow.invalidate(updated, 'set')
        updated.update(collage_plan=plan, cover=original['cover'], images=[*base['images'], *assets],
                       direction=direction, display_treatment=treatment, page_overrides=staged['page_overrides'],
                       collage_requests=deepcopy(row.data['collage_requests']), operation=deepcopy(row.data['operation']))
        flow.mark_bundle(updated, key, reused_cover=True)
        updated['collage_requests'][key].update(status='completed', result_digest=flow.fingerprint(updated, 'set'))
        updated['operation']['status'] = 'completed'
        trace.record(updated, 'append_pdf_collages', 'local_pdf_grid_renderer', inputs={'collage_plan': plan, 'base_asset_ids': [a['id'] for a in base['images']]},
                     outputs={'collage_assets': [{'id': a['id'], 'sha256': a['sha256'], 'source_pages': a['source_pages']} for a in assets]},
                     scope='local_only; keep_original_assets_and_history; pending_human_review; no_export_or_publication')
        flow.event(updated, 'append_pdf_collages', base_image_count=len(base['images']), collage_count=2, human_review_pending=True)
        row.data = updated; commit(db)
    except Exception as exc:
        db.rollback(); db.refresh(row); failed = deepcopy(row.data)
        if failed.get('operation', {}).get('key') == key and failed['operation'].get('status') == 'generating':
            failed['operation']['status'] = 'failed'; failed['collage_requests'][key]['status'] = 'failed'
            trace.record(failed, 'append_pdf_collages', 'local_pdf_grid_renderer', status='failed',
                         inputs={'collage_plan': plan}, outputs={'original_assets_retained': True}, scope='local_only; no_approval_or_export')
            row.data = failed; commit(db)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(422, '拼图制作未完成，原封面、内页、旧稿和失败素材均保留；请刷新后重试') from None
    return view(row)


@router.post('/{run_id}/append-pdf-pages')
def append_pdf_pages(run_id: int, payload: AppendPdfPages, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    """Replace preview tails with eight full-page originals; retain every base image."""
    row = owned(db, user, run_id); key = str(payload.request_key)
    plan = payload.pdf_page_plan.model_dump(); signature = flow.digest(plan)
    previous = row.data.get('pdf_page_requests', {}).get(key)
    if previous:
        if previous['signature'] != signature:
            raise HTTPException(409, '同一单页预览请求的选页已变化，请刷新后重新制作')
        if previous['status'] == 'completed' and previous.get('result_digest') == flow.fingerprint(row.data, 'set'):
            return view(row)
        raise HTTPException(409, '这次单页预览请求已处理或内容已变化，请刷新后重试；不会重复追加图片')
    row = owned(db, user, run_id, payload.expected_version)
    flow.require_approved(row.data, 'copy')
    flow.validate_pdf_page_plan(plan, row.data['source']['page_count'])
    original = deepcopy(row.data)
    base = deepcopy(original); base.pop('collage_plan', None); base.pop('pdf_page_plan', None)
    base['images'] = [asset for asset in original['images'] if asset['kind'] not in {'collage', 'pdf-page'}]
    if not flow.complete_set(base):
        raise HTTPException(409, '请先按当前方案生成完整的原封面与内页；替换单页预览不会重做原图或复用不匹配版本')
    for asset in original['images']:
        asset_path(settings, user, row, asset)
    file, bank, fd = source_fd(db, user, settings, row); os.close(fd)
    if original.get('pdf_page_plan') == plan and 'collage_plan' not in original and flow.complete_set(original):
        return view(row)
    reserved = deepcopy(original)
    reserved['pdf_page_requests'] = {**reserved.get('pdf_page_requests', {}), key: {
        'status': 'generating', 'signature': signature, 'expected_version': payload.expected_version,
        'input_digest': flow.fingerprint(original, 'set'), 'at': shanghai_now().isoformat()}}
    reserved['operation'] = {'key': key, 'status': 'generating', 'kind': 'append_pdf_pages', 'started_at': shanghai_now().isoformat()}
    row.data = reserved; commit(db); reserved_version = row.row_version
    try:
        staged = deepcopy(row.data); staged['pdf_page_plan'] = plan; staged.pop('collage_plan', None)
        staged['page_overrides'] = {slot: value for slot, value in staged.get('page_overrides', {}).items() if not slot.startswith(('collage-', 'pdf-page-'))}
        assets, direction, treatment = render_assets(db, user, settings, row, 'pdf-pages', render_data=staged)
        candidate = {**staged, 'images': [*base['images'], *assets]}
        if len(assets) != 8 or any(asset['kind'] != 'pdf-page' for asset in assets) or not flow.complete_set(candidate):
            raise HTTPException(422, '8张独立样页未按当前升序选页完整生成，原封面与内页均保留')
        file, bank, fd = source_fd(db, user, settings, row); os.close(fd)
        for asset in base['images']:
            asset_path(settings, user, row, asset)
        db.refresh(row)
        if row.row_version != reserved_version or row.data.get('operation', {}).get('key') != key:
            raise HTTPException(409, '制作期间工作记录已变化，未追加或替换图片；请刷新核对')
        updated = flow.checkpoint(original, '将末尾预览改为8张独立PDF样页，保留原封面与内页及旧拼图历史')
        flow.invalidate(updated, 'set'); updated.pop('collage_plan', None)
        updated.update(pdf_page_plan=plan, cover=original['cover'], images=[*base['images'], *assets],
                       direction=direction, display_treatment=treatment, page_overrides=staged['page_overrides'],
                       pdf_page_requests=deepcopy(row.data['pdf_page_requests']), operation=deepcopy(row.data['operation']))
        flow.mark_bundle(updated, key, reused_cover=True)
        updated['pdf_page_requests'][key].update(status='completed', result_digest=flow.fingerprint(updated, 'set'))
        updated['operation']['status'] = 'completed'
        trace.record(updated, 'append_pdf_pages', 'local_pdf_full_page_renderer', inputs={'pdf_page_plan': plan, 'base_asset_ids': [a['id'] for a in base['images']]},
                     outputs={'page_assets': [{'id': a['id'], 'sha256': a['sha256'], 'source_page': a['source_page']} for a in assets]},
                     scope='local_only; ascending_unique_full_pages; retain_base_assets_and_legacy_collage_history; pending_human_review; no_export_or_publication')
        flow.event(updated, 'append_pdf_pages', base_image_count=len(base['images']), full_page_count=8, human_review_pending=True)
        row.data = updated; commit(db)
    except Exception as exc:
        db.rollback(); db.refresh(row); failed = deepcopy(row.data)
        if failed.get('operation', {}).get('key') == key and failed['operation'].get('status') == 'generating':
            failed['operation']['status'] = 'failed'; failed['pdf_page_requests'][key]['status'] = 'failed'
            trace.record(failed, 'append_pdf_pages', 'local_pdf_full_page_renderer', status='failed',
                         inputs={'pdf_page_plan': plan}, outputs={'original_assets_retained': True}, scope='local_only; no_approval_or_export')
            row.data = failed; commit(db)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(422, '独立PDF样页制作未完成，原图、旧拼图、旧稿与失败素材均保留；请刷新后重试') from None
    return view(row)


@router.post('/{run_id}/revise')
def revise(run_id: int, payload: Revise, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    row = owned(db, user, run_id, payload.expected_version); d = row.data
    asset = next((a for a in ([d['cover']] if d.get('cover') else []) + d['images'] if a['id'] == payload.asset_id), None)
    if not asset: raise HTTPException(404, '当前版本没有这张图，请刷新')
    if asset['kind'] == 'collage':
        if payload.brief.text.strip() or payload.brief.nodes or ('layout' in payload.brief.model_fields_set and payload.brief.layout != 'pdf-grid-2x2'):
            raise HTTPException(422, '真实PDF四宫格仅可修改图外标题和说明；原页内容与2×2布局保持不变，换页请使用拼图选页')
        payload.brief.layout = 'pdf-grid-2x2'
    if asset['kind'] == 'pdf-page':
        if payload.brief.text.strip() or payload.brief.nodes or ('layout' in payload.brief.model_fields_set and payload.brief.layout != 'full-page'):
            raise HTTPException(422, '独立PDF样页仅可修改图外标题和说明，原页内容保持不变；换页请使用单页预览选页')
        payload.brief.layout = 'full-page'
    combined = flow.bundle_ready(d)
    flow.require_approved(d, 'copy' if asset['kind'] == 'cover' or combined else 'cover')
    assets, direction, treatment = render_assets(db, user, settings, row, 'revise', {'asset': asset, 'brief': payload.brief.model_dump()})
    updated = flow.checkpoint(d, '单张调整并另存新版本'); flow.invalidate(updated, 'cover' if asset['kind'] == 'cover' else 'set')
    updated['page_overrides'] = {**d.get('page_overrides', {}), asset['slot']: payload.brief.model_dump()}
    if asset['kind'] == 'cover':
        updated['cover'] = assets[0]
        if combined: updated['images'] = [assets[0], *d['images'][1:]]
    else: updated['images'] = [assets[0] if a['id'] == asset['id'] else a for a in d['images']]
    updated['direction'] = direction; updated['display_treatment'] = treatment
    if combined: flow.mark_bundle(updated)
    flow.event(updated, 'revise_image', previous_asset=asset['id']); row.data = updated; commit(db)
    return view(row)


@router.post('/{run_id}/approve')
def approve(run_id: int, payload: Approve, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    row = owned(db, user, run_id, payload.expected_version); d = deepcopy(row.data)
    if not payload.reviewed or payload.digest != flow.fingerprint(d, payload.stage):
        raise HTTPException(409, '请阅读并确认当前版本，内容变化后需重新审核')
    file, bank, fd = source_fd(db, user, settings, row); os.close(fd)
    if payload.stage == 'copy':
        c = d['copy']
        selected = [e for e in d['evidence'] if e['id'] in d['selected_source_ids'] and not e.get('excluded')]
        if not selected:
            raise HTTPException(422, '请先选择本课相关参考来源')
        quality = evidence_review(selected)
        if quality['limited'] and not payload.limited_sources_reviewed:
            raise HTTPException(422, '参考来源仅有摘要或摘录，请明确确认其不代表已验证的学生问题、热榜或购买需求')
        if not c['topic'].strip() or not c['title'].strip() or not c['body'].strip() or len(c['title']) > 20 or len(c['body']) > 1000:
            raise HTTPException(422, '请完善选题和正文，并通过本地20字标题、1000字正文检查')
    else:
        combined = payload.stage == 'set' and payload.combined_review
        if combined:
            flow.require_approved(d, 'copy')
            if not flow.bundle_ready(d) and not flow.approved(d, 'cover'):
                raise HTTPException(409, '请先按当前方案制作完整图片，再审核成品')
            if not flow.complete_set(d):
                raise HTTPException(422, '当前图片与整套方案不一致，请重新制作后审核')
        else:
            flow.require_approved(d, 'copy' if payload.stage == 'cover' else 'cover')
        candidates = [d['cover']] if payload.stage == 'cover' else d['images']
        if not candidates or any(a is None for a in candidates): raise HTTPException(422, '请先生成当前图稿')
        for a in candidates: asset_path(settings, user, row, a)
        if payload.stage == 'set' and not any(a['kind'] in ({'pdf-page'} if d['visual_plan'].get('template_id') == 'magazine-a' else {'sample'}) for a in candidates):
            raise HTTPException(422, '整套须保留真实PDF样张')
    d['approvals'][payload.stage] = {'digest': payload.digest, 'at': shanghai_now().isoformat(), 'source': 'manual_workbench_review'}
    if payload.stage == 'set' and payload.combined_review:
        from backend.app.services.course_visual_trace import record
        d['approvals']['set']['review_scope'] = 'cover_and_all_inner_pages'
        d['approvals']['cover'] = {'digest': flow.fingerprint(d, 'cover'), 'at': d['approvals']['set']['at'],
                                  'source': 'manual_combined_final_review', 'review_scope': 'cover_and_all_inner_pages'}
        record(d, 'final_review', tool='human_workbench_review', inputs={'set_digest': payload.digest},
               outputs={'cover_and_set_approved': True}, scope='explicit_human_review; no_export_or_publication')
    if payload.stage == 'copy':
        d['approvals']['copy'].update(source_quality=quality,
            limited_sources_reviewed=bool(quality['limited'] and payload.limited_sources_reviewed))
        trace.record(d, 'copy_review', 'human_workbench_review', inputs={'copy_digest': payload.digest},
                     outputs={'copy_approved': True}, scope='explicit_human_review; no_image_generation')
    flow.event(d, 'approve_' + payload.stage); row.data = d; commit(db)
    return view(row)


@router.post('/{run_id}/export')
def export(run_id: int, payload: Export, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    row = owned(db, user, run_id); d = deepcopy(row.data)
    if d.get('export') and d['export']['digest'] == flow.fingerprint(d, 'set'):
        if not export_draft_available(db, row, d):
            raise HTTPException(409, '原文案和整套图片仍保留，但原草稿已删除或无法确认关联；未打开或新建其他草稿')
        return view(row)
    row = owned(db, user, run_id, payload.expected_version)
    for stage in ['copy', 'cover', 'set']: flow.require_approved(d, stage)
    if not payload.reviewed or payload.digest != flow.fingerprint(d, 'set'):
        raise HTTPException(409, '请确认将当前审核版本另存为新草稿')
    file, bank, fd = source_fd(db, user, settings, row); os.close(fd)
    target = Path(settings.storage_dir) / 'media'; target.mkdir(parents=True, exist_ok=True)
    paths = []
    for a in d['images']:
        path = asset_path(settings, user, row, a)
        name = f'xhs-asset-u{user.id}-workflow-{row.id}-{a["id"]}.png'; destination = target / name
        if destination.exists():
            if flow.hash_file(destination) != a['sha256']: raise HTTPException(409, '素材文件冲突，未覆盖')
        else:
            with destination.open('xb') as stream: stream.write(path.read_bytes())
        paths.append(name)
    draft = AiDraft(user_id=user.id, platform='xhs', title=d['copy']['title'], body=d['copy']['body'], tags=[{'id': '', 'name': s.lstrip('#')} for s in d['copy']['tags']], source_note_id=None)
    db.add(draft); db.flush()
    for i, name in enumerate(paths): db.add(DraftAsset(draft_id=draft.id, asset_type='image', local_path=name, url='', sort_order=i))
    from backend.app.services.course_draft_origin import draft_binding
    d['export'] = {'draft_id': draft.id, 'digest': flow.fingerprint(d, 'set'), 'at': shanghai_now().isoformat(),
        'snapshot': {**draft_binding(draft), 'version': 1, 'source': deepcopy(d['source']), 'copy': deepcopy(d['copy']),
                     'approvals': deepcopy(d['approvals']), 'workflow_revision': d['revision'],
                     'materials': [{'asset_type': 'image', 'local_path': name, 'url': '', 'sort_order': i, 'sha256': d['images'][i]['sha256']} for i, name in enumerate(paths)],
                     'source_research_id': d.get('research_id'), 'workflow_digest': flow.fingerprint(d, 'set')}}
    trace.record(d, 'save_new_draft', 'local_draft_workshop', inputs={'set_digest': payload.digest},
                 outputs={'draft_id': draft.id, 'asset_ids': [a['id'] for a in d['images']]},
                 scope='new_local_draft_only; preserve_old_drafts; no_publish_or_automatic_tasks')
    flow.event(d, 'save_new_draft', draft_id=draft.id); row.data = d; commit(db)
    return view(row)


@router.post('/{run_id}/restore')
def restore(run_id: int, payload: Restore, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    row = owned(db, user, run_id, payload.expected_version)
    old = next((h for h in row.data['history'] if h['revision'] == payload.revision), None)
    if not old: raise HTTPException(404, '历史版本不存在')
    d = flow.checkpoint(row.data, '以历史版本重新编辑')
    for k in ['copy', 'visual_plan', 'evidence', 'selected_source_ids', 'cover', 'images']: d[k] = deepcopy(old[k])
    if 'set_plan' in old:
        d['set_plan'] = deepcopy(old['set_plan'])
    else:
        d.pop('set_plan', None)
    if 'collage_plan' in old:
        d['collage_plan'] = deepcopy(old['collage_plan'])
    else:
        d.pop('collage_plan', None)
    if 'pdf_page_plan' in old:
        d['pdf_page_plan'] = deepcopy(old['pdf_page_plan'])
    else:
        d.pop('pdf_page_plan', None)
    d['page_overrides'] = deepcopy(old.get('page_overrides', {}))
    d['backgrounds'] = deepcopy(old.get('backgrounds', {}))
    d['approvals'] = {}; d['export'] = None
    d.pop('render_bundle', None)
    flow.event(d, 'restore_as_new_revision', from_revision=payload.revision); row.data = d; commit(db)
    return view(row)


@router.get('/{run_id}/images/{asset_id}')
def image(run_id: int, asset_id: str, source: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db), settings=Depends(require_library)):
    row = owned(db, user, run_id); states = [row.data, *row.data['history']]
    for state in states:
        for a in ([state['cover']] if state.get('cover') else []) + state.get('images', []):
            if a['id'] == asset_id:
                path = asset_path(settings, user, row, a)
                if source:
                    name = a.get('svg_file', '')
                    if Path(name).name != name or not name.endswith('.svg'): raise HTTPException(404, '该历史图稿没有SVG源文件')
                    path = path.with_name(name)
                    if not path.is_file() or flow.hash_file(path) != a.get('svg_sha256'): raise HTTPException(404, 'SVG源文件不可用')
                    return FileResponse(path, media_type='image/svg+xml', filename=name)
                return FileResponse(path, media_type='image/png')
    raise HTTPException(404, '图片不存在')
