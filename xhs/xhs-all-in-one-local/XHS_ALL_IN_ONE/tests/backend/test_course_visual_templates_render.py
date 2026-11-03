"""Real deterministic renderer checks with synthetic local image fixtures only.

No business DB, course PDF, model, approval or workflow API is accessed.
"""
from pathlib import Path
import base64
import json
import os
import shutil
import subprocess

from PIL import Image, ImageDraw
import pytest


ROOT = Path(__file__).resolve().parents[2]
RENDERER = ROOT / 'backend/app/services/course_visual_svg.mjs'
NODE = shutil.which('node') or str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')


@pytest.fixture
def fixtures(tmp_path):
    assets = {}
    for number in [1, 2]:
        path = tmp_path / f'source-{number}.png'
        image = Image.new('RGB', (700, 990), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((34, 35, 666, 42), fill='#0755A2')
        draw.text((45, 70), f'SYNTHETIC SOURCE PAGE {number}', fill='#172F47')
        if number == 2:
            for y in range(120, 910, 45):
                draw.rectangle((45, y, 600 if y % 2 else 650, y + 6), fill='#63798E')
        image.save(path)
        assets[str(number)] = str(path)
    logo = tmp_path / 'logo.png'
    Image.new('RGB', (150, 150), '#0755A2').save(logo)
    guard = tmp_path / 'deny-network.cjs'
    guard.write_text('''const deny=()=>{throw new Error("Network forbidden in renderer test")};
for(const name of ['http','https']){const m=require(name);m.request=deny;m.get=deny;}
const net=require('net');net.connect=deny;net.createConnection=deny;net.Socket.prototype.connect=deny;
globalThis.fetch=deny;
''')
    return {'data': {'source': {'university': '墨尔本大学', 'course_code': 'FNCE10002',
                    'page_count': 56, 'material_type': '期末复习讲义'},
                    'visual_plan': {'sample_pages': [2]}},
            'source_images': assets, 'logo': str(logo), 'backgrounds': {}, '_guard': str(guard)}


def render(tmp_path, fixtures, template=None, kind='cover', **changes):
    directory = tmp_path / f'render-{len(list(tmp_path.glob("render-*")))}'
    directory.mkdir()
    page = {'slot': kind, 'kind': kind, 'title': '先看条件\n再选公式', 'subtitle': '核对问题条件，再对照真实讲义中的讲解。',
            'text': '先看真实内容，再核对是否符合自己的学习需要。', 'nodes': [], 'layout': 'product-hero'}
    if kind == 'use':
        page.update(title='核对需要\n再选资料', nodes=['先看真实样张', '对照当前课件', '独立练习后核对'])
    if template is not None:
        page.update(template_id=template, density='standard')
    page.update(changes)
    payload = {k: v for k, v in fixtures.items() if not k.startswith('_')}
    payload['pages'] = [page]
    source = directory / 'input.json'
    source.write_text(json.dumps(payload, ensure_ascii=False))
    env = {**os.environ, 'NODE_OPTIONS': '--require ' + json.dumps(fixtures['_guard'])}
    completed = subprocess.run([NODE, str(RENDERER), str(source), str(directory)],
                               cwd=ROOT, capture_output=True, text=True, timeout=30, env=env)
    return directory, completed, json.loads(completed.stdout)


def image_uri(path):
    return 'data:image/png;base64,' + base64.b64encode(Path(path).read_bytes()).decode()


def test_three_cover_templates_have_distinct_real_layouts(tmp_path, fixtures):
    pngs = []; svgs = []
    for template in ['question-led', 'decision-map', 'sample-led']:
        directory, completed, result = render(tmp_path, fixtures, template)
        assert completed.returncode == 0, result
        assert result['files'][0]['template_id'] == template
        assert Image.open(directory / 'cover.png').size == (1080, 1440)
        svg = (directory / 'cover.svg').read_text()
        assert svg.count(image_uri(fixtures['source_images']['2'])) == 1
        assert image_uri(fixtures['logo']) in svg
        assert '第1页' not in svg and '1 / 3' not in svg
        pngs.append((directory / 'cover.png').read_bytes()); svgs.append(svg)
    assert len(set(pngs)) == 3 and len(set(svgs)) == 3


@pytest.mark.parametrize('template', ['question-led', 'decision-map', 'sample-led'])
def test_new_usage_page_uses_content_page_and_supplied_copy(tmp_path, fixtures, template):
    directory, completed, result = render(tmp_path, fixtures, template, kind='use')
    assert completed.returncode == 0, result
    svg = (directory / 'use.svg').read_text()
    assert image_uri(fixtures['source_images']['2']) in svg
    assert image_uri(fixtures['source_images']['1']) not in svg
    assert '先看真实内容，再核对是否符合自己的学习需要。' in svg
    assert '复习一章，走完这条路线' not in svg
    assert '先了解，再决定是否购买' not in svg


def test_legacy_missing_and_explicit_template_are_identical(tmp_path, fixtures):
    a, p, r = render(tmp_path, fixtures)
    assert p.returncode == 0, r
    b, p, r = render(tmp_path, fixtures, 'legacy')
    assert p.returncode == 0, r
    assert (a / 'cover.svg').read_bytes() == (b / 'cover.svg').read_bytes()
    assert (a / 'cover.png').read_bytes() == (b / 'cover.png').read_bytes()
    assert 'template_id' not in r['files'][0]


def test_cover_only_selection_fails_instead_of_repeating_cover_as_content(tmp_path, fixtures):
    fixtures['data']['visual_plan']['sample_pages'] = [1]
    directory, completed, result = render(tmp_path, fixtures, 'sample-led')
    assert completed.returncode != 0
    assert '正文样页' in result['error']
    assert not (directory / 'cover.png').exists()


@pytest.mark.parametrize('kind', ['cover', 'use'])
def test_explicit_content_reference_can_be_outside_old_sample_selection(tmp_path, fixtures, kind):
    fixtures['data']['visual_plan'].update(sample_pages=[1], cover_sample_page=2)
    directory, completed, result = render(tmp_path, fixtures, 'sample-led', kind=kind)
    assert completed.returncode == 0, result
    assert image_uri(fixtures['source_images']['2']) in (directory / f'{kind}.svg').read_text()


def test_invalid_explicit_content_reference_never_falls_back_to_another_page(tmp_path, fixtures):
    fixtures['data']['visual_plan']['cover_sample_page'] = 1
    directory, completed, result = render(tmp_path, fixtures, 'sample-led')
    assert completed.returncode != 0 and '封面正文样张' in result['error']
    assert not (directory / 'cover.png').exists()


def test_null_content_reference_retains_legacy_selection_bytes(tmp_path, fixtures):
    original, completed, result = render(tmp_path, fixtures, 'decision-map')
    assert completed.returncode == 0, result
    fixtures['data']['visual_plan']['cover_sample_page'] = None
    other, completed, result = render(tmp_path, fixtures, 'decision-map')
    assert completed.returncode == 0, result
    assert (original / 'cover.svg').read_bytes() == (other / 'cover.svg').read_bytes()
    assert (original / 'cover.png').read_bytes() == (other / 'cover.png').read_bytes()


def test_overflow_is_rejected_without_shrinking_or_writing_output(tmp_path, fixtures):
    directory, completed, result = render(tmp_path, fixtures, 'question-led', title='不可读的超长标题' * 50)
    assert completed.returncode != 0
    assert '不会缩小字体硬塞' in result['error']
    assert not (directory / 'cover.png').exists()


def test_decision_nodes_keep_authored_information_and_readable_font(tmp_path, fixtures):
    directory, completed, result = render(tmp_path, fixtures, 'decision-map',
        nodes=['先看条件｜核对时间点与现金流', '再看目标｜分清现值与终值', '最后核算｜对照讲义中的说明'])
    assert completed.returncode == 0, result
    svg = (directory / 'cover.svg').read_text()
    assert '核对时间点与现金流' in svg
    assert 'font-size="36"' in svg
    assert 'font-size="29"' not in svg


def test_modern_method_nodes_have_room_for_complete_explanation(tmp_path, fixtures):
    directory, completed, result = render(tmp_path, fixtures, 'decision-map', kind='method',
        layout='flow', text='按条件核对所需方法，完成后回看讲义解释。',
        nodes=['先核对｜时间点与已知条件', '再判断｜现值或终值'])
    assert completed.returncode == 0, result
    assert 'font-size="36"' in (directory / 'method.svg').read_text()
