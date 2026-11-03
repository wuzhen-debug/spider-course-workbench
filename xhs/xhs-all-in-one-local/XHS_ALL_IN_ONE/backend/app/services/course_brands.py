"""Confirmed local brand assets. Selection is per work, never an account default."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from fastapi import HTTPException

RESOURCES = Path(__file__).resolve().parents[1] / 'resources/course_workflow'


def brands():
    entries = json.loads((RESOURCES / 'brands.json').read_text())['brands']
    for brand in entries:
        path = (RESOURCES / brand['logo']).resolve()
        if path.parent != RESOURCES.resolve() or hashlib.sha256(path.read_bytes()).hexdigest() != brand['logo_sha256']:
            raise HTTPException(409, '真实品牌Logo指纹已改变，请核对后制作；旧稿保留')
    return deepcopy(entries)


def resolve_brand(value):
    """Accept saved names for compatibility, but never guess a missing choice."""
    value = str(value or '').strip()
    for brand in brands():
        if value in {brand['id'], brand['name']}:
            return brand
    raise HTTPException(422, '请先选择本篇品牌：星途留学或稳过留学')


def saved_brand(snapshot):
    """Validate historical name/hash snapshots without rewriting their identity."""
    brand = resolve_brand(snapshot.get('id') or snapshot.get('name'))
    if any(snapshot.get(k) != brand[k] for k in ('name', 'logo_sha256')):
        raise HTTPException(409, '本稿品牌或Logo版本已改变，未替换原图，请先核对')
    return brand


def logo_path(snapshot):
    return RESOURCES / saved_brand(snapshot)['logo']


def select_bundle(bundle, value):
    result = deepcopy(bundle)
    result['brand'] = resolve_brand(value)
    # Skill snapshots contain examples; only the selected identity is authoritative.
    result['rules'] = result['rules'].replace('本品牌使用真实星途留学Logo', '本品牌使用本篇所选品牌的真实Logo')
    result['rules'] += f"\n本篇唯一品牌：{result['brand']['name']}。文案、封面、内页与PDF样张均沿用该品牌真实Logo；不得混用其他品牌。\n"
    result['contract_digest'] = hashlib.sha256(json.dumps(
        {'base': bundle['contract_digest'], 'brand': result['brand'], 'rules': result['rules']},
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return result
