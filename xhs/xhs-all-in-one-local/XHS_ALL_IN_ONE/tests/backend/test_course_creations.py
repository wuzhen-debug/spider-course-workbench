"""Read-only recovery index: isolated local data, no live API or publication."""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from test_course_library import library, add_pdf, scan
from backend.app.models import AiDraft, User
from backend.app.models.course_library import CourseLibraryFile
from backend.app.models.course_library_draft import CourseLibraryDraft
from backend.app.models.course_research import CourseResearch, CourseResearchDraft
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.services import course_visual_workflow as flow

BASE = '/api/course-center/creations'
COURSE = '02墨大/FNCE10002'


@pytest.fixture
def creations_fixture(library, monkeypatch):
    c, h, other, factory, watcher, settings = library
    monkeypatch.setattr('requests.sessions.Session.request', lambda *a, **k: (_ for _ in ()).throw(AssertionError('External HTTP forbidden')))
    paths = [COURSE + '/期末复习讲义/FNCE10002_26S2_Final.pdf',
             '01USYD/FNCE10002/期末复习讲义/OtherSchool_FNCE10002.pdf',
             '02墨大/FNCE100020/期末复习讲义/OtherCode_FNCE100020.pdf']
    for i, path in enumerate(paths):
        add_pdf(watcher, path, label=f'SYNTHETIC CREATION {i}')
    scan(watcher)
    with factory() as db:
        owner = db.scalar(select(User).where(User.username == 'pdf-owner'))
        foreign = db.scalar(select(User).where(User.username == 'pdf-other'))
        files = {f.relative_path: f for f in db.scalars(select(CourseLibraryFile))}
        file = files[paths[0]]
        at = datetime(2026, 10, 30, 10)
        drafts = [AiDraft(user_id=owner.id, platform='xhs', title='FNCE10002讲义选题', body='Synthetic copy',
                          tags=[{'name': 'FNCE10002'}], created_at=at),
                  AiDraft(user_id=owner.id, platform='xhs', title='FNCE10002图文', body='Synthetic visual copy',
                          tags=[{'name': 'FNCE10002'}], created_at=at + timedelta(minutes=1))]
        db.add_all(drafts)
        study = CourseResearch(id=6, user_id=owner.id, context={'university': '墨尔本大学', 'course_code': 'FNCE10002',
            'library_directory': COURSE + '/期末复习讲义'}, created_at=at, updated_at=at)
        db.add(study); db.flush()
        source = {'university': '墨尔本大学', 'course_code': 'FNCE10002', 'filename': file.filename,
                  'relative_path': file.relative_path, 'revision_id': file.current_revision_id, 'sha256': 'a' * 64}
        research = CourseResearchDraft(id=6, user_id=owner.id, research_id=study.id, request_key=str(uuid4()),
            request_digest='fixture', title=drafts[0].title, body=drafts[0].body, tags=['FNCE10002'], prompt='',
            brief={'materials': [{'file_id': file.id, 'source': deepcopy(source)}]}, mode='ai', status='saved',
            draft_id=drafts[0].id, reviewed_at=at, created_at=at)
        state = flow.initial_data(source, {'brand': {'name': 'Synthetic'}, 'version': 1, 'skills': [], 'rules': '', 'contract_digest': 'fixture'})
        state['copy'] = {'topic': '学生复习问题', 'title': drafts[1].title, 'body': drafts[1].body, 'tags': ['FNCE10002'], 'takeaway': ''}
        state['cover'] = {'id': 'cover', 'sha256': 'b' * 64}
        state['images'] = [state['cover'], {'id': 'sample', 'sha256': 'c' * 64}]
        for stage in ('copy', 'cover', 'set'):
            state['approvals'][stage] = {'at': (at + timedelta(minutes=1)).isoformat(), 'digest': flow.fingerprint(state, stage)}
        state['export'] = {'draft_id': drafts[1].id, 'at': (at + timedelta(minutes=1)).isoformat()}
        visual = CourseVisualWorkflow(user_id=owner.id, file_id=file.id, request_key=str(uuid4()), data=state,
            created_at=at + timedelta(minutes=1), updated_at=at + timedelta(minutes=1))
        package = CourseLibraryDraft(user_id=owner.id, file_id=file.id, revision_id=file.current_revision_id,
            request_key=str(uuid4()), plan_digest='fixture', title='FNCE10002真实样张', body='Synthetic package', tags=[],
            source_snapshot=deepcopy(source), page_texts=[], images=[{'sha256': 'd' * 64}], generation_mode='local',
            created_at=at + timedelta(minutes=2))
        db.add_all([research, visual, package]); db.flush()
        for index, path in enumerate(paths[1:]):
            f = files[path]
            db.add(CourseVisualWorkflow(user_id=owner.id, file_id=f.id, request_key=str(uuid4()), data={
                'source': {'university': f.university, 'course_code': f.course_code, 'filename': f.filename,
                           'relative_path': f.relative_path, 'revision_id': f.current_revision_id},
                'copy': {'title': f'Other course {index}'}, 'images': [], 'cover': None},
                created_at=at - timedelta(days=1), updated_at=at - timedelta(days=1)))
        db.add(CourseResearch(id=7, user_id=foreign.id, context={'university': 'Private university', 'course_code': 'PRIVATE1000'}))
        db.flush()
        db.add(CourseResearchDraft(user_id=foreign.id, research_id=7, request_key=str(uuid4()), request_digest='private',
            title='PRIVATE DO NOT EXPOSE', body='private', tags=[], prompt='private', brief={}))
        db.commit()
        ids = {'file': file.id, 'foreign_school_file': files[paths[1]].id, 'research': research.id,
               'visual': visual.id, 'pdf': package.id, 'draft': drafts[0].id, 'visual_draft': drafts[1].id}
    return c, h, other, factory, ids


