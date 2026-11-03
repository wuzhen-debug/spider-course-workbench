"""Normal image-note limits used by the official Creator publish editor."""
from __future__ import annotations


def utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le", errors="surrogatepass")) // 2


def creator_title_length(value: str) -> int:
    # Official module 96298/rQ counts UTF-16 units, not Python code points.
    encoded = value.encode("utf-16-le", errors="surrogatepass")
    weight = sum(2 if unit > 127 or unit == 94 else 1
                 for unit in (int.from_bytes(encoded[i:i + 2], "little")
                              for i in range(0, len(encoded), 2)))
    return (weight + 1) // 2


def validate_note_text(title: str, desc: str) -> None:
    if not title.strip():
        raise ValueError("请填写标题")
    count = creator_title_length(title)
    if count > 20:
        raise ValueError(f"标题按小红书规则为 {count} 字，最多支持 20 字")
    if utf16_length(desc) > 1000:
        raise ValueError("正文（含话题标记）最多支持 1000 字，请缩短后重试")
