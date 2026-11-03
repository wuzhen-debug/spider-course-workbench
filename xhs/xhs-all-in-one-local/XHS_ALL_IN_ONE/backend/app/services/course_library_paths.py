"""Directory evidence only. No web, AI, moves, renames or edits."""
from pathlib import Path
import os
import re
import stat
import unicodedata

TOP_SCHOOLS = {"01USYD":"悉尼大学", "02墨大":"墨尔本大学", "03UNSW":"新南威尔士大学",
    "04阿德莱德大学":"阿德莱德大学", "05澳洲国立大学":"澳洲国立大学", "06昆士兰大学":"昆士兰大学",
    "07悉尼科技大学":"悉尼科技大学", "08莫那什大学":"莫那什大学", "09麦考瑞大学":"麦考瑞大学",
    "10奥克兰大学":"奥克兰大学", "12怀卡特大学":"怀卡特大学", "13西澳大学":"西澳大学",
    "LSE":"伦敦政治经济学院", "RMIT":"RMIT", "香港大学HKU":"香港大学"}
NESTED_SCHOOLS = {"1.曼彻斯特大学":"曼彻斯特大学", "2.伦敦大学学院UCL":"伦敦大学学院",
    "3.格拉斯哥大学":"格拉斯哥大学", "考文垂大学Coventry":"考文垂大学", "伦敦政治经济学院":"伦敦政治经济学院",
    "USC":"南加州大学", "11纽约大学":"纽约大学", "伦敦国王学院KCL":"伦敦国王学院"}
TYPES = ["预习讲义", "学期跟课讲义", "跟课练习", "期中复习讲义", "期末复习讲义", "期中模拟卷", "期末模拟卷", "专项练习与题库", "Cheat Sheet", "Assignment Guide", "答案解析"]
TYPE_ALIASES = {re.sub(r"[\s_-]", "", x).casefold():x for x in TYPES}
TYPE_ALIASES.update({"cheatsheets":"Cheat Sheet", "专项练习":"专项练习与题库", "题库":"专项练习与题库", "答案":"答案解析"})


def classify(relative_path: str):
    parts = Path(relative_path).parts
    school = ""; start = 1
    if parts[0] in TOP_SCHOOLS: school = TOP_SCHOOLS[parts[0]]
    elif parts[0] in {"000英国", "美国"} and len(parts) > 2:
        start = 2; name = parts[1]
        school = NESTED_SCHOOLS.get(name, name if name.endswith("大学") else "")
    elif parts[0].endswith("大学") and parts[0] not in {"培养方案"}: school = parts[0]
    codes = []
    for part in parts[start:-1]:
        normalized = unicodedata.normalize("NFKC", part).strip().upper()
        match = re.fullmatch(r"([A-Z]{2,12}(?:-[A-Z]{1,5})?[ _-]?\d[A-Z0-9]{2,8})(?:\s+[^\d].*)?", normalized)
        if match: codes.append(re.sub(r"\s+", "", match.group(1)))
    code = codes[0] if len(set(codes)) == 1 else ""
    material = ""; type_source = ""
    for part in parts[start:-1]:
        key = re.sub(r"[\s_-]", "", re.sub(r"^\d+[_.\s-]*", "", part)).casefold()
        if key in TYPE_ALIASES: material = TYPE_ALIASES[key]; type_source = "资料类型目录"
    filename = parts[-1]
    if not material:
        for pattern, label in [(r"cheat[ _-]?sheet", "Cheat Sheet"), (r"assignment[ _-]?guide", "Assignment Guide"),
            (r"midterm[ _-]?mock|期中模拟", "期中模拟卷"), (r"final[ _-]?mock|期末模拟", "期末模拟卷"),
            (r"topic[ _-]?practice|专项练习", "专项练习与题库"), (r"follow[ _-]?along|学期跟课讲义", "学期跟课讲义"),
            (r"期末复习讲义|final[ _-]?revision", "期末复习讲义"), (r"期中复习讲义|midterm[ _-]?revision", "期中复习讲义")]:
            if re.search(pattern, filename, re.I): material = label; type_source = "明确文件名关键词"; break
    terms = {s.upper() for s in re.findall(r"(?<![A-Za-z0-9])P?((?:20)?\d{2}(?:-\d{2})?(?:S[12]|T[123]|FY|AT|ST|WT|MT|LT))(?![A-Za-z0-9])", filename, re.I)}
    term = next(iter(terms)) if len(terms) == 1 else "未标注"
    if re.match(r"^\d{2}(?!\d)", term): term = "20" + term
    missing = [label for label,value in [("大学目录",school),("唯一课程目录",code),("资料类型",material)] if not value]
    return dict(university=school, course_code=code, term=term, material_type=material,
        classification_status="path_identified" if not missing else "needs_confirmation",
        classification_reason=("按题库目录识别；" + type_source + "；未核定内容、使用权或上架状态") if not missing else "待确认：" + "、".join(missing))


def signature(info):
    return f"{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}"


def safe_path(root: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or not rel.parts or any(p in {"..", "."} or p.startswith(".") or p == "_资产归档管理" for p in rel.parts):
        raise ValueError("不允许的文件路径")
    if root.is_symlink() or not root.is_dir(): raise ValueError("题库目录当前不可用")
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink(): raise ValueError("不读取符号链接")
    if current.suffix.lower() != ".pdf" or not current.resolve().is_relative_to(root.resolve()): raise ValueError("文件不在题库范围")
    return current


def open_readonly(root: Path, relative: str):
    path = safe_path(root, relative)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    if not stat.S_ISREG(os.fstat(fd).st_mode): os.close(fd); raise ValueError("不是普通 PDF 文件")
    return fd
