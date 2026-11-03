"""Selected A master: actual PNG generation, raw PDF pixels and legacy bytes.

Synthetic fixtures only; never touches a live DB, AI API or source course file.
"""
from copy import deepcopy
from pathlib import Path
import base64
import hashlib
import json
import os
import subprocess
import xml.etree.ElementTree as ET

from PIL import Image
import pypdfium2 as pdfium
import pytest

from backend.app.services import course_visual_svg as renderer
from backend.app.services.course_brands import resolve_brand
from backend.app.services.course_draft_images import HEADER_HEIGHT
from test_course_visual_templates_render import fixtures, render, NODE, ROOT, RENDERER
from test_course_visual_collage_render import synthetic_pdf


SVG = '{http://www.w3.org/2000/svg}'


def test_a_knowledge_cover_uses_current_course_without_a_pdf_sample(tmp_path, fixtures):
    fixtures['data']['visual_plan']['sample_pages'] = [999]
    fixtures['data']['source'].update(university='测试大学', course_code='TEST4321')
    directory, completed, result = render(tmp_path, fixtures, 'magazine-a',
        title='先理解口径\n再选方法', subtitle='用同一个条件区分两种不同含义。',
        nodes=['已知条件｜先写出题目给定的基数。', '目标条件｜再判断结果应该用什么口径。'])
    assert completed.returncode == 0, result
    assert Image.open(directory / 'cover.png').size == (1080, 1440)
    svg = (directory / 'cover.svg').read_text()
    assert 'TEST4321' in svg and '测试大学' in svg
    assert 'ACC1001' not in svg and '225' not in svg and '240' not in svg
    assert svg.count('<image ') == 1, 'Only the actual brand logo; no mandatory PDF thumbnail'
    assert result['files'][0]['template_id'] == 'magazine-a'


def test_a_method_changes_actual_copy_with_full_width_editorial_layout(tmp_path, fixtures):
    a, process, result = render(tmp_path, fixtures, 'magazine-a', kind='method',
        title='先看条件\n再做判断', subtitle='区分口径后再决定方法。',
        nodes=['明确目标｜先解释需要衡量什么，再识别对应条件。', '检查结果｜把结果代回原题，检查是否满足已知条件。'],
        text='方法来自当前选中的讲义，需要按当前题目核对。')
    assert process.returncode == 0, result
    b, process, result = render(tmp_path, fixtures, 'magazine-a', kind='method',
        title='新标题\n保留当前课程', subtitle='局部修改说明。', nodes=[], text='这是新的解释，必须写入新图片。')
    assert process.returncode == 0, result
    first = (a / 'method.svg').read_text(); second = (b / 'method.svg').read_text()
    assert '需要衡量什么' in first and 'font-size="34"' in first
    assert '这是新的解释' in second and '先解释需要衡量什么' not in second
    assert (a / 'method.png').read_bytes() != (b / 'method.png').read_bytes()


def test_a_raw_page_is_byte_exact_unadorned_and_ignores_ai_background(tmp_path, fixtures):
    fixtures['backgrounds'] = {'pdf-page': '/not-an-existing-ai-background.png'}
    directory, process, result = render(tmp_path, fixtures, 'magazine-a', kind='pdf-page',
        title='真实讲义样张', subtitle='这些元数据不应画在原页上', source_page=2, raw_pdf=True)
    assert process.returncode == 0, result
    original = Path(fixtures['source_images']['2'])
    assert (directory / 'pdf-page.png').read_bytes() == original.read_bytes()
    svg = ET.fromstring((directory / 'pdf-page.svg').read_text())
    assert svg.attrib['width'] == '700' and svg.attrib['height'] == '990'
    assert len(svg.findall(f'{SVG}image')) == 1
    assert len(svg.findall(f'{SVG}text')) == 0
    assert not svg.findall(f'{SVG}rect')
    assert svg.find(f'{SVG}image').attrib['href'] == 'data:image/png;base64,' + base64.b64encode(original.read_bytes()).decode()
    item = result['files'][0]
    assert item['raw_pdf'] is True and item['full_page'] is True
    assert item['width'] == 700 and item['height'] == 990


@pytest.mark.parametrize('number', [0, 57, 2.5])
def test_a_raw_page_rejects_invalid_source_without_output(tmp_path, fixtures, number):
    directory, process, result = render(tmp_path, fixtures, 'magazine-a', kind='pdf-page', source_page=number)
    assert process.returncode != 0 and '有效的物理页' in result['error']
    assert not (directory / 'pdf-page.png').exists()


