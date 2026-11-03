"""Read-only real PDF assets → Visual Director plan → deterministic SVG/PNG."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from backend.app.services.course_visual_workflow import RESOURCES, direct, hash_file
from backend.app.services.course_brands import logo_path
from backend.app.services.course_draft_images import PREVIEW_LAYOUT, frame_page, preview_brand


def render(fd, spec_path, output, stage):
    import pypdfium2 as pdfium
    spec = json.loads(Path(spec_path).read_text()); data = spec['data']; bundle = spec['catalog']; output = Path(output)
    if spec.get('revise'):
        override = spec['revise']; slot = override['asset']['slot']
        data['page_overrides'] = {**data.get('page_overrides', {}), slot: override['brief']}
    direction = direct(data)
    if stage == 'revise': pages = [p for p in direction['pages'] if p['slot'] == spec['revise']['asset']['slot']]
    elif stage == 'collage': pages = [p for p in direction['pages'] if p['kind'] == 'collage']
    elif stage == 'pdf-pages': pages = [p for p in direction['pages'] if p['kind'] == 'pdf-page']
    else: pages = [p for p in direction['pages'] if (p['kind'] == 'cover') == (stage == 'cover')]
    magazine = data['visual_plan'].get('template_id') == 'magazine-a'
    raw_pages = {p['source_page'] for p in pages if p['kind'] == 'pdf-page' and magazine}
    required = ({p['source_page'] for p in pages if p['kind'] in {'sample', 'pdf-page'}} if magazine else
                set([1, *data['visual_plan']['sample_pages'], *[p['source_page'] for p in pages if p['kind'] in {'sample', 'pdf-page'}]]))
    if not magazine and data['visual_plan'].get('cover_sample_page') is not None:
        required.add(data['visual_plan']['cover_sample_page'])
    required.update(number for page in pages if page['kind'] == 'collage' for number in page['source_pages'])
    source_images = {}; profile = bundle.get('approved_display', {})
    with os.fdopen(fd, 'rb', closefd=False) as stream, pdfium.PdfDocument(stream, autoclose=False) as pdf:
        for n in required:
            if n < 1 or n > len(pdf): raise ValueError('样页超出当前PDF范围')
            known = profile.get('assets', {}).get(str(n)) if n not in raw_pages and profile.get('source_sha256') == data['source']['sha256'] else None
            if known:
                src = RESOURCES / known['file']
                if hash_file(src) != known['sha256']: raise ValueError('真实展示样页指纹发生变化')
            else:
                page = pdf[n - 1]
                bitmap = page.render(scale=1600 / page.get_width() if n in raw_pages else min(2.4, 2100 / max(page.get_size())))
                src = output / f'input-{n}.png'; bitmap.to_pil().convert('RGB').save(src)
                bitmap.close(); page.close()
            if n in raw_pages:
                framed = output / f'branded-page-{n}.png'
                snapshot = {key: data['source'].get(key, '') for key in ('university','course_code','term','material_type')}
                frame_page(src, framed, snapshot, n, data['source']['page_count'], preview_brand(data['brand']['id']))
                src = framed
            source_images[str(n)] = str(src.resolve())
    payload = {'data': data, 'direction': direction, 'pages': pages, 'source_images': source_images,
               'logo': str(logo_path(data['brand']).resolve()), 'backgrounds': spec.get('backgrounds', {})}
    path = output / 'render-plan.json'; path.write_text(json.dumps(payload, ensure_ascii=False))
    node = shutil.which('node') or str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')
    if not Path(node).is_file(): raise ValueError('本机Node排版运行时不可用，未改旧稿')
    result = subprocess.run([node, str(Path(__file__).with_suffix('.mjs')), str(path), str(output)], capture_output=True, text=True, timeout=60)
    try: rendered = json.loads(result.stdout)
    except ValueError: raise ValueError('本地SVG排版未完成，旧图与原文件保留')
    if result.returncode or rendered.get('error'): raise ValueError(rendered.get('error', 'SVG排版未完成'))
    for item in rendered['files']:
        item['svg_sha256'] = hash_file(output / item['svg_file'])
        if magazine and item['kind'] == 'pdf-page':
            item.update(preview_layout=PREVIEW_LAYOUT, preview_brand=preview_brand(data['brand']['id']))
    return {**rendered, 'direction': direction,
            'display_treatment': ('真实样页由原PDF本机直接渲染，保留完整原比例与原页码；顶部信息栏及所选品牌真实Logo水印。' if magazine else
                                  profile.get('treatment', '') if profile.get('source_sha256') == data['source']['sha256'] else '原页按原比例保留；需人工核对学校标记、隐私和公开展示权利')}


if __name__ == '__main__':
    try:
        print(json.dumps(render(int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc) if isinstance(exc, ValueError) else '本地图文制作未完成，原件与旧稿均保留'}, ensure_ascii=False))
        raise SystemExit(2)
