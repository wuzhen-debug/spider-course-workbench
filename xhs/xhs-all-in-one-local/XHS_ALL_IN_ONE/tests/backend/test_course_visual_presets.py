"""Selectable template contracts and safe local branching, using isolated data."""
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
import pytest
from sqlalchemy import func, select

from test_course_visual_workflow import BASE, approve, copy_ready, research
from test_course_library import library
from backend.app.models import AiDraft, AutoTask, PublishJob
from backend.app.models.course_visual_workflow import CourseVisualWorkflow
from backend.app.services import course_visual_presets as presets
from backend.app.services import course_visual_workflow as flow


def png_bytes():
    stream = BytesIO(); Image.new('RGB', (108, 144), '#ffffff').save(stream, format='PNG')
    return stream.getvalue()


def preview_resource(tmp_path, monkeypatch):
    root = tmp_path / 'resources'; directory = root / 'template_previews'; directory.mkdir(parents=True)
    monkeypatch.setattr(presets, 'RESOURCES', root)
    image = directory / 'question-led.png'; image.write_bytes(png_bytes())
    manifest = directory / 'manifest.json'
    manifest.write_text(json.dumps({'question-led': {'sha256': hashlib.sha256(image.read_bytes()).hexdigest()}}))
    return image, manifest


def db_rows(factory):
    with factory() as db:
        return {row.id: {'user_id': row.user_id, 'file_id': row.file_id,
            'request_key': row.request_key, 'row_version': row.row_version,
            'data': deepcopy(row.data)} for row in db.scalars(select(CourseVisualWorkflow).order_by(CourseVisualWorkflow.id))}


def assert_no_publish_or_draft(factory):
    with factory() as db:
        for model in [AiDraft, PublishJob, AutoTask]:
            assert db.scalar(select(func.count()).select_from(model)) == 0


def seeded_assets(r):
    """A saved draft-like visual record with synthetic asset metadata only."""
    row = approve(r, copy_ready(r), 'copy'); c, headers, _, factory, *_ = r
    with factory() as db:
        record = db.get(CourseVisualWorkflow, row['id']); data = deepcopy(record.data)
        cover = {'id': 'old-cover', 'slot': 'cover', 'kind': 'cover', 'role': 'Old cover',
                 'path': 'fixture/cover.png', 'sha256': 'old-cover-sha', 'brief': {'title': '旧标题'}}
        sample = {'id': 'old-sample', 'slot': 'sample-0', 'kind': 'sample', 'role': 'Old sample',
                  'path': 'fixture/sample.png', 'sha256': 'old-sample-sha', 'source_page': 1, 'brief': {}}
        data['cover'] = cover; data['images'] = [deepcopy(cover), sample]
        data['page_overrides'] = {'cover': {'title': '旧标题'}}
        data['backgrounds'] = {'cover': {'request_key': 'old-background', 'path': 'fixture/background.png'}}
        data['background_requests'] = {'old-request': {'status': 'render_failed'}}
        data['design_report'] = {'reason': 'Historical design report'}
        data['display_treatment'] = 'Historical source treatment'
        for stage in ['cover', 'set']:
            data['approvals'][stage] = {'digest': flow.fingerprint(data, stage), 'at': 'fixture'}
        data['export'] = {'draft_id': 900001, 'at': '2026-01-01T00:00:00', 'snapshot': {}}
        record.data = data; db.commit()
    return c.get(f'{BASE}/{row["id"]}', headers=headers).json()


def test_catalog_has_three_previewable_templates_two_densities_and_three_copy_goals(research, tmp_path, monkeypatch):
    image, _ = preview_resource(tmp_path, monkeypatch)
    c, headers, other, factory, *_ = research; before = db_rows(factory)
    assert c.get(BASE + '/catalog').status_code == 401
    assert c.get(BASE + '/catalog', headers=other).status_code == 404
    result = c.get(BASE + '/catalog', headers=headers)
    assert result.status_code == 200, result.text
    options = result.json()
    assert [item['id'] for item in options['templates']] == ['magazine-a', 'question-led', 'decision-map', 'sample-led']
    assert options['default_template_id'] == 'magazine-a'
    assert {item['id'] for item in options['densities']} == {'compact', 'standard'}
    assert {item['id'] for item in options['writing_goals']} == {'student-question', 'method-save', 'sample-trial'}
    assert [item['id'] for item in options['templates'] if item['preview_available']] == ['question-led']
    assert options['brand']['name'] == '星途留学'
    assert image.is_file() and db_rows(factory) == before
    assert_no_publish_or_draft(factory)


