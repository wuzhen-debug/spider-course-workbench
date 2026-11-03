"""Full-set layout regression using the saved FNCE10002 candidate's exact text.

Only the editorial JSON is read. PDF/page images and logo are synthetic fixtures;
no business database, workflow API, source PDF, or model is accessed. Missing
local delivery evidence skips these opt-in-content regressions on other installs.
"""
from copy import deepcopy
from pathlib import Path
import base64
import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw
import pytest

from backend.app.services.course_visual_workflow import direct


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT.parent / 'delivery/20261030-templates-editorial-upgrade/candidate.json'
RENDERER = ROOT / 'backend/app/services/course_visual_svg.mjs'
NODE = shutil.which('node') or str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')
pytestmark = pytest.mark.skipif(not CANDIDATE.is_file(), reason='Local FNCE candidate evidence is not installed')


@pytest.fixture
def full_set_fixture(tmp_path):
    candidate = json.loads(CANDIDATE.read_text())
    source_images = {}
    for number in [1, *candidate['visual_plan']['sample_pages']]:
        path = tmp_path / f'synthetic-page-{number}.png'
        image = Image.new('RGB', (700, 990), 'white')
        draw = ImageDraw.Draw(image)
        draw.text((36, 40), f'SYNTHETIC PAGE {number} - TEST FIXTURE ONLY', fill='#172F47')
        for y in range(120, 900, 43):
            draw.rectangle((40, y, 620, y + 5), fill='#63798E')
        image.save(path); source_images[str(number)] = str(path)
    logo = tmp_path / 'synthetic-logo.png'
    Image.new('RGB', (150, 150), '#0755A2').save(logo)
    guard = tmp_path / 'deny-network.cjs'
    guard.write_text('''const deny=()=>{throw new Error("External network forbidden in layout regression")};
for(const name of ['http','https']){const m=require(name);m.request=deny;m.get=deny;}
const net=require('net');net.connect=deny;net.createConnection=deny;net.Socket.prototype.connect=deny;
globalThis.fetch=deny;
''')
    data = {'source': {'university': '墨尔本大学', 'course_code': 'FNCE10002',
            'page_count': 56, 'material_type': '期末复习讲义'},
            'copy': deepcopy(candidate['copy']), 'visual_plan': deepcopy(candidate['visual_plan']),
            'rules': {'digest': 'isolated-full-set-layout-regression'}}
    return {'candidate': candidate, 'data': data, 'source_images': source_images,
            'logo': str(logo), 'guard': guard}


def render_pages(tmp_path, fixture, data=None, pages=None):
    data = data or fixture['data']
    if pages is None:
        pages = [p for p in direct(data)['pages'] if p['kind'] != 'cover']
    output = tmp_path / f'render-{len(list(tmp_path.glob("render-*")))}'; output.mkdir()
    payload = {'data': data, 'pages': pages, 'source_images': fixture['source_images'],
               'logo': fixture['logo'], 'backgrounds': {}}
    source = output / 'input.json'; source.write_text(json.dumps(payload, ensure_ascii=False))
    environment = {**os.environ, 'NODE_OPTIONS': '--require ' + json.dumps(str(fixture['guard']))}
    result = subprocess.run([NODE, str(RENDERER), str(source), str(output)], cwd=ROOT,
                            capture_output=True, text=True, timeout=30, env=environment)
    return output, result, json.loads(result.stdout)


def normalized(value):
    return ''.join(str(value).split())


def svg_text(path):
    root = ET.fromstring(path.read_text())
    return ''.join(''.join(node.itertext()) for node in root.findall('{http://www.w3.org/2000/svg}text'))


@pytest.mark.parametrize('template', ['decision-map', 'question-led', 'sample-led'])
def test_saved_three_node_candidate_renders_entire_set_without_changing_copy(tmp_path, full_set_fixture, template):
    data = deepcopy(full_set_fixture['data']); data['visual_plan']['template_id'] = template
    exact_input = deepcopy(data)
    output, result, rendered = render_pages(tmp_path, full_set_fixture, data)
    assert result.returncode == 0, rendered
    assert data == exact_input, 'The renderer must not abbreviate or rewrite the authored input'
    assert [item['slot'] for item in rendered['files']] == ['method', 'sample-0', 'sample-1', 'use']
    for item in rendered['files']:
        assert Image.open(output / item['file']).size == (1080, 1440)
        assert (output / item['svg_file']).is_file()
    method = normalized(svg_text(output / 'method.svg'))
    assert normalized(data['visual_plan']['method_text']) in method
    for node in data['visual_plan']['method_nodes']:
        heading, description = node.split('｜', 1)
        assert normalized(heading) in method and normalized(description) in method
    for i, number in enumerate(data['visual_plan']['sample_pages']):
        svg = (output / f'sample-{i}.svg').read_text()
        assert normalized(data['visual_plan']['sample_instructions'][i]) in normalized(svg_text(output / f'sample-{i}.svg'))
        exact_image = 'data:image/png;base64,' + base64.b64encode(Path(full_set_fixture['source_images'][str(number)]).read_bytes()).decode()
        assert exact_image in svg, 'Complete source image must remain embedded, not retyped or cropped'
    use = normalized(svg_text(output / 'use.svg'))
    assert normalized(data['visual_plan']['cta']) in use
    assert normalized(data['copy']['topic']) in use
    assert all(normalized(step) in use for step in data['visual_plan']['usage_steps'])


