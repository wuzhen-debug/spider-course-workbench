"""Whole-page typography fits, with original text, type sizes and prior A bytes."""
from pathlib import Path
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET

from PIL import Image
import pytest
from test_course_visual_templates_render import fixtures, render, NODE, ROOT

SVG = '{http://www.w3.org/2000/svg}'
normalize = lambda value: re.sub(r'\s+', '', value)


def retained(directory, page):
    root = ET.parse(directory / 'method.svg').getroot()
    texts = root.findall(f'.//{SVG}text')
    # School/course stay prominent; a real logo is an image.
    assert float(texts[0].attrib['font-size']) >= 40
    assert float(texts[1].attrib['font-size']) >= 40
    actual = ''.join(''.join(t.itertext()) for t in texts[2:])
    expected = page['title'] + page['subtitle'] + ''.join(n.replace('｜', '') for n in page['nodes']) + page['text']
    assert normalize(actual) == normalize(expected)
    assert min(float(t.attrib['font-size']) for t in texts[2:]) >= 34
    assert max(float(t.attrib['y']) for t in texts) <= 1208
    assert Image.open(directory / 'method.png').size == (1080, 1440)


@pytest.mark.parametrize('node_count', [2, 3, 4, 5])
def test_nodes_plus_full_paragraph_reflow_without_losing_text_or_reducing_fonts(tmp_path, fixtures, node_count):
    page = {'title': '先确认条件，再独立练习',
            'subtitle': '能按给定数据说明四项变化，核对每一步的依据，再把检查结果连接到独立练习。',
            'nodes': ['先确认当前对象｜先明确题目研究对象，再把已知条件整理成清单，核对每个条件是否齐全',
                      '单列已知条件｜每一步判断都要写出使用依据，避免把题目要求与已知数据混淆',
                      '明确推理方向｜判断条件与结论的关系，再写出独立解释',
                      '回代检查结果｜把结果代回题目中的每个条件，核对是否成立',
                      '再做迁移练习｜更换条件后重新解释依据，不照抄上一题的结论'][:node_count],
            'text': '先读清题目需要解释的问题，再把每一步使用的条件写完整。核对结果时保留中间过程，并说明为什么这样判断。' * (2 if node_count == 5 else 3)}
    directory, process, result = render(tmp_path, fixtures, 'magazine-a', kind='method', **page)
    assert process.returncode == 0, result
    item = result['files'][0]
    if node_count >= 3:
        assert item['layout_fit']['profile'] != 'original'
    assert item['layout_fit']['content_bottom'] <= 1208
    assert item['layout_fit']['body_font_px'] == 34
    assert item['layout_fit']['title_font_px'] == 70
    retained(directory, page)


@pytest.mark.parametrize('subtitle', ['', '先核对条件，再决定怎样使用当前方法。'])
def test_long_title_and_long_continuous_body_use_measured_header_spacing(tmp_path, fixtures, subtitle):
    page = {'title': '把题目条件连接到完整判断\n再检查每一步的理由', 'subtitle': subtitle, 'nodes': [],
            'text': '读题时先明确对象和目标，再列出可以使用的条件。独立解释判断依据，核对结论是否回应题目，发现差别后回到对应概念。' * 5}
    directory, process, result = render(tmp_path, fixtures, 'magazine-a', kind='method', **page)
    assert process.returncode == 0, result
    retained(directory, page)


def test_amounts_course_codes_and_full_formula_survive_adaptive_layout(tmp_path, fixtures):
    page = {'title': '先拆条件，再核对结果', 'subtitle': '核对 TEST1234 的完整表达式和金额，不省略任何符号或条件。',
            'nodes': ['四项关系｜Eclose=Eopen+Contributions+Profit-Distributions',
                      '期初与期末｜70,000 与 85,000 必须分别对应题目中的期间',
                      '单列变动｜10,000 与 6,000 的含义要分别核对，不能直接合并进利润',
                      '回代检查｜15,000、4,000、11,000 均保留原样，不在排版时计算或改写'],
            'text': '公式中的每一项都要在题目中找到相应依据。先独立写出完整过程，再逐项核对金额和正负号；结果相等不能替代对条件的解释。' * 3}
    directory, process, result = render(tmp_path, fixtures, 'magazine-a', kind='method', **page)
    assert process.returncode == 0, result
    retained(directory, page)


def test_impossible_single_page_still_refuses_without_truncating_or_shrinking(tmp_path, fixtures):
    directory, process, result = render(tmp_path, fixtures, 'magazine-a', kind='method',
        title='保留完整解释', subtitle='', nodes=[], text='完整保留所有字词和条件。' * 100)
    assert process.returncode != 0
    assert '完整内容仍超过单页容量' in result['error'] and '不会缩小字号' in result['error']
    assert not (directory / 'method.png').exists()


def test_previously_fitting_a_method_retains_body_layout_with_prominent_identity(tmp_path, fixtures):
    reference = os.environ.get('COURSE_VISUAL_CAPACITY_BEFORE_RENDERER')
    if not reference or not Path(reference).is_file():
        pytest.skip('Optional historical A byte comparison requires a retained baseline')
    directory, process, result = render(tmp_path, fixtures, 'magazine-a', kind='method',
        title='先看条件，再判断', subtitle='保留原样式与原文。',
        nodes=['核对对象｜确认当前题目中的对象。', '检查结果｜解释为什么满足条件。'],
        text='独立练习后再核对，不删原文或改变字号。')
    assert process.returncode == 0, result
    old = tmp_path / 'before'; old.mkdir()
    process = subprocess.run([NODE, reference, str(directory / 'input.json'), str(old)],
                             cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stdout
    old_texts = ET.parse(old / 'method.svg').getroot().findall(f'.//{SVG}text')
    new_texts = ET.parse(directory / 'method.svg').getroot().findall(f'.//{SVG}text')
    assert [ET.tostring(t) for t in new_texts[2:]] == [ET.tostring(t) for t in old_texts[2:]]
    assert Image.open(directory / 'method.png').size == Image.open(old / 'method.png').size
    assert float(new_texts[0].attrib['font-size']) >= 40
    assert float(new_texts[1].attrib['font-size']) >= 40
