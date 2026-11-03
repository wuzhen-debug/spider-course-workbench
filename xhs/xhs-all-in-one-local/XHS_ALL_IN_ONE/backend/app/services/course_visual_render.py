"""Local deterministic PNG typesetting. Original PDF is an inherited read-only fd."""
import json
import os
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter
from backend.app.services.course_draft_images import font
from backend.app.services.course_visual_workflow import RESOURCES, hash_file
from backend.app.services.course_brands import logo_path

W, H = 1080, 1440
BLUE, INK, ORANGE, LINE = '#0755A2', '#172F47', '#F58A25', '#CEDDEB'


def words(draw, value, xy, size=36, width=936, leading=None, fill=INK, bottom=1200):
    leading = leading or int(size * 1.45)
    rows, row = [], ''
    for ch in str(value):
        if ch == '\n' or (row and draw.textlength(row + ch, font=font(size)) > width):
            rows.append(row); row = '' if ch == '\n' else ch
        else:
            row += ch
    if row:
        rows.append(row)
    x, y = xy
    if y + len(rows) * leading > bottom:
        raise ValueError('图内文字过长，请精简图文方案后重试；未裁切文字或覆盖旧图')
    for i, row in enumerate(rows):
        draw.text((x, y + i * leading), row, font=font(size), fill=fill)
    return y + len(rows) * leading


