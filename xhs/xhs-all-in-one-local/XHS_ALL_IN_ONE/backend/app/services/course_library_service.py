"""Independent local read-only watcher. Never uses XHS, AI or job schedulers."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import threading
import time
import unicodedata
from sqlalchemy import insert, select
from backend.app.core.config import get_settings
from backend.app.core.database import SessionLocal
from backend.app.core.time import shanghai_now
from backend.app.models import User
from backend.app.models.course_center import CourseOffering, CourseMaterialProduct, CourseMaterialVersion
from backend.app.models.course_library import CourseLibraryRoot, CourseLibraryFile, CourseLibraryRevision
from backend.app.services.course_library_paths import classify, open_readonly, safe_path, signature


class SourceChanged(Exception):
    pass


class CourseLibraryWatcher:
    def __init__(self, root: Path, owner_id: int, factory=SessionLocal, stable_seconds=5, reconcile_seconds=60):
        self.root = root.absolute(); self.owner_id = owner_id; self.factory = factory
        self.stable_seconds = max(0, stable_seconds); self.reconcile_seconds = max(5, reconcile_seconds)
        self.stop_event = threading.Event(); self.wake = threading.Event(); self.lock = threading.Lock()
        self.dirty = set(); self.rescan_requested = True; self.pending = {}; self.root_id = None
        self.observer = None; self.thread = None; self.backend = "定期核对"

    def initialize(self):
        with self.factory() as db:
            if not db.get(User, self.owner_id): raise ValueError("本机题库索引所属用户不存在")
            row = db.scalar(select(CourseLibraryRoot).where(CourseLibraryRoot.user_id == self.owner_id, CourseLibraryRoot.path == str(self.root)))
            if row is None:
                row = CourseLibraryRoot(user_id=self.owner_id, path=str(self.root)); db.add(row); db.flush()
            self.root_id = row.id; row.status = "starting"; row.last_error = ""; db.commit()

    def notify(self, path, directory=False):
        with self.lock:
            if directory: self.rescan_requested = True
            else:
                try:
                    rel = str(Path(path).absolute().relative_to(self.root))
                    if rel.lower().endswith('.pdf'): self.dirty.add(rel)
                except ValueError: return
        self.wake.set()

    def request_scan(self):
        with self.lock: self.rescan_requested = True
        self.wake.set()

    def heartbeat(self, status="watching", error="", scanned=False):
        with self.factory() as db:
            row = db.get(CourseLibraryRoot, self.root_id)
            row.status = status; row.heartbeat_at = shanghai_now(); row.last_error = error
            row.watch_backend = self.backend
            if scanned: row.last_scan_at = shanghai_now()
            db.commit()

    def _values(self, relative, info):
        return dict(user_id=self.owner_id, root_id=self.root_id, relative_path=relative, filename=Path(relative).name,
            size_bytes=info.st_size, mtime_ns=info.st_mtime_ns, signature=signature(info), status="pending", **classify(relative))

    def _queue(self, relative, info, priority=0):
        remaining = max(0, self.stable_seconds - (time.time() - info.st_mtime))
        self.pending[relative] = (time.monotonic() + remaining, priority, -info.st_mtime_ns)

    def full_scan(self):
        # Only a complete readable traversal can mark an absent file missing.
        if not self.root.is_dir() or self.root.is_symlink():
            self.heartbeat("unavailable", "题库目录不可用，保留已有索引；恢复目录后会重试")
            return False
        found = {}; errors = []
        for parent, dirs, files in os.walk(self.root, followlinks=False, onerror=lambda e: errors.append(type(e).__name__)):
            if self.stop_event.is_set(): return False
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '_资产归档管理' and not (Path(parent)/d).is_symlink()]
            for name in files:
                if name.startswith(('.', '~$')) or not name.lower().endswith('.pdf'): continue
                path = Path(parent)/name
                try:
                    if path.is_symlink(): continue
                    info = path.stat()
                    if path.is_file(): found[str(path.relative_to(self.root))] = info
                except OSError: errors.append("文件暂不可读")
        with self.factory() as db:
            existing = {r.relative_path:r for r in db.scalars(select(CourseLibraryFile).where(CourseLibraryFile.root_id == self.root_id)).all()}
            additions = []
            for rel, info in found.items():
                old = existing.get(rel)
                if old is None:
                    additions.append(self._values(rel, info)); self._queue(rel, info, 1)
                elif old.signature != signature(info) or old.status == 'missing':
                    old.signature = signature(info); old.size_bytes = info.st_size; old.mtime_ns = info.st_mtime_ns
                    old.status = 'pending'; old.error = ''; self._queue(rel, info)
                else:
                    metadata = classify(rel)
                    changed = any(getattr(old,key)!=value for key,value in metadata.items())
                    if changed:
                        for key,value in metadata.items(): setattr(old,key,value)
                        old.status='pending';self._queue(rel,info,1)
                    elif old.status == 'pending' and rel not in self.pending: self._queue(rel, info, 1)
            for offset in range(0, len(additions), 500): db.execute(insert(CourseLibraryFile), additions[offset:offset+500])
            if not errors:
                for rel, old in existing.items():
                    if rel not in found:
                        old.status = 'missing'; old.error = '原文件未找到；索引和历史仍保留'
                        self.pending.pop(rel, None)
            db.commit()
        self.heartbeat("partial" if errors else "watching", "部分目录不可读，未把未发现文件批量标为丢失" if errors else "", scanned=True)
        return True

    def observe(self, relative):
        try:
            path = safe_path(self.root, relative); info = path.stat()
        except (OSError, ValueError):
            # Confirm deletion on the next complete traversal, rather than a
            # transient rename or a directory permission error.
            self.rescan_requested = True; return
        with self.factory() as db:
            row = db.scalar(select(CourseLibraryFile).where(CourseLibraryFile.root_id == self.root_id, CourseLibraryFile.relative_path == relative))
            if row is None: row = CourseLibraryFile(**self._values(relative, info)); db.add(row)
            elif row.signature == signature(info) and row.status == 'ready': return
            else:
                row.signature = signature(info); row.size_bytes = info.st_size; row.mtime_ns = info.st_mtime_ns
                row.status = 'pending'; row.error = ''
            db.commit()
        # Every event gets a quiet-write window, even if an editor preserves mtime.
        self.pending[relative] = (time.monotonic() + self.stable_seconds, 0, -info.st_mtime_ns)

    def _register_product(self, db, file, revision):
        if not (file.university and file.course_code and file.material_type): return
        product = db.get(CourseMaterialProduct, file.product_id) if file.product_id else None
        uni_key = unicodedata.normalize('NFKC', file.university).casefold().strip()
        course = db.scalar(select(CourseOffering).where(CourseOffering.user_id == self.owner_id,
            CourseOffering.university_key == uni_key, CourseOffering.code_key == file.course_code,
            CourseOffering.term_key == file.term, CourseOffering.is_demo.is_(False)))
        if course is None:
            course = CourseOffering(user_id=self.owner_id, university=file.university, university_key=uni_key,
                course_code=file.course_code, code_key=file.course_code, course_name=file.course_code, term=file.term,
                term_key=file.term, language="未标注", aliases=[], aliases_search="", is_demo=False,
                source_reference="题库目录识别", notes="本机只读索引；内容质检、样张使用权和上架状态待人工确认")
            db.add(course); db.flush()
        if product is None:
            product = CourseMaterialProduct(user_id=self.owner_id, course_id=course.id, title=Path(file.filename).stem[:240],
                material_type=file.material_type, coverage="题库 PDF 自动登记", owner="", listing_status="not_listed",
                seed_key=f"library-file-{self.root_id}-{file.id}", notes="仅登记本机资料；未自动确认内容质检或营销使用权")
            db.add(product); db.flush(); file.product_id = product.id; file.course_id = course.id
        elif product.seed_key == f"library-file-{self.root_id}-{file.id}":
            # Reconcile path-derived identity without overwriting product edits,
            # QA, listing status or any previous content revision.
            product.course_id=course.id;file.course_id=course.id
        if revision.version_id is None:
            version = CourseMaterialVersion(user_id=self.owner_id, product_id=product.id,
                version=f"PDF-{revision.id}-{revision.sha256[:10]}", language="未标注",
                source_reference=f"library://files/{file.id}/revisions/{revision.id}", sha256=revision.sha256,
                file_status="verified", qa_status="pending", notes="文件内容指纹已核对；不代表内容质检或可售确认")
            db.add(version); db.flush(); revision.version_id = version.id

    def index_one(self, relative):
        with self.factory() as db:
            file = db.scalar(select(CourseLibraryFile).where(CourseLibraryFile.root_id == self.root_id, CourseLibraryFile.relative_path == relative))
            if file is None or file.status != 'pending': return
            fd = open_readonly(self.root, relative)
            try:
                before = os.fstat(fd)
                if signature(before) != file.signature: raise SourceChanged()
                digest = hashlib.sha256(); header = os.read(fd, 1024); digest.update(header)
                if b'%PDF-' not in header: raise ValueError("文件缺少 PDF 标识，请检查是否尚未写完或格式异常")
                while chunk := os.read(fd, 1024*1024):
                    if self.stop_event.is_set(): raise SourceChanged()
                    digest.update(chunk)
                if signature(os.fstat(fd)) != file.signature or signature(safe_path(self.root, relative).stat()) != file.signature: raise SourceChanged()
            finally: os.close(fd)
            sha = digest.hexdigest()
            for key,value in classify(relative).items(): setattr(file,key,value)
            revision = db.scalar(select(CourseLibraryRevision).where(CourseLibraryRevision.file_id == file.id, CourseLibraryRevision.sha256 == sha))
            if revision is None:
                revision = CourseLibraryRevision(user_id=self.owner_id, file_id=file.id, sha256=sha,
                    size_bytes=before.st_size, mtime_ns=before.st_mtime_ns)
                db.add(revision); db.flush(); file.revision_count += 1
            file.current_revision_id = revision.id; file.status = 'ready'; file.error = ''
            file.updated_at = shanghai_now(); self._register_product(db, file, revision); db.commit()

    def process_ready(self, limit=24):
        now = time.monotonic(); ready = sorted((v[1],v[2],rel) for rel,v in self.pending.items() if v[0] <= now)
        for _,__,relative in ready[:limit]:
            if self.stop_event.is_set(): break
            self.pending.pop(relative, None)
            try: self.index_one(relative)
            except SourceChanged: self.notify(self.root/relative)
            except (OSError, ValueError):
                with self.factory() as db:
                    row = db.scalar(select(CourseLibraryFile).where(CourseLibraryFile.root_id == self.root_id, CourseLibraryFile.relative_path == relative))
                    if row: row.status = 'error'; row.error = 'PDF 暂不可读或格式异常，原文件保持原样；文件变化后会重试'; db.commit()
            except Exception:
                # Keep pending across DB contention; do not lose the work item.
                self.pending[relative] = (time.monotonic()+5, 0, 0)
                self.heartbeat('error', '索引暂未完成，正在保留记录并重试')
        return len(ready[:limit])

    def run(self):
        last_scan = 0; last_beat = 0
        while not self.stop_event.is_set():
            try:
                with self.lock:
                    rescan = self.rescan_requested; self.rescan_requested = False
                    changed = self.dirty; self.dirty = set()
                if rescan or time.monotonic()-last_scan >= self.reconcile_seconds:
                    self.full_scan(); last_scan = time.monotonic()
                for path in changed: self.observe(path)
                processed = self.process_ready()
                if time.monotonic()-last_beat >= 5:
                    with self.factory() as db: status = db.get(CourseLibraryRoot,self.root_id).status
                    if status not in {'unavailable','partial','error'}: self.heartbeat()
                    last_beat = time.monotonic()
                self.wake.wait(0.05 if processed else 1); self.wake.clear()
            except Exception:
                self.heartbeat('error', '题库扫描暂不可用；保留原索引，稍后重试')
                self.stop_event.wait(5)
        self.heartbeat('stopped', '本机平台已停止，重新启动后继续核对')

    def start(self):
        self.initialize()
        try:
            from watchdog.events import FileSystemEventHandler
            # PollingObserver avoids the native macOS FSEvents extension's
            # process abort in this installation. It never modifies the source.
            from watchdog.observers.polling import PollingObserver
            service = self
            class Handler(FileSystemEventHandler):
                def on_any_event(self, event):
                    if event.event_type not in {'created','modified','moved','deleted'}: return
                    service.notify(event.src_path, event.is_directory)
                    if getattr(event,'dest_path',None): service.notify(event.dest_path,event.is_directory)
            self.observer = PollingObserver(timeout=5); self.observer.schedule(Handler(),str(self.root),recursive=True); self.observer.start()
            self.backend = '5 秒目录轮询 + 定期核对'
        except (ImportError, OSError): self.backend = '定期核对（文件事件不可用）'
        self.thread = threading.Thread(target=self.run, name='course-pdf-library', daemon=True); self.thread.start()
        return self

    def stop(self):
        self.stop_event.set(); self.wake.set()
        if self.observer: self.observer.stop(); self.observer.join(timeout=3)
        if self.thread: self.thread.join(timeout=10)


_service = None


def start_course_library():
    global _service
    settings = get_settings()
    if not (settings.course_center_enabled and settings.course_library_enabled): return None
    if not settings.course_library_root or settings.course_library_owner_id <= 0: raise ValueError("题库监测需要明确目录和所属用户")
    _service = CourseLibraryWatcher(Path(settings.course_library_root), settings.course_library_owner_id,
        stable_seconds=settings.course_library_stable_seconds, reconcile_seconds=settings.course_library_reconcile_seconds).start()
    return _service


def request_library_scan():
    if _service: _service.request_scan(); return True
    return False


def stop_course_library(service):
    global _service
    if service: service.stop()
    _service = None