def test_template_preview_requires_owner_and_matches_the_manifest(research, tmp_path, monkeypatch):
    image, _ = preview_resource(tmp_path, monkeypatch)
    c, headers, other, factory, *_ = research; path = BASE + '/template-previews/question-led'
    assert c.get(path).status_code == 401
    assert c.get(path, headers=other).status_code == 404
    response = c.get(path, headers=headers)
    assert response.status_code == 200 and response.content == image.read_bytes()
    assert response.headers['content-type'].startswith('image/png')
    assert c.get(BASE + '/template-previews/unknown-template', headers=headers).status_code == 404
    assert c.get(BASE + '/template-previews/decision-map', headers=headers).status_code == 404
    assert presets.preview_path('../question-led') is None
    assert presets.preview_path('/etc/passwd') is None
    assert presets.preview_path('question-led.png') is None
    assert_no_publish_or_draft(factory)


@pytest.mark.parametrize('problem', ['tampered_image', 'missing_manifest', 'wrong_sha', 'invalid_json', 'invalid_object', 'invalid_entry'])
def test_template_preview_rejects_missing_or_invalid_manifest_and_changed_images(research, tmp_path, monkeypatch, problem):
    image, manifest = preview_resource(tmp_path, monkeypatch)
    if problem == 'tampered_image': image.write_bytes(image.read_bytes() + b'changed')
    elif problem == 'missing_manifest': manifest.rename(manifest.with_name('preserved-original-manifest.json'))
    elif problem == 'wrong_sha': manifest.write_text(json.dumps({'question-led': {'sha256': 'wrong'}}))
    elif problem == 'invalid_json': manifest.write_text('{invalid')
    elif problem == 'invalid_object': manifest.write_text('[]')
    elif problem == 'invalid_entry': manifest.write_text('{"question-led":null}')
    c, headers, *_ = research
    assert c.get(BASE + '/template-previews/question-led', headers=headers).status_code == 409


@pytest.mark.parametrize('link_at', ['file', 'parent'])
def test_template_preview_does_not_serve_symlinks_outside_resource_root(research, tmp_path, monkeypatch, link_at):
    root = tmp_path / 'resources'; root.mkdir(); outside = tmp_path / 'outside'; outside.mkdir()
    image = outside / 'question-led.png'; image.write_bytes(png_bytes())
    (outside / 'manifest.json').write_text(json.dumps({'question-led': {'sha256': hashlib.sha256(image.read_bytes()).hexdigest()}}))
    if link_at == 'parent':
        (root / 'template_previews').symlink_to(outside, target_is_directory=True)
    else:
        directory = root / 'template_previews'; directory.mkdir()
        (directory / 'question-led.png').symlink_to(image)
        (directory / 'manifest.json').write_bytes((outside / 'manifest.json').read_bytes())
    monkeypatch.setattr(presets, 'RESOURCES', root)
    c, headers, *_ = research
    assert c.get(BASE + '/template-previews/question-led', headers=headers).status_code == 404


def test_quality_reports_concrete_gaps_not_a_quality_score_or_approval(research):
    c, headers, _, factory, *_ = research; row = copy_ready(research)
    before = db_rows(factory)
    result = c.get(f'{BASE}/{row["id"]}', headers=headers).json()
    quality = result['quality']
    assert {'visual_template', 'cover_only_sample'} <= {x['id'] for x in quality['checks']}
    assert all(x['status'] in {'attention', 'ready', 'manual'} for x in quality['checks'])
    assert any('不代替' in value for value in [quality['summary']])
    assert any('流量预测' in x['detail'] for x in quality['checks'])
    assert 'score' not in quality and 'passed' not in quality
    assert result['approved'] == {'copy': False, 'cover': False, 'set': False}
    assert db_rows(factory) == before


