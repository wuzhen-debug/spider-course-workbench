"""PDF → 2x2 collage acceptance without a business DB or external requests."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import base64
import hashlib
import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

from PIL import Image
import pytest

from backend.app.services import course_visual_svg as renderer
from backend.app.services import course_visual_workflow as flow


ROOT = Path(__file__).resolve().parents[2]
NODE = shutil.which('node') or str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')
SVG = '{http://www.w3.org/2000/svg}'


def synthetic_pdf(count=9):
    font_id = 3 + count * 2
    kids = ' '.join(f'{3 + i * 2} 0 R' for i in range(count))
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               f'<< /Type /Pages /Kids [{kids}] /Count {count} >>'.encode()]
    for i in range(count):
        width, height = (792, 612) if i in {3, 6} else (612, 792)
        stream = f'BT /F1 24 Tf 60 {height-72} Td (SYNTHETIC PHYSICAL PDF PAGE {i + 1}) Tj ET'.encode()
        objects.extend([
            f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {4 + i * 2} 0 R >>'.encode(),
            b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream'])
    objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    data = b'%PDF-1.4\n'; offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data)); data += f'{number} 0 obj\n'.encode() + obj + b'\nendobj\n'
    start = len(data)
    data += f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode()
    data += b''.join(f'{offset:010} 00000 n \n'.encode() for offset in offsets)
    return data + f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


@pytest.fixture
def document(tmp_path, monkeypatch):
    source = tmp_path / 'synthetic-source.pdf'; source.write_bytes(synthetic_pdf())
    bundle = flow.catalog()
    data = flow.initial_data({'university': '墨尔本大学', 'course_code': 'FNCE10002',
        'filename': source.name, 'material_type': '期末复习讲义', 'page_count': 9,
        'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}, bundle)
    # This fixture exercises saved legacy collages. New-record defaults prefer
    # separate PDF pages; remove that mode explicitly before choosing collages.
    data.pop('pdf_page_plan', None)
    data['copy'].update(topic='阅读方法与真实样张', title='查看真实讲义样张', body='Synthetic test copy',
                        takeaway='核对已知条件，再阅读原讲义。')
    data['visual_plan'].update(sample_pages=[2], sample_instructions=['核对原讲义的条件说明。'],
        method_title='先核对条件', method_text='先说明适用条件，再对照真实讲义。',
        method_layout='editorial', method_nodes=[])
    data['collage_plan'] = {'groups': [[2, 3, 4, 5], [6, 7, 8, 9]]}
    guard = tmp_path / 'deny-network.cjs'
    guard.write_text('''const deny=()=>{throw new Error("External network forbidden in collage test")};
for(const name of ['http','https']){const m=require(name);m.request=deny;m.get=deny;}
const net=require('net');net.connect=deny;net.createConnection=deny;net.Socket.prototype.connect=deny;
globalThis.fetch=deny;
''')
    monkeypatch.setenv('NODE_OPTIONS', '--require ' + json.dumps(str(guard)))
    return {'source': source, 'bundle': bundle, 'data': data, 'guard': guard,
            'original': source.read_bytes()}


def run_pdf(tmp_path, fixture, stage='collage', data=None, backgrounds=None):
    output = tmp_path / f'render-{len(list(tmp_path.glob("render-*")))}'; output.mkdir()
    spec = {'data': data or fixture['data'], 'catalog': fixture['bundle'], 'backgrounds': backgrounds or {}}
    config = output / 'input.json'; config.write_text(json.dumps(spec, ensure_ascii=False))
    with fixture['source'].open('rb') as stream:
        rendered = renderer.render(stream.fileno(), config, output, stage)
    assert fixture['source'].read_bytes() == fixture['original']
    return output, rendered


def run_node(tmp_path, payload, script=None):
    output = tmp_path / f'node-{len(list(tmp_path.glob("node-*")))}'; output.mkdir()
    source = output / 'input.json'; source.write_text(json.dumps(payload, ensure_ascii=False))
    result = subprocess.run([NODE, str(script or renderer.__file__.replace('.py', '.mjs')), str(source), str(output)],
                            capture_output=True, text=True, cwd=ROOT, timeout=60)
    return output, result, json.loads(result.stdout)


def test_collage_stage_renders_only_two_collages_with_all_eight_source_pages(tmp_path, document):
    output, result = run_pdf(tmp_path, document)
    assert [item['slot'] for item in result['files']] == ['collage-0', 'collage-1']
    plan = json.loads((output / 'render-plan.json').read_text())
    assert set(range(2, 10)) <= {int(value) for value in plan['source_images']}
    for i, item in enumerate(result['files']):
        assert item['kind'] == 'collage' and item['full_pages'] is True
        assert item['source_pages'] == document['data']['collage_plan']['groups'][i]
        assert 'source_page' not in item and 'full_page' not in item
        assert Image.open(output / item['file']).size == (1080, 1440)
        assert item['svg_sha256'] == hashlib.sha256((output / item['svg_file']).read_bytes()).hexdigest()


def test_collage_embeds_exact_complete_images_without_cropping_or_extra_page_markers(tmp_path, document):
    output, result = run_pdf(tmp_path, document)
    plan = json.loads((output / 'render-plan.json').read_text())
    for item in result['files']:
        svg_text = (output / item['svg_file']).read_text(); svg = ET.fromstring(svg_text)
        images = svg.findall(f'{SVG}image')
        assert len(images) == 5, 'Four complete physical pages plus the real brand logo'
        assert 'clipPath' not in svg_text and '<mask' not in svg_text
        for number, image in zip(item['source_pages'], images[:4]):
            source = Path(plan['source_images'][str(number)])
            assert image.attrib['href'] == 'data:image/png;base64,' + base64.b64encode(source.read_bytes()).decode()
            assert image.attrib['preserveAspectRatio'] == 'xMidYMid meet'
            width, height = Image.open(source).size
            assert float(image.attrib['width']) / float(image.attrib['height']) == pytest.approx(width / height)
            x, y, w, h = [float(image.attrib[key]) for key in ['x', 'y', 'width', 'height']]
            assert 72 <= x <= x + w <= 1008 and 150 <= y <= y + h <= 1208
        external_text = ''.join(''.join(node.itertext()) for node in svg.findall(f'{SVG}text'))
        assert '第' not in external_text and not any(char.isdigit() for char in external_text)
        watermark = next(node for node in svg.findall(f'{SVG}text') if node.attrib.get('opacity'))
        top = float(watermark.attrib['y']) - float(watermark.attrib['font-size'])
        bottom = float(watermark.attrib['y'])
        assert all(bottom <= float(image.attrib['y']) or top >= float(image.attrib['y']) + float(image.attrib['height']) for image in images[:4])


def test_set_stage_includes_collages_after_other_noncover_pages(tmp_path, document):
    _, result = run_pdf(tmp_path, document, 'set')
    assert [item['kind'] for item in result['files']] == ['method', 'sample', 'use', 'collage', 'collage']


def test_collage_ignores_background_without_reading_or_embedding_it(tmp_path, document):
    a, first = run_pdf(tmp_path, document)
    b, second = run_pdf(tmp_path, document, backgrounds={'collage-0': '/not-a-real-ai-background.png'})
    for x, y in zip(first['files'], second['files']):
        assert (a / x['file']).read_bytes() == (b / y['file']).read_bytes()
        assert (a / x['svg_file']).read_bytes() == (b / y['svg_file']).read_bytes()


@pytest.mark.parametrize('source_pages', [[2, 2, 3, 4], [2, 3, 4], [1, 2, 3, 4], [2, 3, 4, 99], [2, 3, 4, 4.5]])
def test_invalid_collage_does_not_write_image(tmp_path, document, source_pages):
    output, _ = run_pdf(tmp_path, document)
    payload = json.loads((output / 'render-plan.json').read_text())
    payload['pages'] = [{**payload['pages'][0], 'source_pages': source_pages}]
    target, process, result = run_node(tmp_path, payload)
    assert process.returncode != 0 and '4张不同且有效' in result['error']
    assert not (target / 'collage-0.png').exists()


@pytest.mark.parametrize('template', ['legacy', 'question-led', 'decision-map', 'sample-led'])
def test_pre_collage_templates_are_byte_identical_to_saved_before_renderer(tmp_path, document, template):
    reference = os.getenv('COURSE_VISUAL_BEFORE_RENDERER')
    if not reference or not Path(reference).is_file():
        pytest.skip('Provide a local pre-change renderer path for byte compatibility acceptance')
    data = deepcopy(document['data']); data.pop('collage_plan', None)
    data['visual_plan'].update(template_id=template, density='standard')
    for stage in ['cover', 'set']:
        output, current = run_pdf(tmp_path, document, stage, data)
        payload = json.loads((output / 'render-plan.json').read_text())
        old_output, process, old = run_node(tmp_path, payload, Path(reference))
        assert process.returncode == 0, old
        assert current['files'] == old['files'] or [item['file'] for item in current['files']] == [item['file'] for item in old['files']]
        for item in current['files']:
            assert (output / item['file']).read_bytes() == (old_output / item['file']).read_bytes()
            assert (output / item['svg_file']).read_bytes() == (old_output / item['svg_file']).read_bytes()