def test_modern_sample_retains_wrapped_external_caption_and_complete_source(tmp_path, full_set_fixture):
    data = deepcopy(full_set_fixture['data'])
    caption = '先核对现金流处理，再把项目风险和融资结构等适用条件写进判断，最后对照这份真实讲义中的说明。'
    data['visual_plan']['sample_instructions'][0] = caption
    pages = [p for p in direct(data)['pages'] if p['slot'] == 'sample-0']
    output, result, rendered = render_pages(tmp_path, full_set_fixture, data, pages)
    assert result.returncode == 0, rendered
    assert normalized(caption) in normalized(svg_text(output / 'sample-0.svg'))
    assert Image.open(output / 'sample-0.png').size == (1080, 1440)


def test_modern_use_handles_three_line_topic_without_losing_steps_or_cta(tmp_path, full_set_fixture):
    data = deepcopy(full_set_fixture['data'])
    data['copy']['topic'] = '做项目估值时先核对风险与融资结构等适用条件再代入折现率计算项目价值'
    pages = [p for p in direct(data)['pages'] if p['slot'] == 'use']
    output, result, rendered = render_pages(tmp_path, full_set_fixture, data, pages)
    assert result.returncode == 0, rendered
    text = normalized(svg_text(output / 'use.svg'))
    assert normalized(data['copy']['topic']) in text
    assert all(normalized(step) in text for step in data['visual_plan']['usage_steps'])
    assert normalized(data['visual_plan']['cta']) in text


RUN7_TAKEAWAY = '遇到案例题时，先用“主体—层次—证据”定位，再选理论；作答后逐条对照材料中的具体行为，删去没有证据支撑的理论点。'


@pytest.mark.parametrize('template', ['decision-map', 'question-led', 'sample-led'])
def test_real_long_takeaway_renders_cover_and_entire_set_without_abbreviation(tmp_path, full_set_fixture, template):
    """The actual run7 copy hit a one-line-only cover region before this fix."""
    data = deepcopy(full_set_fixture['data'])
    data['source'].update(university='昆士兰大学', course_code='MGTS1601')
    data['copy'].update(takeaway=RUN7_TAKEAWAY, title='MGTS1601案例题别堆理论', topic='案例题先定位，再选理论')
    data['visual_plan'].update(template_id=template, cover_lines=['案例题先定位', '再选理论'],
                              method_title='先找证据，再选理论', method_text='先定位对象和层次，再对照材料选理论。',
                              method_nodes=['定位｜找主体与层次', '选用｜核对理论条件', '对照｜保留材料证据'])
    # Cover and method must both cope with the same full authored takeaway;
    # direct's legacy method summary remains unchanged outside this fixture.
    pages = direct(data)['pages']
    for page in pages:
        if page['kind'] == 'method': page['subtitle'] = RUN7_TAKEAWAY
    before = deepcopy(data); before_pages = deepcopy(pages)
    output, result, rendered = render_pages(tmp_path, full_set_fixture, data, pages)
    assert result.returncode == 0, rendered
    assert data == before and pages == before_pages
    for item in rendered['files']:
        assert Image.open(output / item['file']).size == (1080, 1440)
    assert normalized(RUN7_TAKEAWAY) in normalized(svg_text(output / 'cover.svg'))
    assert normalized(RUN7_TAKEAWAY) in normalized(svg_text(output / 'method.svg'))
    root = ET.fromstring((output / 'cover.svg').read_text())
    nodes = root.findall('{http://www.w3.org/2000/svg}text')
    x, top, bottom, font = {'question-led': (76, 518, 610, 34), 'decision-map': (76, 455, 539, 32),
                            'sample-led': (72, 607, 999, 36)}[template]
    subtitle_nodes = [node for node in nodes if float(node.get('x')) == x and top <= float(node.get('y')) <= bottom]
    assert subtitle_nodes and all(float(node.get('font-size')) == font for node in subtitle_nodes)
    source = full_set_fixture['source_images'][str(data['visual_plan']['sample_pages'][0])]
    assert 'data:image/png;base64,' + base64.b64encode(Path(source).read_bytes()).decode() in (output / 'cover.svg').read_text()


@pytest.mark.parametrize('template', ['decision-map', 'question-led', 'sample-led'])
def test_short_cover_retains_original_coordinate_and_font_contract(tmp_path, full_set_fixture, template):
    data = deepcopy(full_set_fixture['data']); data['visual_plan']['template_id'] = template
    data['copy']['takeaway'] = '先核对条件，再独立练习'
    pages = [p for p in direct(data)['pages'] if p['kind'] == 'cover']
    output, result, rendered = render_pages(tmp_path, full_set_fixture, data, pages)
    assert result.returncode == 0, rendered
    svg = (output / 'cover.svg').read_text()
    if template == 'decision-map':
        assert 'x="72" y="507" width="422" height="198"' in svg
        assert 'x="548" y="532"' in svg
        assert 'font-size="32"' in svg
    elif template == 'question-led':
        assert 'x="72" y="617" width="8" height="112"' in svg
        assert 'x="504" y="583"' in svg
        assert 'font-size="34"' in svg
    else:
        assert 'x="72" y="980"' in svg
        assert 'x="474" y="477"' in svg
        assert 'font-size="36"' in svg