def test_fork_is_owned_versioned_idempotent_and_preserves_original_every_field(research):
    c, headers, other, factory, *_ = research; row = seeded_assets(research)
    before = db_rows(factory); original = before[row['id']]
    endpoint = f'{BASE}/{row["id"]}/fork'; payload = {'expected_version': row['row_version']}
    assert c.post(endpoint, json=payload).status_code == 401
    assert c.post(endpoint, headers=other, json=payload).status_code == 404
    assert c.post(endpoint, headers=headers, json={'expected_version': row['row_version'] - 1}).status_code == 409
    assert db_rows(factory) == before
    response = c.post(endpoint, headers=headers, json=payload)
    assert response.status_code == 200, response.text
    new = response.json(); assert new['id'] != row['id'] and new['file_id'] == row['file_id']
    assert new['data']['forked_from'] == {'run_id': row['id'], 'row_version': row['row_version'], 'revision': original['data']['revision']}
    for key in ['copy', 'source', 'brand', 'evidence', 'selected_source_ids', 'visual_plan']:
        assert new['data'][key] == row['data'][key]
    for key, expected in {'approvals': {}, 'cover': None, 'images': [], 'export': None, 'history': [],
                          'backgrounds': {}, 'background_requests': {}, 'page_overrides': {}}.items():
        assert new['data'][key] == expected
    assert 'operation' not in new['data'] and 'design_report' not in new['data'] and 'display_treatment' not in new['data']
    assert new['approved'] == {'copy': False, 'cover': False, 'set': False}
    assert not new['publishing_enabled'] and not new['automatic_operations_enabled']
    second = c.post(endpoint, headers=headers, json=payload)
    assert second.status_code == 200 and second.json()['id'] == new['id']
    current = db_rows(factory)
    assert len(current) == len(before) + 1 and current[row['id']] == original
    assert_no_publish_or_draft(factory)


def test_fork_waits_for_an_existing_generation_without_mutating_the_record(research):
    c, headers, _, factory, *_ = research; row = copy_ready(research)
    with factory() as db:
        record = db.get(CourseVisualWorkflow, row['id']); data = deepcopy(record.data)
        data['operation'] = {'status': 'generating', 'key': 'synthetic-in-flight'}; record.data = data; db.commit()
    before = db_rows(factory); version = before[row['id']]['row_version']
    response = c.post(f'{BASE}/{row["id"]}/fork', headers=headers, json={'expected_version': version})
    assert response.status_code == 409 and db_rows(factory) == before


@pytest.mark.parametrize('changes', [{'template_id': 'question-led'}, {'density': 'compact'}, {'template_id': 'sample-led', 'density': 'compact'}])
def test_changing_template_or_density_archives_old_visuals_and_preserves_copy_review(research, changes):
    c, headers, _, factory, *_ = research; row = seeded_assets(research)
    before = db_rows(factory)[row['id']]
    response = c.patch(f'{BASE}/{row["id"]}', headers=headers, json={
        'expected_version': row['row_version'], 'visual_plan': {**row['data']['visual_plan'], **changes}})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['approved']['copy'] and not result['approved']['cover'] and not result['approved']['set']
    assert result['data']['copy'] == row['data']['copy']
    assert result['data']['cover'] is None and result['data']['images'] == [] and result['data']['export'] is None
    assert result['data']['history'][-1]['cover']['id'] == 'old-cover'
    assert [a['id'] for a in result['data']['history'][-1]['images']] == ['old-cover', 'old-sample']
    with factory() as db:
        current = db.get(CourseVisualWorkflow, row['id'])
        assert current.data['approvals']['copy'] == before['data']['approvals']['copy']
        assert current.data['history'][-1]['backgrounds'] == before['data']['backgrounds']
        assert current.data['history'][-1]['export'] == before['data']['export']
    assert_no_publish_or_draft(factory)
