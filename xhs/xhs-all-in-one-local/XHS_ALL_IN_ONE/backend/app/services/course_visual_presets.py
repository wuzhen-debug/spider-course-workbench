"""Selectable visual skeletons and observable editorial checks, never approval."""
import json
from pathlib import Path

from backend.app.services.course_content_editorial import COPY_GOALS, quality_hints

RESOURCES = Path(__file__).resolve().parents[1] / 'resources/course_workflow'
TEMPLATES = [
    {'id': 'magazine-a', 'name': 'A 杂志讲解版（已确认）', 'description': '白底蓝橙、宽正文与细线；4张干货后接9张原样PDF单页预览。',
     'suitable_for': '资料痛点与卖点讲解，或研究选题后的完整知识解释'},
    {'id': 'question-led', 'name': '问题大标题', 'description': '大标题聚焦一个问题，下部以真实讲义承接。',
     'suitable_for': '具体学习情境、条件混淆、问题切入'},
    {'id': 'decision-map', 'name': '判断方法图', 'description': '纵向判断节点与真实样张并列，解释先看什么再用什么。',
     'suitable_for': '方法选择、条件判断、解题路径'},
    {'id': 'sample-led', 'name': '真实样张试读', 'description': '突出真实正文样张，用外部说明解释讲义价值。',
     'suitable_for': '资料试读、讲解方式、购买前判断'},
]
DENSITIES = [
    {'id': 'compact', 'name': '简洁大字', 'description': '减少说明量，突出一个问题；超长提示精简，不缩小字硬塞。'},
    {'id': 'standard', 'name': '标准讲解', 'description': '保留必要说明与条件关系，完整样张保持原比例。'},
]


def preview_path(template_id):
    if template_id not in {item['id'] for item in TEMPLATES}:
        return None
    return RESOURCES / 'template_previews' / (template_id + '.png')


def choices():
    return {'default_template_id': 'magazine-a', 'templates': [{**item, 'preview_available': preview_path(item['id']).is_file()} for item in TEMPLATES],
            'writing_goals': [{'id': key, 'name': value['label'], 'description': value['instruction']} for key, value in COPY_GOALS.items()],
            'densities': DENSITIES}


def quality(data):
    copy = data['copy']; plan = data['visual_plan']
    selected = [s for s in data.get('evidence', []) if s.get('id') in data.get('selected_source_ids', []) and not s.get('excluded')]
    hints = quality_hints(copy, data['brand']['name'], selected, plan)
    checks = [{'id': item['code'], 'label': {
        'missing_takeaway': '具体读者收获', 'missing_tags': '相关话题', 'long_copy': '正文信息密度',
        'missing_material_bridge': '真实资料的承接', 'limited_research': '选题研究依据',
        'cover_only_sample': '正文样张依据',
    }.get(item['code'], '编辑检查'), 'status': 'attention', 'detail': item['message']} for item in hints['items']]
    def add(key, label, status, detail):
        checks.append({'id': key, 'label': label, 'status': status, 'detail': detail})
    add('lengths', '标题与正文字数', 'ready' if 0 < len(copy['title']) <= 20 and 0 < len(copy['body']) <= 1000 else 'attention',
        f"标题{len(copy['title'])}/20字，正文{len(copy['body'])}/1000字；字数通过不代表内容质量通过。")
    add('visual_template', '视觉版式', 'ready' if plan.get('template_id') not in {None, '', 'legacy'} else 'attention',
        '已选择新版模板，实际标题、样张和布局仍需看图。' if plan.get('template_id') not in {None, '', 'legacy'} else '当前保留旧版式，可在“模板与标准”中选择新版式。')
    add('copy_visual_bridge', '正文与图片的承接', 'manual' if plan.get('method_text', '').strip() or copy.get('goal') == 'sample-trial' else 'attention',
        '请核对方法说明与真实样张是否兑现标题和正文。' if plan.get('method_text', '').strip() or copy.get('goal') == 'sample-trial' else '当前没有方法内页；若标题承诺解释，请补上具体方法，避免只展示讲义封面。')
    add('product_basis', '资料事实与适用范围', 'manual', '页数、版本、样页可核对；完整内容QA、公开展示权利与本学期考试要求仍需人工确认。')
    add('editorial_review', '吸引力与原创表达', 'manual', '检查开头是否具体、读者是否得到完整方法、资料怎样接住问题；不能只换课程代码，不能把本提示当流量预测。')
    count = sum(c['status'] == 'attention' for c in checks)
    return {'summary': f'有{count}项可改进之处；这里检查已保存版本，不代替选题、审美或人工审核。', 'checks': checks}
