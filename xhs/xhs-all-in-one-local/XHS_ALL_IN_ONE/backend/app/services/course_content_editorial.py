"""Shared, source-grounded course-copy direction. No generation or writes.

Visual Director owns visual planning; the bounded aussie-course-xhs writing
references own topic/copy decisions. Existing records keep their skill hashes.
"""
from pathlib import Path
import hashlib
import json

from fastapi import HTTPException

RESOURCES = Path(__file__).resolve().parents[1] / 'resources/course_workflow'
COPY_REFERENCES = ('topics.md', 'writing.md', 'editorial.md')
COPY_GOALS = {
    'student-question': {
        'label': '具体问题切入',
        'instruction': '从一个具体读题、理解或练习情境切入，解释一个卡点及下一步。问题证据不足时以假设学习情境表达，不宣称学生普遍如此。',
    },
    'method-save': {
        'label': '方法收藏',
        'instruction': '给出可在下一道练习中使用的判断条件或操作方法，解释何时使用、如何自查。让读者不购买也能得到完整收获，不罗列全课程模块凑内容。',
    },
    'sample-trial': {
        'label': '真实样张试读',
        'instruction': '围绕一个资料选择疑问，说明真实样页具体讲了什么、怎样用于练习、适合什么学习阶段；自然邀请先了解目录和样张再判断购买。只承诺已给出的资料事实。',
    },
}


def copy_goal(value=None):
    goal = value or 'student-question'
    if goal not in COPY_GOALS:
        raise HTTPException(422, '请选择具体问题切入、方法收藏或真实样张试读')
    return goal


def writing_skill_bundle(rules=None):
    """Read only the three writing references, verified against the chosen run.

    Research has no workflow snapshot yet, so it uses the current catalog. The
    digest stored by its writing-plan API already covers the compiled prompt.
    """
    entries = rules['skills'] if rules is not None else json.loads((RESOURCES / 'catalog.json').read_text())['skills']
    selected = []
    for name in COPY_REFERENCES:
        relative = f'skills/aussie-course-xhs/references/{name}'
        entry = next((e for e in entries if e.get('skill') == 'aussie-course-xhs' and e.get('file') == relative), None)
        if entry is None:
            raise HTTPException(409, '本记录缺少课程文案 Skill 快照，请另存新工作记录后使用新策略')
        path = RESOURCES / relative
        try:
            content = path.read_bytes()
        except OSError:
            raise HTTPException(409, '课程文案 Skill 快照不可用，旧稿已保留') from None
        if hashlib.sha256(content).hexdigest() != entry['sha256']:
            raise HTTPException(409, '课程文案 Skill 快照已变化，请核对版本后另存新工作记录')
        selected.append({'file': relative, 'sha256': entry['sha256'], 'text': content.decode('utf-8')})
    return selected


def writing_direction(goal=None, brand='', rules=None):
    goal = copy_goal(goal)
    references = writing_skill_bundle(rules)
    return (
        '课程文案职责：由 aussie-course-xhs 负责具体选题、原创表达、学生收获和真实资料价值。'
        'XHS Visual Director 只负责后续视觉编排，不在此阶段混入暗色风格、固定页数或整套画面指令。\n'
        f"本篇编辑目标：{goal}（{COPY_GOALS[goal]['label']}）。{COPY_GOALS[goal]['instruction']}\n"
        f'本篇已选择品牌：{brand or "未选择；不得擅自署名"}。品牌身份不等于学校官方或学生本人。\n'
        '下面三个文件是本次实际使用且已核对哈希的写作参考，只采用其编辑原则；'
        '明确选择的目标优先，不能把参考中的可选例子写成所有课程的必备栏目。\n'
        + '\n\n'.join(f"【{r['file']}】\n{r['text']}" for r in references)
        + '\n\n本篇交付要求：\n'
        '先在编辑判断中比较有实质差异的切入点，再选一个；不是把资料名称直接当选题。'
        '标题、开头、完整学习收获、样页证据和下一步了解资料动作要相互对应。'
        '正文通常150–450中文字符，按信息量伸缩但不超过1000字；不为接近上限堆砌模块与英文名。'
        '至少提供一个读者可立即使用的判断、解释或自查动作；不能只说“理解概念、做题、看解析”。'
        'tags用相关学校、课程和当前问题，通常3–8个；不堆无关词，不承诺标签数量带来推荐。'
        'takeaway必须是一个可观察的读后动作，不得留空或只写“提高效率”。'
        '涉及产品时明确资料如何接住本篇问题，但不硬塞价格、虚假优惠、成绩、销量或QA结论。'
        '仅搜索标题、空正文或没有评论时，不能编造学生原话、“大家都在问”、热门验证或购买需求。'
        '内部证据定位、限制、备选理由和待核验项放在source_map/editor_notes，不能混入发布正文。'
        '完成后做替换课程代码检查：若大段文字可直接用于另一门课，应回到真实例子、条件或样页重新组织。'
    )


def evidence_summary(selected):
    details = sum(s.get('content_status') == 'detail' and bool(s.get('content', '').strip()) for s in selected)
    comments = sum(len(s.get('comments') or []) for s in selected)
    return {'source_count': len(selected), 'detail_count': details, 'comments_read': comments,
            'limited': not details, 'student_questions_verified': False,
            'interpretation': ('只有标题或搜索摘要，可作为待测试选题线索；没有读到正文的来源不能证明原文结构或结论。' if not details else '只代表本次读取样本；评论身份、问题适用范围与热度仍须人工判断。')}


def quality_hints(copy, brand='', selected=None, visual_plan=None):
    """Visible editorial gaps, never an engagement score or automatic approval."""
    hints = []
    if not str(copy.get('takeaway') or '').strip():
        hints.append({'code': 'missing_takeaway', 'message': '请写清读者看完能完成的一个具体动作。'})
    if not copy.get('tags'):
        hints.append({'code': 'missing_tags', 'message': '尚未选择与学校、课程和当前问题相关的话题。'})
    body = str(copy.get('body') or '')
    if len(body) > 450:
        hints.append({'code': 'long_copy', 'message': '正文较长，请检查模块罗列与重复建议，保留能兑现标题的解释。'})
    if copy_goal(copy.get('goal')) == 'sample-trial' and brand and brand not in body:
        hints.append({'code': 'missing_material_bridge', 'message': '试读目标需要说明本篇品牌资料如何接住问题，以及读者怎样继续了解。'})
    if selected is not None and evidence_summary(selected)['limited']:
        hints.append({'code': 'limited_research', 'message': '当前参考仅有标题或摘要，选题仍待验证，不能称已确认学生需求。'})
    cover_page = visual_plan.get('cover_sample_page') if visual_plan is not None else None
    explicit_content = isinstance(cover_page, int) and not isinstance(cover_page, bool) and cover_page >= 2
    if visual_plan is not None and set(visual_plan.get('sample_pages') or []) <= {1} and not explicit_content:
        hints.append({'code': 'cover_only_sample', 'message': '当前只选讲义封面，建议选一张能兑现本篇收获的真实内容页。'})
    return {'kind': 'editorial_gaps', 'not_engagement_prediction': True, 'items': hints}
