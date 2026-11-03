"""One consented Seedream background; no course text, PDF or logo leaves this app."""
from io import BytesIO
from pathlib import Path
import base64
import hashlib
import json
import requests
from PIL import Image
from fastapi import HTTPException
from sqlalchemy import select
from backend.app.models import ModelConfig
from backend.app.services import course_visual_workflow as flow

STYLES = {
    'paper-depth': ('纸感与光影', 'Subtle ivory-white paper relief and soft natural studio shadows. A narrow deep-blue folded ribbon and a small orange accent at the lower outer edges; restrained editorial product photography lighting.'),
    'linear-geometry': ('轻量几何线条', 'A few thin deep-blue geometric curves and one small orange accent in the outer edges of the middle-lower area. Abstract geometry only, not a mathematical diagram. Calm white editorial background.'),
    'quiet-paper': ('更简洁的纸感', 'Almost-white fine paper texture with extremely subtle side lighting, a tiny orange accent and a thin deep-blue line at the outer lower edges. Very sparse, quiet, professional.'),
}
STRENGTHS = {'light': 'Very subtle, pale accents, plenty of clean white space.', 'balanced': 'Clearly visible at the outer edges, but subordinate to the real product that will be added locally.'}
SCOPE = '仅发送下方背景设计提示词、尺寸和模型参数。不发送课程文案、学校/课程代码、PDF、样张、Logo、来源评论或本机路径；生成后在本机叠加真实资料和文字。'


def model_context(db, user):
    model = db.scalar(select(ModelConfig).where(ModelConfig.user_id == user.id, ModelConfig.model_type == 'image', ModelConfig.is_default.is_(True)))
    hint = None if model is None else {'id': model.id, 'name': model.name, 'model_name': model.model_name, 'destination': model.base_url.rstrip('/') + '/images/generations', 'configured': bool(model.encrypted_api_key)}
    return model, hint


def supported(model):
    return model is not None and model.base_url.rstrip('/') == 'https://ark.cn-beijing.volces.com/api/v3' and model.model_name.startswith(('doubao-seedream-5-0-flash-', 'doubao-seedream-5-0-pro-'))


def prepare(db, user, row, slot, style, strength):
    page = next((p for p in flow.direct(row.data)['pages'] if p['slot'] == slot), None)
    if not page: raise HTTPException(404, '当前方案中没有这张图')
    if page['kind'] in {'sample', 'collage', 'pdf-page'}: raise HTTPException(422, '真实PDF样张保持白底与完整原页；可用“修改这张”调整外部说明')
    flow.require_approved(row.data, 'copy' if page['kind'] == 'cover' or flow.bundle_ready(row.data) else 'cover')
    flow.require_content_sample(row.data)
    if page['kind'] != 'cover' and not any(a['slot'] == slot for a in row.data['images']):
        raise HTTPException(422, '请先生成内页，再为这张图设计背景')
    if style not in STYLES or strength not in STRENGTHS: raise HTTPException(422, '请选择支持的背景方向')
    model, hint = model_context(db, user)
    zones = ('Keep the top 35 percent completely white for locally typeset headlines. Keep the central product zone from x=12 to 88 percent and y=36 to 82 percent free of objects; real document pages will be composited there locally.'
             if page['kind'] == 'cover' else 'Keep the central 84 percent of the canvas completely white and uncluttered for locally typeset explanatory text. Restrict all decoration to the outer edges.')
    prompt = ('Visual Director master lock: 1536x2048px, strict 3:4 vertical portrait, no square, no landscape, no crop, no extra border. '
              'White #FFFFFF background, deep blue #0755A2 and orange #F58A25 only as small accents. '
              'Create one premium editorial BACKGROUND ONLY, not a finished poster. ' + zones + ' '
              'Keep the bottom 15 percent pure white for a real logo added later. ' + STYLES[style][1] + ' ' + STRENGTHS[strength] + ' '
              'No text, letters, Chinese characters, numbers, formulas, page counters, logos, books, documents, fake worksheets, product mockups, people, university marks, neon, gradients or visual clutter. '
              'No placeholder text, no different template, no random layout shift. The background must support a real educational product without inventing its content.')
    result = {'slot': slot, 'style': style, 'strength': strength, 'style_label': STYLES[style][0], 'prompt': prompt, 'scope': SCOPE,
              'model': hint, 'supported': supported(model), 'size': '1536x2048', 'count': 1,
              'estimated_cost': '约 ¥0.12 / 张，实际以火山方舟账单为准' if model and 'flash' in model.model_name else '按当前模型计费',
              'row_version': row.row_version, 'input_digest': flow.fingerprint(row.data, 'set')}
    # Bind consent to current credentials without returning any credential material.
    result['plan_digest'] = flow.digest({'plan': result, 'credential_revision': hashlib.sha256((model.encrypted_api_key or '').encode()).hexdigest() if model else ''})
    return result


class SeedreamBackgroundClient:
    def generate(self, *, model, api_key, prompt):
        try:
            response = requests.post(model.base_url.rstrip('/') + '/images/generations',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={'model': model.model_name, 'prompt': prompt, 'size': '1536x2048', 'response_format': 'b64_json', 'watermark': False}, timeout=(15, 180))
            payload = response.json()
            if response.status_code != 200:
                code = payload.get('error', {}).get('code', '') if isinstance(payload, dict) else ''
                messages = {'ModelNotOpen': '请在火山方舟开通当前图片模型', 'AuthenticationError': '请检查图片模型API Key', 'AccountOverdueError': '请检查火山方舟余额', 'OperationDenied.ServiceOverdue': '请检查火山方舟余额'}
                raise ValueError(f'图片接口 HTTP {response.status_code}：' + messages.get(code, '生成未完成，请检查服务状态；未自动重试'))
            rows = payload.get('data', [])
            if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict): raise ValueError('图片接口没有返回一张可用背景')
            encoded = rows[0].get('b64_json')
            if not isinstance(encoded, str) or not encoded or len(encoded) > 44_000_000: raise ValueError('图片接口没有返回有效背景数据')
            raw = base64.b64decode(encoded, validate=True)
            # Decode and bound untrusted raster data before a local render.
            with Image.open(BytesIO(raw)) as image:
                if image.format not in {'PNG', 'JPEG', 'WEBP'} or image.width * image.height > 5_000_000 or min(image.size) < 700:
                    raise ValueError('返回图片的格式或尺寸不符合背景要求')
                if abs(image.width / image.height - .75) > .025: raise ValueError('返回背景不是3:4竖图；已停止合成，旧稿保留')
                image.load()
                return raw
        except requests.RequestException:
            raise ValueError('图片接口连接超时或网络异常，结果可能已生成；未自动重试，请先核对方舟调用记录') from None
        except (KeyError, TypeError, json.JSONDecodeError, base64.binascii.Error):
            raise ValueError('图片接口返回内容不可用，旧稿保留') from None


def get_background_client():
    return SeedreamBackgroundClient()


def local_path(root, entry):
    root = Path(root).resolve(); relative = Path(entry['path']); path = root / relative
    if relative.is_absolute() or '..' in relative.parts or path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
        raise HTTPException(409, '背景文件路径无效，旧图保留')
    if flow.hash_file(path) != entry['sha256']: raise HTTPException(409, '背景文件指纹已变化，请恢复原文件或另做背景')
    return path.resolve()
