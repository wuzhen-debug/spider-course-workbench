"""Explicit local workbench import; no network, approvals, drafts or publishing.

Run dry validation first. The CLI only writes when --apply is provided and always
uses an explicit existing SQLite database; it never initializes or migrates it.
"""
from copy import deepcopy
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from types import SimpleNamespace
from uuid import uuid4
import xml.etree.ElementTree as ET

from fastapi import HTTPException
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.models import User
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.services import course_visual_workflow as flow
from backend.app.services import course_visual_trace as trace


def local_file(root, relative, suffix):
    """No absolute path, parent escape or symlink at any bundle component."""
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or rel.suffix.lower() != suffix:
        raise ValueError('Import asset path is not a permitted relative file')
    path = root / rel
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Import asset escaped its explicit bundle')
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError('Import asset cannot be a symlink')
        current = current.parent
    if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > 25 * 1024 * 1024:
        raise ValueError('Import asset must be a bounded regular file')
    return path


def safe_svg(path):
    raw = path.read_bytes()
    if len(raw) > 5 * 1024 * 1024 or re.search(br'<!DOCTYPE|<!ENTITY', raw, re.I):
        raise ValueError('SVG source is not a bounded passive document')
    tree = ET.fromstring(raw)
    for node in tree.iter():
        tag = node.tag.rsplit('}', 1)[-1].lower()
        if tag in {'script', 'foreignobject', 'animate', 'set', 'iframe', 'style'}:
            raise ValueError('Active SVG content is not importable')
        for key, value in node.attrib.items():
            key = key.rsplit('}', 1)[-1].lower()
            if key.startswith('on') or (key == 'href' and not value.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,', '#'))):
                raise ValueError('SVG event handlers or external resources are not importable')


def import_bundle(db, user, settings, *, manifest_path, content, file_id,
                  revision_id, source_sha256, request_key, apply=False):
    """Validate all inputs before creating a new owner-scoped workbench record."""
    from backend.app.api.course_library_drafts import PlanRequest, build_plan, stable_source, unchanged
    from backend.app.api.course_visual_workflow import Copy, VisualPlan, SetPlan
    manifest_path = Path(manifest_path).absolute()
    if manifest_path.is_symlink() or manifest_path.parent.is_symlink() or not manifest_path.is_file():
        raise ValueError('Explicit local manifest is not a regular file')
    root = manifest_path.parent
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('source_pdf_sha256') != source_sha256 or not re.fullmatch(r'[a-f0-9]{64}', source_sha256):
        raise ValueError('Manifest source SHA does not match explicit source')
    entries = manifest.get('files', [])
    if len(entries) != 13 or [e.get('order') for e in entries] != list(range(1, 14)):
        raise ValueError('A import requires exactly four teaching images followed by nine PDF pages')
    pages = [entry.get('source_physical_page') for entry in entries[4:]]
    if len(set(pages)) != 9 or pages != sorted(pages) or any(not isinstance(p, int) or isinstance(p, bool) or p < 2 for p in pages):
        raise ValueError('PDF previews must be nine distinct ordered body pages')
    checked_copy = Copy.model_validate(content['copy']).model_dump(exclude_none=True)
    checked_plan = VisualPlan.model_validate(content['visual_plan']).model_dump(exclude_none=True)
    checked_set = SetPlan.model_validate(content['set_plan']).model_dump()
    if checked_plan['template_id'] != 'magazine-a':
        raise ValueError('This import only accepts the explicitly chosen magazine A master')
    if not checked_copy['title'].strip() or len(checked_copy['title']) > 20 or not checked_copy['body'].strip() or len(checked_copy['body']) > 1000:
        raise ValueError('Imported copy must be reviewable within local title/body limits')
    file, bank, revision, fd = stable_source(db, user, settings, file_id, revision_id)
    try:
        if revision.sha256 != source_sha256:
            raise ValueError('Current owner-scoped PDF revision differs from import source')
        import pypdfium2 as pdfium
        with os.fdopen(os.dup(fd), 'rb') as stream:
            document = pdfium.PdfDocument(stream)
            if any(n > len(document) for n in pages):
                raise ValueError('Preview page exceeds the actual source PDF')
            checked = []
            for index, entry in enumerate(entries):
                png = local_file(root, entry['file'], '.png')
                if flow.hash_file(png) != entry.get('sha256'):
                    raise ValueError('PNG SHA mismatch; no workflow was created')
                image = Image.open(png)
                if image.format != 'PNG' or list(image.size) != [entry.get('width'), entry.get('height')]:
                    raise ValueError('PNG format or dimensions do not match manifest')
                image.load()
                if index < 4:
                    if image.size != (1080, 1440):
                        raise ValueError('Teaching image canvas must match selected A master')
                    svg = local_file(root, str(Path('editable') / (png.stem + '.svg')), '.svg')
                    safe_svg(svg)
                else:
                    svg = None
                    n = pages[index - 4]
                    page = document[n - 1]
                    if not (0 < image.width <= 6000 and 0 < image.height <= 10000):
                        raise ValueError('Original preview dimensions are not bounded')
                    bitmap = page.render(scale=image.width / page.get_width())
                    fresh = bitmap.to_pil().convert('RGB')
                    if fresh.size != image.size or hashlib.sha256(fresh.tobytes()).digest() != hashlib.sha256(image.convert('RGB').tobytes()).digest():
                        raise ValueError('Preview pixels differ from unchanged original PDF render')
                    bitmap.close(); page.close()
                checked.append((entry, png, svg, image.size))
            document.close()
        unchanged(file, bank, fd)
    finally:
        os.close(fd)
    source = build_plan(db, user, settings, file_id, PlanRequest(revision_id=revision_id, pages=[1]))['source']
    state = flow.initial_data(source, flow.catalog(), 'magazine-a')
    state.update(copy=checked_copy, visual_plan=checked_plan, set_plan=checked_set,
                 pdf_page_plan={'pages': pages}, label=f'{source["course_code"]} · A版 · 待审核（4+9）')
    state['entry_mode'] = 'pdf-driven'
    evidence_id = f'pdf-{revision_id}-{source_sha256[:12]}'
    mapped_pages = sorted({page for item in content.get('source_map', []) for page in item.get('pdf_pages', [])}) or sorted(set(pages))
    if any(not isinstance(page, int) or isinstance(page, bool) or page < 1 or page > source['page_count'] for page in mapped_pages):
        raise ValueError('Source map exceeds the confirmed PDF')
    state['evidence'] = [{'id': evidence_id, 'evidence_type': 'pdf-analysis', 'source_url': '',
                          'title': source['filename'], 'content_status': 'pdf-analysis', 'comments': [],
                          'content': '基于同版本PDF的教学分析与真实资料使用方式；没有小红书评论需求验证。',
                          'pdf_pages': mapped_pages,
                          'excluded': False}]
    state['selected_source_ids'] = [evidence_id]
    state['source_map'] = deepcopy(content.get('source_map', []))
    state['template_selection'] = {'template_id': 'magazine-a', 'source': 'explicit_user_style_selection',
                                 'confirmation': '选a吧', 'scope': 'visual_style_only; final_copy_and_set_pending_review'}
    content_digest = hashlib.sha256(json.dumps({'copy': checked_copy, 'visual_plan': checked_plan, 'set_plan': checked_set,
        'source_map': content.get('source_map', [])}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    state['import'] = {'manifest_digest': flow.hash_file(manifest_path), 'content_digest': content_digest, 'source_sha256': source_sha256,
                       'tool': 'explicit_local_review_bundle_import', 'status': 'pending_human_review'}
    flow.validate_pdf_page_plan(state['pdf_page_plan'], source['page_count'])
    flow.require_magazine_content(state)
    directions = flow.direct(state)['pages']
    if len(directions) != 13:
        raise ValueError('Imported content does not produce exactly four teaching plus nine preview slots')
    previous = db.scalar(select(CourseVisualWorkflow).where(CourseVisualWorkflow.user_id == user.id,
                         CourseVisualWorkflow.request_key == request_key))
    if previous is not None:
        if (previous.file_id != file_id or previous.data['source']['revision_id'] != revision_id or
                previous.data.get('import', {}).get('manifest_digest') != state['import']['manifest_digest'] or
                previous.data.get('import', {}).get('content_digest') != content_digest):
            raise ValueError('Import key belongs to different content; existing workflow was preserved')
        return {'status': 'already_imported', 'run_id': previous.id, 'image_count': len(previous.data.get('images', []))}
    if not apply:
        return {'status': 'validated_dry_run', 'file_id': file_id, 'revision_id': revision_id,
                'image_count': 13, 'source_sha256': source_sha256, 'approvals': {}, 'export': None}
    storage = Path(settings.storage_dir).resolve()
    row = CourseVisualWorkflow(user_id=user.id, file_id=file_id, request_key=request_key, data={})
    db.add(row); db.flush()
    target = storage / 'course-visual' / f'u{user.id}' / f'r{row.id}'
    generation = 'import-' + uuid4().hex
    destination = target / generation
    for p in [storage, storage / 'course-visual', target.parent, target, destination]:
        if p.is_symlink():
            raise ValueError('Workflow storage directory cannot be a symlink')
    destination.mkdir(parents=True, exist_ok=False)
    assets = []
    for direction, (entry, png, svg, size) in zip(directions, checked):
        name = f'{entry["order"]:02d}-{uuid4().hex}.png'
        output = destination / name
        with output.open('xb') as stream:
            stream.write(png.read_bytes())
        if flow.hash_file(output) != entry['sha256']:
            raise ValueError('Copied PNG failed SHA verification; pending transaction must roll back')
        asset = {'id': uuid4().hex, 'slot': direction['slot'], 'kind': direction['kind'],
                 'role': direction['title'], 'file': name, 'path': f'{generation}/{name}',
                 'sha256': entry['sha256'], 'width': size[0], 'height': size[1],
                 'brief': {k: deepcopy(direction.get(k, [] if k == 'nodes' else '')) for k in ['title', 'subtitle', 'text', 'layout', 'nodes']}}
        for field in ['source_page', 'source_pages', 'raw_pdf']:
            if field in direction:
                asset[field] = deepcopy(direction[field])
        if svg is not None:
            svg_name = Path(name).with_suffix('.svg').name
            with (destination / svg_name).open('xb') as stream:
                stream.write(svg.read_bytes())
            asset.update(svg_file=svg_name, svg_sha256=flow.hash_file(destination / svg_name))
        assets.append(asset)
    state.update(cover=assets[0], images=assets, approvals={}, export=None, history=[])
    if not flow.complete_set(state):
        raise ValueError('Imported actual images do not match the intended A slots')
    flow.mark_bundle(state, request_key=request_key)
    trace.record(state, 'import_local_visual_set', 'sha_verified_local_bundle_import',
                 inputs={'source': source, 'manifest_digest': state['import']['manifest_digest']},
                 outputs={'asset_ids': [a['id'] for a in assets], 'sha256': [a['sha256'] for a in assets]},
                 scope='local_workbench_only; no_approval_draft_export_publish_or_auto_tasks')
    flow.event(state, 'import_local_visual_set', image_count=13, human_review_pending=True)
    row.data = state
    # Caller owns the transaction and must commit or roll back explicitly.
    db.flush()
    return {'status': 'imported_pending_review', 'run_id': row.id, 'image_count': 13,
            'approvals': {}, 'export': None, 'url': f'http://127.0.0.1:8000/platforms/xhs/visual-workbench?run={row.id}&stage=set'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--storage-dir', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--content', required=True, type=Path)
    parser.add_argument('--owner-id', required=True, type=int)
    parser.add_argument('--file-id', required=True, type=int)
    parser.add_argument('--revision-id', required=True, type=int)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--request-key', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    database = args.database.resolve()
    if not database.is_file() or args.database.is_symlink():
        parser.error('Use an explicit existing local SQLite database, never an initialized replacement')
    engine = create_engine('sqlite:///' + str(database))
    cfg = get_settings()
    settings = SimpleNamespace(**cfg.model_dump(), storage_dir=args.storage_dir.resolve())
    with Session(engine) as db:
        try:
            user = db.get(User, args.owner_id)
            if user is None:
                raise ValueError('Owner not found')
            result = import_bundle(db, user, settings, manifest_path=args.manifest,
                content=json.loads(args.content.read_text()), file_id=args.file_id,
                revision_id=args.revision_id, source_sha256=args.source_sha256,
                request_key=args.request_key, apply=args.apply)
            if args.apply:
                db.commit()
            else:
                db.rollback()
            print(json.dumps(result, ensure_ascii=False))
        except Exception:
            db.rollback()
            raise


if __name__ == '__main__':
    main()
