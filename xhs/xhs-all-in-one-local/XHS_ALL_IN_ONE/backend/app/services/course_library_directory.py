"""Literal directory browsing. Reads names/stat only; never classifies or modifies sources."""
from contextlib import contextmanager
from pathlib import Path
import os
import re
import stat
from backend.app.services.course_library_paths import signature


def path_parts(relative: str):
    if not relative: return []
    parts = relative.split('/')
    if '\x00' in relative or any(part in {'', '.', '..'} for part in parts):
        raise ValueError('目录必须是题库内的相对路径')
    return parts


@contextmanager
def open_directory(root: Path, relative: str):
    parts = path_parts(relative)
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(root, flags)
    try:
        for part in parts:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd); fd = child
        yield fd
    finally: os.close(fd)


def natural_name(name):
    return [(0, int(piece)) if piece.isdigit() else (1, piece.casefold()) for piece in re.split(r'(\d+)', name)]


def read_directory(root: Path, relative: str):
    result = []
    with open_directory(root, relative) as fd, os.scandir(fd) as entries:
        for entry in entries:
            try: info = entry.stat(follow_symlinks=False)
            except FileNotFoundError: continue  # A concurrent rename is reflected on the next poll.
            kind = 'symlink' if stat.S_ISLNK(info.st_mode) else 'directory' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode) else 'other'
            path = '/'.join([relative, entry.name]) if relative else entry.name
            is_pdf = kind == 'file' and entry.name.lower().endswith('.pdf')
            # Match the existing PDF watch scope; browsing does not expand ingestion.
            index_eligible = is_pdf and not entry.name.startswith('~$') and not any(part.startswith('.') or part == '_资产归档管理' for part in path.split('/'))
            result.append({'name': entry.name, 'relative_path': path, 'kind': kind, 'is_pdf': is_pdf,
                           'index_eligible': index_eligible, 'size_bytes': info.st_size if kind == 'file' else None,
                           'mtime_ns': info.st_mtime_ns, 'signature': signature(info)})
    result.sort(key=lambda item: (item['kind'] != 'directory', natural_name(item['name']), item['name']))
    return result


def course_initial(entry):
    """Presentation hint from the literal folder name; never change archive metadata."""
    if entry['kind'] != 'directory': return None
    name = entry['name'].lstrip()
    return name[0].upper() if re.match(r'^[A-Za-z][A-Za-z _-]*\d', name) else None


def alphabetic_groups(entries, target_size=60):
    """Keep each letter whole, packing small adjacent letters near a soft target."""
    buckets = {}; other = []
    for entry in entries:
        letter = course_initial(entry)
        if letter: buckets.setdefault(letter, []).append(entry)
        else: other.append(entry)
    # A leaf/product directory should still show its PDFs and Word files together.
    if len(buckets) < 2: return []
    groups = []; pending = []; count = 0
    def flush():
        nonlocal pending, count
        if not pending: return
        first, last = pending[0]['initial'], pending[-1]['initial']
        groups.append({'key': first if first == last else f'{first}-{last}',
                       'label': first if first == last else f'{first}–{last}',
                       'letters': pending, 'count': count,
                       'items': [entry for letter in pending for entry in buckets[letter['initial']]]})
        pending = []; count = 0
    for letter, items in sorted(buckets.items()):
        if pending and count >= 24 and abs(count-target_size) <= abs(count+len(items)-target_size): flush()
        pending.append({'initial': letter, 'count': len(items)}); count += len(items)
        if count >= target_size: flush()
    flush()
    if len(groups) > 1 and groups[-1]['count'] < 24 and groups[-2]['count'] + groups[-1]['count'] <= 90:
        tail = groups.pop(); previous = groups[-1]
        previous['letters'] += tail['letters']; previous['count'] += tail['count']; previous['items'] += tail['items']
        first, last = previous['letters'][0]['initial'], previous['letters'][-1]['initial']
        previous['key'] = f'{first}-{last}'; previous['label'] = f'{first}–{last}'
    if other: groups.append({'key': 'other', 'label': '其他目录与文件', 'letters': [], 'count': len(other), 'items': other})
    return groups
