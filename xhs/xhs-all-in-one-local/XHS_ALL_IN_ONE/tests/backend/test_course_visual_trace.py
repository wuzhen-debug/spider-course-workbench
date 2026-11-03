"""Small private provenance records without source/prompt/credential duplication."""
from copy import deepcopy
import json

from backend.app.services import course_visual_trace as trace


def data():
    return {'rules': {'version': 'test-version', 'skills': [
        {'skill': 'aussie-course-xhs', 'file': '/private/source', 'sha256': 'a' * 64},
        {'skill': 'xhs-visual-director', 'sha256': 'b' * 64}]},
        'source': {'revision_id': 364, 'sha256': 'c' * 64,
                   'relative_path': '/private/course.pdf'},
        'selected_source_ids': ['source-1'], 'approvals': {},
        'copy': {'body': 'private course text'}, 'images': [], 'export': None}


def test_trace_records_provenance_with_hashes_only():
    d = data()
    original = deepcopy(d)
    entry = trace.record(d, 'copy', 'configured-text-model',
        model={'name': 'Provider', 'model_name': 'deepseek-chat',
               'destination': 'https://user:password@example.com:443/v1?api_key=secret#private',
               'api_key': 'do-not-store', 'secret': 'another-secret'},
        inputs={'prompt': 'private input prompt'}, outputs={'body': 'private output'},
        scope='Approved excerpt to configured text model')
    assert entry['model'] == {'name': 'Provider', 'model_name': 'deepseek-chat',
                              'destination': 'https://example.com:443'}
    assert entry['source'] == {'revision_id': 364, 'sha256': 'c' * 64}
    assert entry['skills'][0] == {'skill': 'aussie-course-xhs', 'sha256': 'a' * 64}
    assert entry['selected_source_ids'] == ['source-1']
    assert len(entry['inputs_digest']) == len(entry['outputs_digest']) == 64
    rendered = json.dumps(entry)
    for private in ['private input prompt', 'private output', '/private/source',
                    '/private/course.pdf', 'password', 'api_key', 'do-not-store', 'another-secret']:
        assert private not in rendered
    assert {k: v for k, v in d.items() if k != 'production_trace'} == original


def test_trace_retains_failed_steps_and_copies_identifiers():
    d = data()
    failed = trace.record(d, 'images', 'local-renderer', inputs={'a': 1, 'b': 2},
                          status='failed')
    completed = trace.record(d, 'images', 'local-renderer', inputs={'b': 2, 'a': 1},
                             outputs={'images': ['image-sha']})
    d['selected_source_ids'].append('later')
    d['rules']['skills'][0]['sha256'] = 'changed'
    assert d['production_trace'] == [failed, completed]
    assert failed['status'] == 'failed' and completed['status'] == 'completed'
    assert failed['inputs_digest'] == completed['inputs_digest']
    assert failed['outputs_digest'] is None
    assert failed['selected_source_ids'] == ['source-1']
    assert failed['skills'][0]['sha256'] == 'a' * 64
    assert failed['model'] is None


def test_trace_accepts_legacy_records_and_rejects_unusable_destinations():
    d = {}
    one = trace.record(d, 'images', 'local-renderer', model={'destination': 'not-a-url'})
    two = trace.record(d, 'images', 'local-renderer', model={'destination': 'file:///private/key'})
    three = trace.record(d, 'images', 'local-renderer', model={'destination': 'https://host:invalid'})
    assert all(item['model'] is None for item in [one, two, three])
    assert one['source'] == {} and one['skills'] == []
    assert len(d['production_trace']) == 3
