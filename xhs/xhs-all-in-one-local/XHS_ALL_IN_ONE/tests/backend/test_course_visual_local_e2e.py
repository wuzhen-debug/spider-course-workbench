"""Opt-in local acceptance with a read-only snapshot of the actual FNCE10002 run.

Run from the application root:
COURSE_VISUAL_REAL_AUDIT=1 COURSE_VISUAL_AUDIT_LIBRARY=/path/to/library ../.venv/bin/python -m pytest -q -s \
  tests/backend/test_course_visual_local_e2e.py

Approvals below are deliberately simulated by a test identity in an isolated DB.
They are not user approvals and do not change the real workflow or draft.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pytest


pytestmark = pytest.mark.skipif(os.getenv('COURSE_VISUAL_REAL_AUDIT') != '1',
    reason='Explicit opt-in is required for the local real-material acceptance fixture')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        default=str).encode()).hexdigest()


def readonly_snapshot(path):
    """Logical hashes avoid SQLite WAL/file timestamp differences; no writes."""
    with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        tables = ['ai_drafts', 'draft_assets', 'course_visual_workflows',
                  'course_research', 'course_research_drafts', 'publish_jobs', 'auto_tasks']
        return {table: {'count': len(rows), 'sha256': digest(rows)}
            for table in tables
            for rows in [[dict(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY id')]]}


def test_actual_fnce10002_local_render_to_new_draft(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from PIL import Image, ImageDraw
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import sessionmaker
    from backend.app.api import course_visual_workflow as api, drafts, files
    from backend.app.api.course_library import require_library
    from backend.app.core.database import Base, get_db
    from backend.app.core.deps import get_current_user
    from backend.app.models import User, AiDraft, DraftAsset, PublishJob, AutoTask
    from backend.app.models.course_library import CourseLibraryRoot, CourseLibraryFile, CourseLibraryRevision
    from backend.app.models.course_visual_workflow import CourseVisualWorkflow
    from backend.app.services import course_visual_workflow as flow
    from backend.app.services.course_library_paths import signature

    app_root = Path(__file__).resolve().parents[2]
    install = app_root.parent
    real_db = install / 'data/spider_xhs.db'
    protected_before = readonly_snapshot(real_db)
    with sqlite3.connect(real_db.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        original = dict(db.execute('SELECT * FROM course_visual_workflows WHERE id=4').fetchone())
        actual = json.loads(original['data'])
        old_drafts = [dict(r) for r in db.execute('SELECT * FROM ai_drafts ORDER BY id')]
    assert original['file_id'] == 19901
    assert actual['source']['revision_id'] == 172
    assert actual['source']['course_code'] == 'FNCE10002'
    real_pdf = Path(os.environ['COURSE_VISUAL_AUDIT_LIBRARY']) / actual['source']['relative_path']
    original_pdf_before = {'sha256': sha(real_pdf), 'size': real_pdf.stat().st_size,
                           'mtime_ns': real_pdf.stat().st_mtime_ns}
    assert original_pdf_before['sha256'] == actual['source']['sha256']

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:6]
    delivery = install / 'delivery/20261030-full-flow-audit' / ('isolated-real-render-' + stamp)
    delivery.mkdir(parents=True)
    private = delivery / 'private'; private.mkdir()
    library = private / '题库'; library.mkdir()
    fixture_pdf = library / actual['source']['relative_path']
    fixture_pdf.parent.mkdir(parents=True)
    shutil.copy2(real_pdf, fixture_pdf)
    assert sha(fixture_pdf) == actual['source']['sha256']
    storage = private / 'storage'; storage.mkdir()
    media = storage / 'media'; media.mkdir()

    # Actual data is retained locally. Network is denied in this test and both
    # renderer subprocesses; source links are provenance, never fetched here.
    guard = private / 'network-guard'; guard.mkdir()
    (guard / 'sitecustomize.py').write_text('''import socket\n\ndef forbidden(*args, **kwargs):\n    raise RuntimeError("External network disabled in isolated local acceptance")\nsocket.socket.connect = forbidden\nsocket.socket.connect_ex = forbidden\nsocket.create_connection = forbidden\nsocket.getaddrinfo = forbidden\n''')
    (guard / 'guard.cjs').write_text('''const deny=()=>{throw new Error("External network disabled in isolated local acceptance")};
for (const mod of ['http','https']) {const m=require(mod);m.request=deny;m.get=deny;}
const net=require('net');net.connect=deny;net.createConnection=deny;net.Socket.prototype.connect=deny;
const tls=require('tls');tls.connect=deny;
const dns=require('dns');for(const k of Object.keys(dns)){if(/^(lookup|resolve|reverse)/.test(k)&&typeof dns[k]==='function')dns[k]=deny;}
globalThis.fetch=deny;
''')
    monkeypatch.setenv('PYTHONPATH', str(guard) + os.pathsep + str(app_root))
    monkeypatch.setenv('NODE_OPTIONS', '--require ' + json.dumps(str(guard / 'guard.cjs'), ensure_ascii=False))
    denied_calls = []
    def forbidden(*args, **kwargs):
        denied_calls.append('unexpected_network_attempt')
        raise AssertionError('No external network is authorized by this local acceptance')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)

    engine = create_engine(f'sqlite:///{private / "isolated.db"}', connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    owner = User(id=1, username='isolated-acceptance-test-identity', password_hash='not-a-login')
    data = flow.initial_data(deepcopy(actual['source']), flow.catalog())
    for key in ['brand', 'rules', 'copy', 'visual_plan', 'selected_source_ids', 'searches', 'research_id', 'analysis', 'research_handoff']:
        if key in actual:
            data[key] = deepcopy(actual[key])
    data['evidence'] = flow.public_evidence(actual['evidence'])
    data['research_handoff']['acceptance_test_identity'] = True
    (private / 'fixture.json').write_text(json.dumps({'origin_run_id': 4,
        'origin_row_version': original['row_version'], 'source': data['source'],
        'data': data, 'test_only': True, 'not_user_review': True}, ensure_ascii=False, indent=2))
    old_asset = media / 'isolated-existing-old-asset.png'
    Image.new('RGB', (32, 32), '#0755A2').save(old_asset)
    with factory() as db:
        db.add(owner); db.flush()
        db.add(CourseLibraryRoot(id=1, user_id=1, path=str(library.absolute()), status='ready'))
        stat = fixture_pdf.stat()
        db.add(CourseLibraryFile(id=19901, user_id=1, root_id=1,
            relative_path=data['source']['relative_path'], filename=data['source']['filename'],
            size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns, signature=signature(stat),
            status='ready', university=data['source']['university'], course_code='FNCE10002',
            term=data['source']['term'], material_type=data['source']['material_type'],
            current_revision_id=172, revision_count=1))
        db.add(CourseLibraryRevision(id=172, user_id=1, file_id=19901,
            sha256=data['source']['sha256'], size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns,
            page_count=data['source']['page_count'], pdf_status='valid'))
        for saved in old_drafts:
            db.add(AiDraft(id=saved['id'], user_id=1, platform=saved['platform'],
                title=saved['title'], body=saved['body'], tags=json.loads(saved['tags'] or '[]'),
                created_at=datetime.fromisoformat(saved['created_at'])))
        if not old_drafts:
            db.add(AiDraft(id=1, user_id=1, platform='xhs', title='Existing old draft fixture', body='Must stay unchanged', tags=[]))
        db.flush()
        db.add(DraftAsset(draft_id=1, asset_type='image', local_path=old_asset.name, url='', sort_order=0))
        db.add(CourseVisualWorkflow(id=4, user_id=1, file_id=19901, request_key=str(uuid4()), data=data))
        db.commit()
    def draft_snapshot():
        with factory() as db:
            return {'drafts': [dict(id=r.id, title=r.title, body=r.body, tags=r.tags,
                        created_at=r.created_at.isoformat()) for r in db.scalars(select(AiDraft).order_by(AiDraft.id))],
                    'assets': [dict(id=r.id, draft_id=r.draft_id, local_path=r.local_path,
                        sort_order=r.sort_order) for r in db.scalars(select(DraftAsset).order_by(DraftAsset.id))]}
    old_snapshot = draft_snapshot(); old_image_sha = sha(old_asset)
    settings = SimpleNamespace(storage_dir=storage, course_center_enabled=True,
        course_library_enabled=True, course_library_root=str(library.absolute()),
        course_library_owner_id=1, scheduler_enabled=False)
    def isolated_db():
        with factory() as db:
            yield db
    # A fresh app intentionally has no production lifespan, watcher or scheduler.
    app = FastAPI()
    for router in [api.router, drafts.router, files.router]:
        app.include_router(router, prefix='/api')
    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[require_library] = lambda: settings
    monkeypatch.setattr(files, 'get_settings', lambda: settings)
    trace = []
    prefix = '/api/course-center/visual-workflows/4'
    with TestClient(app) as client:
        row = client.get(prefix).json()
        def post(route, expected=200, **payload):
            nonlocal row
            response = client.post(prefix + '/' + route,
                json={'expected_version': row['row_version'], **payload})
            trace.append({'route': route, 'stage': payload.get('stage'), 'status': response.status_code})
            assert response.status_code == expected, response.text
            if expected == 200:
                row = response.json()
            return response
        def approve(stage):
            post('approve', stage=stage, reviewed=True, limited_sources_reviewed=True,
                 digest=row['digests'][stage])
        def read_image(asset):
            response = client.get('/api' + asset['url'])
            assert response.status_code == 200, response.text
            assert hashlib.sha256(response.content).hexdigest() == asset['sha256']
            assert Image.open(io.BytesIO(response.content)).size == (1080, 1440)
            svg = client.get('/api' + asset['url'], params={'source': True})
            assert svg.status_code == 200 and b'<svg' in svg.content
            assert hashlib.sha256(svg.content).hexdigest() == asset['svg_sha256']
        post('render', expected=409, stage='cover')
        post('render', expected=409, stage='set')
        post('approve', expected=422, stage='copy', reviewed=True, digest=row['digests']['copy'])
        approve('copy')
        post('render', stage='cover')
        first_cover = deepcopy(row['data']['cover']); read_image(first_cover)
        post('render', expected=409, stage='set')
        # Revision must be additive, and the previous PNG/SVG stays readable.
        post('revise', asset_id=first_cover['id'], brief=first_cover['brief'])
        assert row['data']['cover']['id'] != first_cover['id']
        read_image(first_cover); read_image(row['data']['cover'])
        approve('cover')
        post('render', stage='set')
        expected_kinds = ['cover'] + (['method'] if data['visual_plan']['method_text'].strip() else [])
        expected_kinds += ['sample'] * len(data['visual_plan']['sample_pages']) + ['use']
        assert [a['kind'] for a in row['data']['images']] == expected_kinds
        for image in row['data']['images']:
            read_image(image)
        post('export', expected=409, reviewed=True, digest=row['digests']['set'])
        approve('set')
        previous_version = row['row_version']; set_digest = row['digests']['set']
        post('export', reviewed=True, digest=set_digest)
        exported = row['data']['export']; new_id = exported['draft_id']
        assert new_id not in [r['id'] for r in old_snapshot['drafts']]
        assert exported['draft_available'] is True
        snapshot = exported['snapshot']
        assert snapshot['source'] == data['source']
        assert snapshot['copy'] == data['copy']
        assert snapshot['approvals'] == row['data']['approvals']
        assert snapshot['source_research_id'] == data['research_id']
        assert snapshot['workflow_digest'] == set_digest
        assert all(row['approved'].values())
        listed = client.get('/api/drafts', params={'platform': 'xhs'}).json()
        assert any(r['id'] == new_id for r in listed['items'])
        assets = client.get(f'/api/drafts/{new_id}/assets').json()['items']
        assert [a['sort_order'] for a in assets] == list(range(len(expected_kinds)))
        assert [a['local_path'] for a in assets] == [a['local_path'] for a in snapshot['materials']]
        for i, asset in enumerate(assets):
            response = client.get(asset['url'])
            assert response.status_code == 200
            assert hashlib.sha256(response.content).hexdigest() == row['data']['images'][i]['sha256']
            assert sha(media / asset['local_path']) == snapshot['materials'][i]['sha256']
        retry = client.post(prefix + '/export', json={'expected_version': previous_version,
            'reviewed': True, 'digest': set_digest})
        assert retry.status_code == 200 and retry.json()['data']['export']['draft_id'] == new_id
        resumed = client.get(prefix).json()
        assert resumed['data']['export']['draft_id'] == new_id
        assert [a['id'] for a in resumed['data']['images']] == [a['id'] for a in row['data']['images']]
        assert not resumed['publishing_enabled'] and not resumed['automatic_operations_enabled']
        after = draft_snapshot()
        assert after['drafts'][:len(old_snapshot['drafts'])] == old_snapshot['drafts']
        assert after['assets'][:len(old_snapshot['assets'])] == old_snapshot['assets']
        assert sha(old_asset) == old_image_sha
        with factory() as db:
            counts = {model.__tablename__: db.scalar(select(func.count()).select_from(model))
                for model in [AiDraft, DraftAsset, PublishJob, AutoTask]}
        assert counts['ai_drafts'] == len(old_snapshot['drafts']) + 1
        assert counts['publish_jobs'] == counts['auto_tasks'] == 0
        image_records = []
        sheet = Image.new('RGB', (360 * len(assets), 520), '#E8EDF2')
        for i, asset in enumerate(assets):
            name = f'{i + 1:02d}-{expected_kinds[i]}.png'
            shutil.copy2(media / asset['local_path'], delivery / name)
            image = Image.open(delivery / name).convert('RGB'); image.thumbnail((348, 464))
            sheet.paste(image, (360 * i + 6, 6))
            ImageDraw.Draw(sheet).text((360 * i + 10, 480), f'{i + 1}: {expected_kinds[i]}', fill='#172F47')
            image_records.append({'file': name, 'sha256': sha(delivery / name), 'kind': expected_kinds[i],
                'asset_id': row['data']['images'][i]['id'], 'source_page': row['data']['images'][i].get('source_page'),
                'dimensions': [1080, 1440]})
        sheet.save(delivery / 'contact-sheet.png')
        (private / 'final-workflow.json').write_text(json.dumps(row, ensure_ascii=False, indent=2))

    protected_after = readonly_snapshot(real_db)
    assert protected_before == protected_after
    original_pdf_after = {'sha256': sha(real_pdf), 'size': real_pdf.stat().st_size,
                          'mtime_ns': real_pdf.stat().st_mtime_ns}
    assert original_pdf_before == original_pdf_after
    assert sha(fixture_pdf) == data['source']['sha256']
    assert denied_calls == []
    receipt = {'status': 'passed', 'scope': 'isolated_backend_real_local_render',
        'not_actual_user_approval': True, 'approval_identity': owner.username,
        'real_workflow_not_written': True, 'real_db_tables_unchanged': protected_after,
        'real_pdf_unchanged': original_pdf_after, 'source_run_id': 4,
        'source_row_version': original['row_version'], 'source_pdf_revision_id': 172,
        'source_file_id': 19901, 'source_sha256': data['source']['sha256'],
        'isolated_db': str(private / 'isolated.db'), 'isolated_storage': str(storage),
        'isolated_new_draft_id': new_id, 'counts': counts, 'image_count': len(image_records),
        'images': image_records, 'trace': trace,
        'copy_sha256': digest(data['copy']), 'visual_plan_sha256': digest(data['visual_plan']),
        'logo_sha256': flow.catalog()['brand']['logo_sha256'],
        'network_guard': 'Python socket and renderer Python/Node subprocesses deny network',
        'external_network_attempts': len(denied_calls), 'outbound_ai_or_xhs_calls': 0,
        'scheduler_started': False, 'watcher_started': False,
        'checked': ['manual stage gates', 'limited-source acknowledgement', 'cover PNG/SVG',
            'additive cover revision', 'historical image retrieval', 'whole set PNG/SVG',
            'real sample page', 'new draft export', 'source/copy/approval snapshot',
            'draft attachment order and SHA256', 'idempotent export', 'reload workflow',
            'old draft and asset unchanged', 'no publish or auto task', 'real PDF and DB unchanged'],
        'limitation': 'Backend/API acceptance only; simulated reviews do not approve this material for publication.'}
    (delivery / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    (delivery / 'README.txt').write_text('FNCE10002 本机隔离验收\n\n'
        '本目录图片由真实 PDF 和真实 Logo 经当前本机 SVG/PNG 排版器生成。\n'
        '审核为独立测试身份模拟，未写入真实工作记录、草稿工坊或发布任务。\n'
        '实际文案、方案和 PDF 版本来自 run 4 / file 19901 / revision 172。\n'
        'private 目录包含仅本机验收用的真实资料副本、隔离 DB 和工作流快照，不应公开。\n'
        '查看 receipt.json、contact-sheet.png 和 01-cover.png 等图片。\n')
    engine.dispose()
    print('LOCAL_REAL_RENDER_ACCEPTANCE=' + str(delivery / 'receipt.json'))