def get_all(fixture, **params):
    c, h, *_ = fixture
    result = c.get(BASE, headers=h, params={'limit': 100, **params})
    assert result.status_code == 200, result.text
    return result.json()


def test_three_paths_have_exact_resumable_urls_and_stage_metadata(creations_fixture):
    ids = creations_fixture[-1]
    data = get_all(creations_fixture, file_id=ids['file'])
    assert data['total'] == 3
    rows = {item['kind']: item for item in data['items']}
    assert list(rows) == ['pdf', 'visual', 'research']
    assert rows['research']['id'] == 'research:6'
    assert rows['research']['draft_available'] and rows['research']['status'] == 'draft_saved'
    assert rows['visual']['image_count'] == 2 and rows['visual']['draft_available']
    assert rows['pdf']['image_count'] == 1 and rows['pdf']['status'] == 'images_pending'
    research = parse_qs(urlsplit(rows['research']['primary_url']).query)
    assert research['research_id'] == ['6'] and research['research_draft_id'] == ['6']
    assert research['file_id'] == [str(ids['file'])]
    assert research['library_dir'] == [COURSE + '/期末复习讲义']
    assert parse_qs(urlsplit(rows['visual']['primary_url']).query)['run'] == [str(ids['visual'])]
    pdf = parse_qs(urlsplit(rows['pdf']['primary_url']).query)
    assert pdf['library_file_id'] == [str(ids['file'])] and pdf['package_id'] == [str(ids['pdf'])]
    assert all(item['primary_url'].startswith('/platforms/xhs/') for item in rows.values())
    assert all(parse_qs(urlsplit(item['source_url']).query)['library_file_id'] == [str(ids['file'])] for item in rows.values())
    assert all('source_path' not in item and 'body' not in item and 'prompt' not in item for item in rows.values())


def test_literal_directory_course_filters_search_and_pagination(creations_fixture):
    ids = creations_fixture[-1]
    matching = get_all(creations_fixture, directory=COURSE)
    assert matching['total'] == 3
    assert all(item['university'] == '墨尔本大学' and item['file_id'] == ids['file'] for item in matching['items'])
    assert get_all(creations_fixture, directory='01USYD/FNCE10002')['total'] == 1
    assert get_all(creations_fixture, directory='02墨大/FNCE100020')['total'] == 1
    assert get_all(creations_fixture, q='fnce10002讲义')['total'] == 1
    assert get_all(creations_fixture, q='unrelated')['total'] == 0
    c, h, *_ = creations_fixture
    first = c.get(BASE, headers=h, params={'limit': 2}).json()
    second = c.get(BASE, headers=h, params={'limit': 2, 'offset': 2}).json()
    assert first['total'] == second['total'] == 5
    assert first['limit'] == 2 and second['offset'] == 2
    assert not set(x['id'] for x in first['items']) & set(x['id'] for x in second['items'])


