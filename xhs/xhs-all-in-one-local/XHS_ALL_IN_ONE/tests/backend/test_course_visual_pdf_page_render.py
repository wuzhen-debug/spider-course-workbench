"""Eight separate, complete PDF pages; no business DB, API, model or network."""
from copy import deepcopy
from pathlib import Path
import base64
import hashlib
import json
import os
import xml.etree.ElementTree as ET

from PIL import Image
import pytest

from test_course_visual_collage_render import document, run_pdf, run_node, SVG


@pytest.fixture
def pdf_document(document):
    document['data'].pop('collage_plan', None)
    document['data']['pdf_page_plan'] = {'pages': list(range(2, 10))}
    document['data']['visual_plan']['method_text'] = ''
    return document


def test_pdf_pages_stage_produces_eight_single_pages_in_physical_order(tmp_path, pdf_document):
    output, result = run_pdf(tmp_path, pdf_document, 'pdf-pages')
    assert [item['slot'] for item in result['files']] == [f'pdf-page-{i}' for i in range(8)]
    assert [item['source_page'] for item in result['files']] == list(range(2, 10))
    assert all(item['kind'] == 'pdf-page' and item['full_page'] is True for item in result['files'])
    assert all('source_pages' not in item for item in result['files'])
    plan = json.loads((output / 'render-plan.json').read_text())
    assert set(range(2, 10)) <= {int(value) for value in plan['source_images']}
    for item in result['files']:
        assert Image.open(output / item['file']).size == (1080, 1440)
        assert item['svg_sha256'] == hashlib.sha256((output / item['svg_file']).read_bytes()).hexdigest()


def test_single_page_embeds_exact_high_resolution_original_without_crop_or_retyping(tmp_path, pdf_document):
    output, result = run_pdf(tmp_path, pdf_document, 'pdf-pages')
    plan = json.loads((output / 'render-plan.json').read_text())
    for item in result['files']:
        source = Path(plan['source_images'][str(item['source_page'])])
        raw = (output / item['svg_file']).read_text(); svg = ET.fromstring(raw)
        images = svg.findall(f'{SVG}image'); assert len(images) == 2, 'Exactly one source page and the real brand logo'
        page = images[0]
        assert page.attrib['href'] == 'data:image/png;base64,' + base64.b64encode(source.read_bytes()).decode()
        assert page.attrib['preserveAspectRatio'] == 'xMidYMid meet'
        width, height = Image.open(source).size
        assert max(width, height) >= 1500, 'Retain PDFium source pixels in the zoomable SVG'
        assert float(page.attrib['width']) / float(page.attrib['height']) == pytest.approx(width / height)
        x, y, w, h = [float(page.attrib[key]) for key in ['x', 'y', 'width', 'height']]
        assert 72 <= x <= x + w <= 1008 and 156 <= y <= y + h <= 1208
        assert w == pytest.approx(936) or h == pytest.approx(1052), 'A full source page uses the available width or height'
        assert 'clipPath' not in raw and '<mask' not in raw
        external = ''.join(''.join(node.itertext()) for node in svg.findall(f'{SVG}text'))
        assert '第' not in external and not any(char.isdigit() for char in external)
        assert 'SYNTHETIC PHYSICAL PDF PAGE' not in external, 'Source PDF content stays pixels rather than retyped text'
        watermark = next(node for node in svg.findall(f'{SVG}text') if node.attrib.get('opacity'))
        assert float(watermark.attrib['y']) - float(watermark.attrib['font-size']) > y + h
        assert float(watermark.attrib['y']) < float(images[1].attrib['y']), 'Watermark stays between source page and logo'


def test_set_stage_appends_eight_pages_after_existing_noncover_cards(tmp_path, pdf_document):
    _, result = run_pdf(tmp_path, pdf_document, 'set')
    assert [item['kind'] for item in result['files']] == ['sample', 'use', *['pdf-page'] * 8]


def test_original_single_pages_ignore_ai_background(tmp_path, pdf_document):
    a, first = run_pdf(tmp_path, pdf_document, 'pdf-pages')
    b, second = run_pdf(tmp_path, pdf_document, 'pdf-pages', backgrounds={'pdf-page-0': '/not-an-ai-background.png'})
    for x, y in zip(first['files'], second['files']):
        assert (a / x['file']).read_bytes() == (b / y['file']).read_bytes()
        assert (a / x['svg_file']).read_bytes() == (b / y['svg_file']).read_bytes()


def test_external_heading_edit_keeps_the_same_complete_source_page(tmp_path, pdf_document):
    output, _ = run_pdf(tmp_path, pdf_document, 'pdf-pages')
    payload = json.loads((output / 'render-plan.json').read_text())
    payload['pages'] = [{**payload['pages'][0], 'title': '核对原讲义内容', 'subtitle': '完整原页保留原比例与原有公式。'}]
    target, process, result = run_node(tmp_path, payload)
    assert process.returncode == 0, result
    svg = ET.fromstring((target / 'pdf-page-0.svg').read_text())
    source = Path(payload['source_images']['2'])
    assert svg.findall(f'{SVG}image')[0].attrib['href'] == 'data:image/png;base64,' + base64.b64encode(source.read_bytes()).decode()
    text = ''.join(''.join(node.itertext()) for node in svg.findall(f'{SVG}text'))
    assert '核对原讲义内容' in text and '完整原页保留原比例与原有公式。' in text


@pytest.mark.parametrize('source_page', [0, 10, 2.5])
def test_invalid_source_page_never_writes_output(tmp_path, pdf_document, source_page):
    output, _ = run_pdf(tmp_path, pdf_document, 'pdf-pages')
    payload = json.loads((output / 'render-plan.json').read_text())
    payload['pages'] = [{**payload['pages'][0], 'source_page': source_page}]
    target, process, result = run_node(tmp_path, payload)
    assert process.returncode != 0 and '有效的物理页' in result['error']
    assert not (target / 'pdf-page-0.png').exists()


@pytest.mark.parametrize('template', ['legacy', 'question-led', 'decision-map', 'sample-led', 'collage'])
def test_prior_templates_and_collage_keep_exact_png_svg_bytes(tmp_path, pdf_document, template):
    reference = os.getenv('COURSE_VISUAL_PDF_PAGE_BEFORE_RENDERER')
    if not reference or not Path(reference).is_file():
        pytest.skip('Provide the pre-single-page renderer for local byte-compatibility acceptance')
    data = deepcopy(pdf_document['data']); data.pop('pdf_page_plan', None)
    if template == 'collage':
        data['collage_plan'] = {'groups': [[2, 3, 4, 5], [6, 7, 8, 9]]}; stages = ['collage']
    else:
        data['visual_plan'].update(template_id=template, density='standard',
                                  method_text='先说明适用条件，再对照真实讲义。')
        stages = ['cover', 'set']
    for stage in stages:
        output, current = run_pdf(tmp_path, pdf_document, stage, data)
        payload = json.loads((output / 'render-plan.json').read_text())
        old_output, process, old = run_node(tmp_path, payload, Path(reference))
        assert process.returncode == 0, old
        assert [item['file'] for item in current['files']] == [item['file'] for item in old['files']]
        for item in current['files']:
            assert (output / item['file']).read_bytes() == (old_output / item['file']).read_bytes()
            assert (output / item['svg_file']).read_bytes() == (old_output / item['svg_file']).read_bytes()
