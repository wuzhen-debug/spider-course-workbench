"""Isolated PDFium subprocess; receives an already-open read-only descriptor."""
import json
import os
import sys
from pathlib import Path


def render(fd, page_number, output, sample=False, frame_source=False):
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw, ImageFont
    stream = os.fdopen(fd, 'rb', closefd=False)
    with pdfium.PdfDocument(stream, autoclose=False) as document:
        total = len(document)
        if page_number < 1 or page_number > total: return {'error':'页码超出范围','page_count':total}
        page = document[page_number-1]
        width,height = page.get_size()
        if width <= 0 or height <= 0: return {'error':'PDF 页面尺寸异常'}
        scale = min((2400 if frame_source else 1600)/max(width,height), 3 if frame_source else 2)
        bitmap = page.render(scale=scale)
        picture = bitmap.to_pil().convert('RGB')
        if frame_source:
            # The framing service adds the real brand watermark and all
            # metadata. No synthetic footer is appended to the real PDF page.
            picture.save(output, format='PNG')
            bitmap.close(); page.close()
            return {'page_count':total,'width':picture.width,'height':picture.height}
        overlay = Image.new('RGBA',picture.size,(0,0,0,0)); draw = ImageDraw.Draw(overlay)
        try: font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',max(16,picture.width//28))
        except OSError: font = ImageFont.load_default()
        text = 'SAMPLE - COURSE PREVIEW' if sample else 'LOCAL PREVIEW - NOT PUBLISHED'
        for y in range(max(40,picture.height//5),picture.height,max(100,picture.height//3)):
            draw.text((picture.width//10,y),text,font=font,fill=(40,70,100,55))
        # Append a footer outside the PDF canvas, preserving the source's
        # original page numbers and bottom-margin content in the preview.
        rendered=Image.alpha_composite(picture.convert('RGBA'),overlay).convert('RGB')
        canvas=Image.new('RGB',(rendered.width,rendered.height+40),(15,34,60));canvas.paste(rendered,(0,0))
        try: footer_font=ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',18)
        except OSError: footer_font=ImageFont.load_default()
        footer=ImageDraw.Draw(canvas);label=f'PDF SAMPLE  |  {page_number} / {total}' if sample else f'LOCAL SAMPLE  |  {page_number} / {total}'
        box=footer.textbbox((0,0),label,font=footer_font)
        footer.text((12,rendered.height+(40-(box[3]-box[1]))/2-box[1]),label,font=footer_font,fill=(255,255,255))
        canvas.save(output,format='PNG')
        bitmap.close(); page.close()
        return {'page_count':total,'width':canvas.width,'height':canvas.height}


if __name__ == '__main__':
    try:
        mode = sys.argv[4] if len(sys.argv)>4 else ''
        result = render(int(sys.argv[1]),int(sys.argv[2]),Path(sys.argv[3]),sample=mode=='sample',frame_source=mode=='sample-body')
        print(json.dumps(result,ensure_ascii=False))
    except Exception:
        print(json.dumps({'error':'PDF 无法预览，可能已加密、未写完整或格式异常；原文件保持原样'},ensure_ascii=False))
        raise SystemExit(2)
