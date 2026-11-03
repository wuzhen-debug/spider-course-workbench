"""Full-width real PDF previews with a compact metadata header; never crop pages."""
from pathlib import Path
from fastapi import HTTPException
from PIL import Image, ImageChops, ImageDraw, ImageFont
from backend.app.services.course_brands import resolve_brand, logo_path

RESOURCES = Path(__file__).resolve().parents[1] / 'resources/course_workflow'
PREVIEW_LAYOUT = 'pdf-full-width-v2'
PREVIEW_WIDTH = 1200
HEADER_HEIGHT = 124


def preview_brand(brand_id='xingtu'):
    """Reuse the approved real brand asset; never invent a logo or modify it."""
    try:
        brand = resolve_brand(brand_id)
        return {'id': brand['id'], 'name': brand['name'], 'logo_sha256': brand['logo_sha256'], 'treatment': 'real-logo-watermark-v1'}
    except (OSError, KeyError, ValueError):
        raise HTTPException(409, '真实品牌Logo暂不可用或指纹已改变，请核对后再生成；旧样张保留')


def brand_logo(brand):
    with Image.open(logo_path(brand)) as source:
        mark = source.convert('RGBA')
    r, g, b, _ = mark.split()
    white = ImageChops.darker(ImageChops.darker(r, g), b)
    alpha = white.point(lambda value: max(0, min(255, (246 - value) * 11)))
    mark.putalpha(alpha)
    return mark.crop(alpha.getbbox())


def font(size):
    for path in ['/System/Library/Fonts/PingFang.ttc', '/System/Library/Fonts/STHeiti Light.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']:
        if Path(path).is_file(): return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def fit_text(draw, text, size, width):
    text = str(text)
    while size > 18 and draw.textbbox((0, 0), text, font=font(size))[2] > width: size -= 1
    while draw.textbbox((0, 0), text, font=font(size))[2] > width: text = text[:-2] + '…'
    return text, font(size)


def frame_page(source, output, snapshot, page, total, brand=None):
    brand = brand or preview_brand()
    logo = brand_logo(brand)
    with Image.open(source) as original:
        # Keep the PDF's own ratio instead of shrinking it inside a 3:4 frame.
        # The final image contains the entire page, including its real footer.
        height = round(original.height * PREVIEW_WIDTH / original.width)
        if height > 12000:
            raise HTTPException(422, '此 PDF 单页比例过长，请选择普通页面制作样张；原文件与旧图保留')
        page_image = original.convert('RGB').resize((PREVIEW_WIDTH, height), Image.Resampling.LANCZOS)
        watermark = logo.copy()
        watermark.thumbnail((360, 360), Image.Resampling.LANCZOS)
        watermark.putalpha(watermark.getchannel('A').point(lambda value: value * 34 // 255))
        page_image.paste(watermark, ((page_image.width-watermark.width)//2, (page_image.height-watermark.height)//2), watermark)
    canvas = Image.new('RGB', (PREVIEW_WIDTH, HEADER_HEIGHT + height), 'white')
    canvas.paste(page_image, (0, HEADER_HEIGHT))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, PREVIEW_WIDTH, HEADER_HEIGHT - 1), fill='#101f38')
    label = ' · '.join(v for v in [snapshot['university'], snapshot['course_code']] if v and v != '未标注') or '课程资料样张'
    text, face = fit_text(draw, label, 42, 1016)
    draw.text((28, 8), text, font=face, fill='white')
    details = ' · '.join(v for v in [snapshot['term'], snapshot['material_type'], f'原 PDF 第 {page} / {total} 页'] if v and v != '未标注')
    text, face = fit_text(draw, details, 26, 1016)
    draw.text((28, 76), text, font=face, fill='#f2b45b')
    logo.thumbnail((84, 84), Image.Resampling.LANCZOS)
    draw.rounded_rectangle((1080, 12, 1184, 112), radius=8, fill='white')
    canvas.paste(logo, (1090+(84-logo.width)//2, 20+(84-logo.height)//2), logo)
    draw.rectangle((0, HEADER_HEIGHT-4, PREVIEW_WIDTH, HEADER_HEIGHT-1), fill='#f2b45b')
    canvas.save(output, format='PNG')
    return {'width': canvas.width, 'height': canvas.height}