def test_owner_and_argument_guards(creations_fixture):
    c, h, other, *_ = creations_fixture
    assert c.get(BASE).status_code == 401
    assert c.get(BASE, headers=other).status_code == 404
    assert c.get(BASE, headers=h, params={'file_id': 9999999}).status_code == 404
    for params in ({'directory': '../outside'}, {'directory': '/absolute'}, {'limit': 101}, {'offset': -1}):
        assert c.get(BASE, headers=h, params=params).status_code == 422
    assert not any('PRIVATE' in item['title'] for item in get_all(creations_fixture)['items'])


@pytest.mark.parametrize('reuse', [False, True])
def test_missing_or_reused_draft_id_never_links_unrelated_copy(creations_fixture, reuse):
    _, _, _, factory, ids = creations_fixture
    with factory() as db:
        old = db.get(AiDraft, ids['draft'])
        if reuse:
            old.title = 'New unrelated course'
            old.body = 'This numeric id was reused'
            old.created_at += timedelta(days=1)
        else:
            db.delete(old)
        db.commit()
    item = next(x for x in get_all(creations_fixture, file_id=ids['file'])['items'] if x['id'] == 'research:6')
    assert item['draft_id'] == ids['draft'] and not item['draft_available']
    assert item['status'] == 'copy_saved'
    assert 'research_draft_id=6' in item['primary_url'] and '/drafts?' not in item['primary_url']


def test_new_identity_binding_allows_later_draft_edits_but_not_replacement(creations_fixture):
    _, _, _, factory, ids = creations_fixture
    with factory() as db:
        row = db.get(CourseResearchDraft, 6)
        draft = db.get(AiDraft, ids['draft'])
        row.brief = {**row.brief, 'draft_binding': {'draft_id': draft.id, 'user_id': draft.user_id, 'draft_created_at': draft.created_at.isoformat()}}
        draft.title = 'User edited the saved draft'
        db.commit()
    assert next(x for x in get_all(creations_fixture)['items'] if x['id'] == 'research:6')['draft_available']
    with factory() as db:
        draft = db.get(AiDraft, ids['draft']); draft.created_at += timedelta(days=1); db.commit()
    assert not next(x for x in get_all(creations_fixture)['items'] if x['id'] == 'research:6')['draft_available']


def test_read_listing_changes_no_database_rows_or_pdf_bytes(creations_fixture):
    c, h, _, factory, ids = creations_fixture
    def snapshot():
        with factory() as db:
            names = db.execute(text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")).scalars().all()
            return {name: db.execute(text('SELECT * FROM "' + name + '" ORDER BY rowid')).fetchall() for name in names}
    before = snapshot()
    # All files here are disposable fixture PDFs, never the user's archive.
    from backend.app.api.course_library import get_settings
    root = Path(get_settings().course_library_root)
    source_bytes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*.pdf')}
    for query in ({}, {'q': 'FNCE10002'}, {'file_id': ids['file']}, {'directory': COURSE}):
        assert c.get(BASE, headers=h, params=query).status_code == 200
    assert snapshot() == before
    assert {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*.pdf')} == source_bytes


@pytest.mark.parametrize(('state', 'expected'), [
    ('set_reviewed', 'images_reviewed'), ('set_pending', 'images_pending'),
    ('cover_reviewed', 'cover_reviewed'), ('cover_pending', 'cover_pending'),
    ('copy_reviewed', 'visual_planned'), ('processing', 'processing'), ('failed', 'failed'),
])
def test_visual_status_keeps_review_stages_distinct(creations_fixture, state, expected):
    _, _, _, factory, ids = creations_fixture
    with factory() as db:
        row = db.get(CourseVisualWorkflow, ids['visual'])
        data = deepcopy(row.data); data['export'] = None
        if state in {'cover_reviewed', 'cover_pending', 'copy_reviewed'}:
            data['images'] = []
        if state == 'copy_reviewed':
            data['cover'] = None
        if state.endswith('_pending'):
            data['approvals'] = {}
        else:
            for stage in ('copy', 'cover', 'set'):
                data['approvals'][stage] = {'at': '2026-10-30T10:00:00', 'digest': flow.fingerprint(data, stage)}
        if state in {'processing', 'failed'}:
            data['operation'] = {'status': 'generating' if state == 'processing' else 'failed'}
        row.data = data; db.commit()
    item = next(x for x in get_all(creations_fixture)['items'] if x['kind'] == 'visual' and x['id'] == f"visual:{ids['visual']}")
    assert item['status'] == expected
