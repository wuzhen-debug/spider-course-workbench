"""Bounded local text extraction in a separate PDFium process, using a read-only fd."""
import json
import os
import sys


def extract(fd, pages):
    import pypdfium2 as pdfium
    with os.fdopen(fd, 'rb', closefd=False) as stream, pdfium.PdfDocument(stream, autoclose=False) as document:
        total = len(document)
        if not total or total > 10000 or not 1 <= len(pages) <= 9 or any(p < 1 or p > total for p in pages):
            return {'error': '预览页码超出 PDF 范围（每次最多选择 9 页）'}
        result = []
        remaining = 18000
        for number in pages:
            page = document[number-1]
            textpage = page.get_textpage()
            count = textpage.count_chars()
            text = textpage.get_text_range(0, min(count, 4000)).replace('\x00', '').strip()[:remaining]
            result.append({'page': number, 'text': text, 'truncated': count > min(4000, remaining)})
            remaining -= len(text)
            textpage.close(); page.close()
        return {'page_count': total, 'pages': result}


if __name__ == '__main__':
    try:
        result = extract(int(sys.argv[1]), [int(n) for n in sys.argv[2].split(',')])
        print(json.dumps(result, ensure_ascii=False))
        if result.get('error'): raise SystemExit(2)
    except Exception:
        print(json.dumps({'error': 'PDF 文字读取失败；请检查文件是否加密或损坏'}, ensure_ascii=False))
        raise SystemExit(2)
