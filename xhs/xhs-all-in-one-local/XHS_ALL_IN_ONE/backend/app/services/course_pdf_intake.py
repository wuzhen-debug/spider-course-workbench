"""Bounded, read-only PDF text intake worker. No OCR, files or network writes."""
import json
import os
import sys

MAX_PAGES = 120
MAX_PAGE_CHARS = 4000
MAX_CHARS = 120000


def extract(fd):
    import pypdfium2 as pdfium
    with os.fdopen(fd, 'rb', closefd=False) as stream, pdfium.PdfDocument(stream, autoclose=False) as pdf:
        total = len(pdf)
        if not total or total > 10000:
            return {'error': 'PDF页数不在支持范围内，未读取或外发内容'}
        selected = list(range(1, total + 1)) if total <= MAX_PAGES else sorted(
            {1, 2, 3, 4, *[5 + round(i * (total - 5) / (MAX_PAGES - 5)) for i in range(MAX_PAGES - 4)]})
        pages = []
        remaining = MAX_CHARS
        truncated = total > len(selected)
        for n in selected:
            if remaining <= 0:
                truncated = True
                break
            page = pdf[n - 1]
            text = page.get_textpage()
            count = text.count_chars()
            limit = min(MAX_PAGE_CHARS, remaining)
            value = text.get_text_range(0, min(count, limit)).replace('\x00', '').strip()
            cut = count > limit
            truncated = truncated or cut
            pages.append({'page': n, 'text': value, 'truncated': cut, 'original_chars': count})
            remaining -= len(value)
            text.close(); page.close()
        return {'page_count': total, 'pages': pages, 'local_truncated': truncated,
                'limits': {'pages': MAX_PAGES, 'page_chars': MAX_PAGE_CHARS, 'total_chars': MAX_CHARS}}


if __name__ == '__main__':
    try:
        result = extract(int(sys.argv[1]))
        print(json.dumps(result, ensure_ascii=False))
        if result.get('error'):
            raise SystemExit(2)
    except Exception:
        print(json.dumps({'error': 'PDF文字读取失败，请检查加密或损坏；原件保持不变'}, ensure_ascii=False))
        raise SystemExit(2)
