"""Layout invariants for measured CJK wrapping; no live database or network."""
from pathlib import Path
import json
import subprocess
import xml.etree.ElementTree as ET

import pytest
from test_course_visual_templates_render import ROOT, NODE, fixtures, render


MODULE = ROOT / 'backend/app/services/course_visual_linebreak.mjs'
REPORTED_TEXT = ('权益变动里混着业主投入和提款，它们改变权益但不属于利润。读题顺序：先从收入走到税后净利润；'
                 '再把权益拆成期初权益加业主投入加本期利润减业主提款等于期末权益；反推利润时先扣净业主投入。'
                 '用讲义数据自查：期末 85,000 减期初 70,000 得 15,000，净投入 4,000，利润应为 11,000。')
HARNESS = r'''
import {wrapMeasuredText} from MODULE;
import {createRequire} from 'node:module';
import path from 'node:path';import os from 'node:os';
const require=createRequire(import.meta.url);let sharp;
try{sharp=require('sharp')}catch{sharp=createRequire(path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/'))('sharp')}
const segmenter=new Intl.Segmenter('und',{granularity:'grapheme'}),cache=new Map();
const escape=s=>s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const results=[];
for(const item of CASES){
 async function measure(text){
  if(item.mono)return Array.from(segmenter.segment(text)).length;
  if(!text)return 0;const k=JSON.stringify([text,item.size||34]);
  if(!cache.has(k)){const m=await sharp({text:{text:escape(text),font:`Hiragino Sans GB ${item.size||34}`,dpi:72,rgba:true}}).metadata();cache.set(k,m.width||0)}return cache.get(k);
 }
 try{const rows=await wrapMeasuredText(item.text,item.width,measure);results.push({rows,widths:await Promise.all(rows.map(measure))})}
 catch(error){results.push({error:error.message})}
}
console.log(JSON.stringify(results));
'''


def wrap_cases(cases):
    source = HARNESS.replace('MODULE', json.dumps(MODULE.as_uri())).replace('CASES', json.dumps(cases, ensure_ascii=False))
    result = subprocess.run([NODE, '--input-type=module', '-e', source], cwd=ROOT,
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def compact(value):
    return ''.join(value.split())


def test_reported_full_paragraph_fits_real_font_without_content_loss():
    result = wrap_cases([{'text': REPORTED_TEXT, 'width': 928}])[0]
    assert 'error' not in result
    assert len(result['rows']) >= 3
    assert compact(''.join(result['rows'])) == compact(REPORTED_TEXT)
    assert all(width <= 928 for width in result['widths'])
    assert all(not line.startswith(tuple('，。！？；：、）》】」』”’')) for line in result['rows'])
    assert all(not line.endswith(tuple('（《【「『“‘')) for line in result['rows'])


@pytest.mark.parametrize('text', [
    '甲乙丙丁戊，己庚辛壬癸，天地玄黄宇宙洪荒。',
    '甲乙丙丁（戊己庚辛）壬癸，天地玄黄（宇宙洪荒）。',
    '甲乙丙丁戊。）》己庚辛壬癸，天地玄黄。',
    '甲乙丙丁(AB)戊己庚辛，甲乙丙丁[CD]戊己庚辛。',
    'abcdefghij，klmnopqrst。uvwxyz，hello。',
])
def test_full_paragraph_flows_past_two_full_lines_and_respects_punctuation(text):
    result = wrap_cases([{'text': text, 'width': 6, 'mono': True}])[0]
    assert 'error' not in result
    assert ''.join(result['rows']) == text
    assert all(width <= 6 for width in result['widths'])
    assert all(not row.startswith(tuple(',.;:!?，。！？；：、）》】」』”’)]}')) for row in result['rows'])
    assert all(not row.endswith(tuple('（《【「『“‘([{')) for row in result['rows'])


def test_hard_breaks_blank_lines_crlf_and_authored_punctuation_are_preserved():
    text = '第一行 \r\n\r\n）第二行\n第三行（\n'
    result = wrap_cases([{'text': text, 'width': 20, 'mono': True}])[0]
    assert result['rows'] == ['第一行', '', '）第二行', '第三行（']
    assert wrap_cases([{'text': '', 'width': 20, 'mono': True}])[0]['rows'] == []


def test_course_codes_grouped_amounts_and_english_words_are_atomic_when_they_fit():
    text = 'ACC1001 与 FNCE10002；85,000 和 70,000.50，$11,000、-$11,000、$-11,000 对应 25%；check conditions before practice。'
    result = wrap_cases([{'text': text, 'width': 230, 'size': 24}])[0]
    assert 'error' not in result
    assert compact(''.join(result['rows'])) == compact(text)
    for token in ['ACC1001', 'FNCE10002', '85,000', '70,000.50', '$11,000', '-$11,000', '$-11,000', '25%', 'conditions', 'practice']:
        assert any(token in row for row in result['rows']), (token, result)
    assert all(width <= 230 for width in result['widths'])


def test_long_tokens_fall_back_without_splitting_graphemes_or_inserting_spaces():
    text = 'ACC1001Profit25percentabcdefghijklmn；cafe\u0301abcdefghijklmn。👩\u200d💻👩\u200d💻👩\u200d💻'
    result = wrap_cases([{'text': text, 'width': 7, 'mono': True}])[0]
    assert 'error' not in result
    assert ''.join(result['rows']) == text
    assert all(width <= 7 for width in result['widths'])
    assert all(not row.startswith(('\u0301', '\u200d')) and not row.endswith('\u200d') for row in result['rows'])


def test_a_single_grapheme_that_cannot_fit_still_fails_safely():
    result = wrap_cases([{'text': '字', 'width': 0.5, 'mono': True}])[0]
    assert '超出区域宽度' in result['error']


@pytest.mark.parametrize('token', ['-$1234567890', '$-1234567890', '−¥1234567890'])
def test_oversized_financial_amount_keeps_sign_and_currency_with_first_digit(token):
    result = wrap_cases([{'text': token, 'width': 4, 'mono': True}])[0]
    assert 'error' not in result
    assert ''.join(result['rows']) == token
    assert result['rows'][0].startswith(token[:3])
    assert all(row not in ['-', '−', '$', '¥', '-$', '$-', '−¥'] for row in result['rows'])
    assert all(width <= 4 for width in result['widths'])


def test_reported_method_produces_actual_png_without_editing_the_body(tmp_path, fixtures):
    directory, process, result = render(tmp_path, fixtures, 'magazine-a', kind='method',
        title='先拆权益，再算利润', subtitle='', nodes=[], text=REPORTED_TEXT)
    assert process.returncode == 0, result
    assert (directory/'method.png').is_file()
    root = ET.fromstring((directory/'method.svg').read_text())
    lines = [node.text or '' for node in root.findall('{http://www.w3.org/2000/svg}text')
             if node.attrib.get('font-size') == '34' and node.attrib.get('font-weight') == '400']
    assert compact(''.join(lines)) == compact(REPORTED_TEXT)
    assert result['files'][0]['brief']['text'] == REPORTED_TEXT