def canvas(data, logo, heading=None, instruction=None):
    image = Image.new('RGB', (W, H), 'white'); d = ImageDraw.Draw(image)
    words(d, data['source']['university'] + ' · ' + data['source']['course_code'], (72, 80), 31, bottom=132)
    d.line((72, 132, 1008, 132), fill=LINE, width=2)
    if heading:
        words(d, heading, (72, 160), 52, bottom=225)
    if instruction:
        words(d, instruction, (92, 220), 30, bottom=264)
        d.rectangle((72, 220, 77, 251), fill=ORANGE)
    d.line((72, 1315, 426, 1315), fill=LINE, width=2); d.line((654, 1315, 1008, 1315), fill=LINE, width=2)
    mark = logo.copy(); mark.thumbnail((150, 150), Image.Resampling.LANCZOS)
    image.paste(mark, (465 + (150 - mark.width) // 2, 1228 + (150 - mark.height) // 2))
    return image


def paper(canvas, image, box, angle=0):
    x, y, width = box
    page = image.copy().convert('RGBA'); page = page.resize((width, round(width * page.height / page.width)), Image.Resampling.LANCZOS)
    if angle:
        page = page.rotate(angle, Image.Resampling.BICUBIC, expand=True)
    layer = Image.new('RGBA', canvas.size); shadow = Image.new('RGBA', canvas.size)
    shadow.paste((23, 47, 71, 32), (x + 2, y + 13, x + page.width + 2, y + page.height + 13))
    shadow = shadow.filter(ImageFilter.GaussianBlur(13)); layer.alpha_composite(shadow)
    layer.alpha_composite(page, (x, y)); canvas.paste(Image.alpha_composite(canvas.convert('RGBA'), layer).convert('RGB'))


def render(fd, payload, destination, stage):
    import pypdfium2 as pdfium
    data = payload['data']; catalog = payload['catalog']; plan = data['visual_plan']; destination = Path(destination)
    logo = Image.open(logo_path(data['brand'])).convert('RGB')
    original = os.fdopen(fd, 'rb', closefd=False)
    with pdfium.PdfDocument(original, autoclose=False) as document:
        pages = [1, *plan['sample_pages']]
        if any(n < 1 or n > len(document) for n in pages):
            raise ValueError('样页超出当前PDF范围')
        profile = catalog.get('approved_display', {})
        def sample(number):
            known = profile.get('assets', {}).get(str(number)) if profile.get('source_sha256') == data['source']['sha256'] else None
            if known:
                path = RESOURCES / known['file']
                if hash_file(path) != known['sha256']:
                    raise ValueError('已核验展示样页的指纹发生变化')
                return Image.open(path).convert('RGB')
            page = document[number - 1]; bitmap = page.render(scale=min(2.4, 2000 / max(page.get_size())))
            result = bitmap.to_pil().convert('RGB').copy(); bitmap.close(); page.close()
            return result

        if stage == 'cover':
            image = Image.new('RGB', (W, H), 'white'); d = ImageDraw.Draw(image)
            words(d, data['source']['university'], (72, 80), 31, bottom=130)
            words(d, data['source']['course_code'], (72, 130), 86, bottom=230)
            lines = plan['cover_lines'] or [data['copy']['title'].replace(data['source']['course_code'], '').strip()]
            title = '\n'.join(lines)
            y = words(d, title, (72, 240), 74, leading=96, fill=INK, bottom=445)
            words(d, data['source']['material_type'] or '课程资料', (76, max(438, y + 8)), 30, bottom=493)
            chosen = plan['sample_pages']
            paper(image, sample(chosen[0]), (87, 588, 330), 9)
            if len(chosen) > 1:
                paper(image, sample(chosen[1]), (608, 580, 330), -9)
            paper(image, sample(1), (312, 520, 448), 0)
            words(d, f'{len(document)} 页 PDF · 真实讲义样张', (260, 1192), 29, width=740, bottom=1235, fill=BLUE)
            # Keep the exact real-logo footer system on every image.
            footer = canvas(data, logo)
            image.paste(footer.crop((0, 1228, W, H)), (0, 1228))
            image.save(destination / 'cover.png')
            return {'files': [{'file': 'cover.png', 'role': '封面', 'kind': 'cover'}], 'page_count': len(document), 'display_treatment': profile.get('treatment', '') if profile.get('source_sha256') == data['source']['sha256'] else '真实原页；学校标记、权利与隐私请在人工审核时核对'}

        result = []
        if plan['method_text'].strip():
            image = canvas(data, logo); d = ImageDraw.Draw(image)
            y = words(d, plan['method_title'], (72, 175), 62, leading=82, fill=BLUE, bottom=375)
            words(d, plan['method_text'], (72, y + 58), 38, leading=59, bottom=1175)
            image.save(destination / 'method.png'); result.append({'file': 'method.png', 'role': plan['method_title'], 'kind': 'method'})
        for i, number in enumerate(plan['sample_pages']):
            instructions = plan['sample_instructions']; hint = instructions[i] if i < len(instructions) and instructions[i] else '结合正文问题，查看这份真实讲义样张。'
            image = canvas(data, logo, '真实讲义样张', hint)
            page = sample(number); page.thumbnail((944, 944), Image.Resampling.LANCZOS)
            image.paste(page, ((W - page.width) // 2, 264 + (944 - page.height) // 2))
            d = ImageDraw.Draw(image); d.text((375, 1140), data['brand']['name'] + ' · 资料预览', font=font(27), fill='#CEDDEB')
            name = f'sample-{i}.png'; image.save(destination / name)
            result.append({'file': name, 'role': hint, 'kind': 'sample', 'source_page': number, 'full_page': True})
        image = canvas(data, logo); d = ImageDraw.Draw(image)
        y = words(d, '这样用讲义，再判断是否适合', (72, 175), 60, leading=80, fill=BLUE, bottom=365)
        y = words(d, f'{len(document)} 页 PDF · ' + data['source']['material_type'], (72, y + 28), 32, bottom=425)
        for i, step in enumerate(plan['usage_steps']):
            y = words(d, step, (100, max(470, y + 32)), 36, bottom=970)
        y = words(d, '先了解，再决定是否购买', (72, max(992, y + 28)), 42, bottom=1050)
        words(d, plan['cta'], (72, y + 16), 32, leading=46, bottom=1160)
        words(d, '资料用于学习辅助；考试范围以学校本学期 LMS 为准。', (72, 1180), 25, bottom=1220)
        image.save(destination / 'use-and-fit.png'); result.append({'file': 'use-and-fit.png', 'role': '使用方法与购买判断', 'kind': 'use'})
        return {'files': result, 'page_count': len(document), 'display_treatment': profile.get('treatment', '') if profile.get('source_sha256') == data['source']['sha256'] else '真实原页；请人工核对学校标记、权利与隐私'}


if __name__ == '__main__':
    try:
        result = render(int(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()), sys.argv[3], sys.argv[4])
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc) if isinstance(exc, ValueError) else '本地图片制作未完成，原文件与旧图保持不变'}, ensure_ascii=False))
        raise SystemExit(2)