def test_a_overflow_is_rejected_instead_of_shrinking_or_truncating(tmp_path, fixtures):
    directory, process, result = render(tmp_path, fixtures, 'magazine-a', kind='method',
        title='保留完整文案', subtitle='', nodes=[], text='需要完整保留的长句' * 100)
    assert process.returncode != 0 and '不会缩小字号' in result['error']
    assert not (directory / 'method.png').exists()


def test_a_python_adapter_renders_nine_original_pages_and_ignores_display_substitution(tmp_path, fixtures, monkeypatch):
    source = tmp_path / 'synthetic.pdf'; source.write_bytes(synthetic_pdf(10))
    data = deepcopy(fixtures['data']); data['source']['page_count'] = 10
    data['brand'] = resolve_brand('wenguo')
    data['source']['sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    data['visual_plan'].update(template_id='magazine-a', sample_pages=[999], cover_sample_page=999)
    pages = [{'slot': f'pdf-page-{i}', 'kind': 'pdf-page', 'title': '真实讲义样张', 'subtitle': '', 'text': '',
              'nodes': [], 'layout': 'full-page', 'source_page': n, 'raw_pdf': True,
              'template_id': 'magazine-a', 'density': 'standard'} for i, n in enumerate(range(2, 11))]
    monkeypatch.setattr(renderer, 'direct', lambda _data: {'pages': pages})
    # A raw preview must never reuse an older branded/modified approved display.
    spec = {'data': data, 'catalog': {'brand': {'logo': 'xingtu-logo.jpg'},
            'approved_display': {'source_sha256': data['source']['sha256'],
                                 'assets': {str(n): {'file': 'must-not-be-read.png', 'sha256': '0'*64} for n in range(2, 11)}}}}
    output = tmp_path / 'adapter'; output.mkdir(); config = output / 'spec.json'
    config.write_text(json.dumps(spec, ensure_ascii=False))
    before = source.read_bytes()
    with source.open('rb') as stream:
        result = renderer.render(stream.fileno(), config, output, 'pdf-pages')
    assert len(result['files']) == 9 and [f['source_page'] for f in result['files']] == list(range(2, 11))
    with pdfium.PdfDocument(source) as pdf:
        for item in result['files']:
            page = pdf[item['source_page'] - 1]
            bitmap = page.render(scale=1600 / page.get_width())
            actual = Image.open(output / item['file']).convert('RGB')
            fresh = bitmap.to_pil().convert('RGB')
            native=Image.open(output / f'input-{item["source_page"]}.png').convert('RGB')
            assert native.tobytes()==fresh.tobytes(), 'The exact full PDF raster is retained before adding a separate header and brand watermark'
            assert actual.size==(1200,round(1200*fresh.height/fresh.width)+HEADER_HEIGHT)
            assert actual.getpixel((0,HEADER_HEIGHT))==fresh.getpixel((0,0))
            assert actual.getpixel((0,actual.height-1))==fresh.getpixel((0,fresh.height-1))
            assert item['svg_sha256'] == hashlib.sha256((output / item['svg_file']).read_bytes()).hexdigest()
            bitmap.close(); page.close()
    assert source.read_bytes() == before


@pytest.mark.parametrize('template', ['legacy', 'question-led', 'decision-map', 'sample-led'])
def test_existing_templates_keep_exact_svg_png_bytes(tmp_path, fixtures, template):
    reference = os.environ.get('COURSE_VISUAL_MAGAZINE_BEFORE_RENDERER')
    if not reference or not Path(reference).is_file():
        pytest.skip('Provide pre-A renderer for local byte-level regression')
    for kind in ['cover', 'method', 'pdf-page']:
        options = {'source_page': 2, 'title': '真实讲义样张', 'subtitle': ''} if kind == 'pdf-page' else {}
        current, process, result = render(tmp_path, fixtures, template, kind=kind, **options)
        assert process.returncode == 0, result
        payload = current / 'input.json'
        old = tmp_path / f'old-{template}-{kind}'; old.mkdir()
        env = {**os.environ, 'NODE_OPTIONS': '--require ' + json.dumps(fixtures['_guard'])}
        process = subprocess.run([NODE, reference, str(payload), str(old)], cwd=ROOT,
                                 capture_output=True, text=True, timeout=30, env=env)
        assert process.returncode == 0, process.stdout
        assert (current / f'{kind}.svg').read_bytes() == (old / f'{kind}.svg').read_bytes()
        assert (current / f'{kind}.png').read_bytes() == (old / f'{kind}.png').read_bytes()
