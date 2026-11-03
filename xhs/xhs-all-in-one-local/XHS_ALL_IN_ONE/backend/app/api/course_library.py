"""Authenticated inventory and private page PNGs. No raw-PDF serving route."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session
from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.time import shanghai_now
from backend.app.models import User
from backend.app.models.course_library import CourseLibraryRoot, CourseLibraryFile, CourseLibraryRevision
from backend.app.services.course_library_paths import open_readonly, safe_path, signature
from backend.app.services.course_library_service import request_library_scan
from backend.app.services.course_library_directory import alphabetic_groups, course_initial, open_directory, read_directory

router = APIRouter(prefix='/course-center/library',tags=['course-library'])


def require_library(user: User = Depends(get_current_user)):
    settings = get_settings()
    if not (settings.course_center_enabled and settings.course_library_enabled) or settings.course_library_owner_id != user.id:
        raise HTTPException(404,'本账号的题库监测未启用')
    return settings


def root_for(db,user,settings):
    return db.scalar(select(CourseLibraryRoot).where(CourseLibraryRoot.user_id==user.id,CourseLibraryRoot.path==str(Path(settings.course_library_root).absolute())))


def owned_file(db,file_id,user,settings):
    file=db.get(CourseLibraryFile,file_id);root=root_for(db,user,settings)
    if file is None or file.user_id!=user.id or root is None or file.root_id!=root.id: raise HTTPException(404,'文件记录不存在')
    return file,root


def row_view(row):
    return {c.name:(getattr(row,c.name).isoformat() if isinstance(getattr(row,c.name),datetime) else getattr(row,c.name))
        for c in row.__table__.columns if c.name not in {'user_id','signature'}}


@router.get('/status')
def status(user: User=Depends(get_current_user),db: Session=Depends(get_db),settings=Depends(require_library)):
    root=root_for(db,user,settings)
    counts=dict(db.execute(select(CourseLibraryFile.status,func.count()).where(CourseLibraryFile.root_id==root.id).group_by(CourseLibraryFile.status)).all()) if root else {}
    query=select(CourseLibraryFile).where(CourseLibraryFile.root_id==root.id) if root else None
    def count(condition):
        return db.scalar(select(func.count()).select_from(query.where(condition).subquery())) if query is not None else 0
    age=(shanghai_now()-root.heartbeat_at).total_seconds() if root and root.heartbeat_at else None
    return {'enabled':True,'root':row_view(root) if root else None,'counts':counts,'total':sum(counts.values()),
        'products':count(CourseLibraryFile.product_id.is_not(None)),
        'needs_confirmation':count(CourseLibraryFile.classification_status=='needs_confirmation'),
        'updated_files':count(CourseLibraryFile.revision_count>1),
        'watcher_alive':age is not None and age<120 and root.status!='stopped',
        'stable_seconds':settings.course_library_stable_seconds,'reconcile_seconds':settings.course_library_reconcile_seconds,
        'publishing_enabled':False,'xhs_auto_ops_enabled':False,'original_files_read_only':True}


@router.post('/rescan')
def rescan(user: User=Depends(get_current_user),settings=Depends(require_library)):
    if not request_library_scan(): raise HTTPException(503,'本地监测未运行，请检查本机服务配置')
    return {'queued':True,'external_actions':0}


def filtered_files(root_id,user_id,q='',university='',state='',scope_university=None,scope_course=None,scope_type=None):
    # None is an unselected level; an empty string is a selected pending folder.
    if (scope_course is not None and scope_university is None) or (scope_type is not None and scope_course is None):
        raise HTTPException(422,'请按大学、课程代码、资料类型逐级选择目录')
    query=select(CourseLibraryFile).where(CourseLibraryFile.root_id==root_id,CourseLibraryFile.user_id==user_id)
    if q.strip():
        like=f'%{q.strip()}%'; query=query.where(or_(CourseLibraryFile.relative_path.ilike(like),CourseLibraryFile.course_code.ilike(like),CourseLibraryFile.university.ilike(like)))
    if university: query=query.where(CourseLibraryFile.university==university)
    for column,value in [(CourseLibraryFile.university,scope_university),(CourseLibraryFile.course_code,scope_course),(CourseLibraryFile.material_type,scope_type)]:
        if value is not None: query=query.where(column==value)
    if state=='needs_confirmation': query=query.where(CourseLibraryFile.classification_status=='needs_confirmation')
    elif state=='products': query=query.where(CourseLibraryFile.product_id.is_not(None))
    elif state=='updated': query=query.where(CourseLibraryFile.revision_count>1)
    elif state: query=query.where(CourseLibraryFile.status==state)
    return query


@router.get('/folders')
def folders(q:str='',state:str='',folder_q:str=Query('',max_length=200),
    scope_university:str|None=Query(None,max_length=180),scope_course:str|None=Query(None,max_length=40),scope_type:str|None=Query(None,max_length=80),
    page:int=Query(1,ge=1),page_size:int=Query(24,ge=1,le=100),
    user: User=Depends(get_current_user),db: Session=Depends(get_db),settings=Depends(require_library)):
    root=root_for(db,user,settings)
    depth=sum(value is not None for value in [scope_university,scope_course,scope_type])
    query=filtered_files(root.id if root else -1,user.id,q=q,state=state,scope_university=scope_university,scope_course=scope_course,scope_type=scope_type)
    if depth==3: return {'items':[],'total':0,'total_files':db.scalar(select(func.count()).select_from(query.subquery())),'depth':depth,'page':page,'page_size':page_size}
    columns=[CourseLibraryFile.university,CourseLibraryFile.course_code,CourseLibraryFile.material_type]
    pending_labels=['大学待确认','课程待确认','资料类型待确认']
    if folder_q.strip():
        text=folder_q.strip();condition=columns[depth].ilike(f'%{text}%')
        if text in pending_labels[depth]:condition=or_(condition,columns[depth]=='')
        query=query.where(condition)
    scoped=query.subquery();key=scoped.c[columns[depth].key]
    children=func.count(func.distinct(scoped.c[columns[depth+1].key])) if depth<2 else func.count()
    grouped=select(key.label('value'),func.count().label('file_count'),children.label('child_count'),
        func.sum(case((scoped.c.status=='error',1),else_=0)).label('error_count')).group_by(key)
    total=db.scalar(select(func.count()).select_from(grouped.subquery()))
    order=[case((key=='',1),else_=0)]
    if depth==0:order.append(func.count().desc())
    rows=db.execute(grouped.order_by(*order,key).offset((page-1)*page_size).limit(page_size)).mappings().all()
    return {'items':[{**dict(row),'label':row['value'] or pending_labels[depth],'pending':row['value']==''} for row in rows],
        'total':total,'total_files':db.scalar(select(func.count()).select_from(query.subquery())), 'depth':depth,'page':page,'page_size':page_size}


@router.get('/files')
def files(q:str='',university:str='',state:str='',page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),
    scope_university:str|None=Query(None,max_length=180),scope_course:str|None=Query(None,max_length=40),scope_type:str|None=Query(None,max_length=80),
    directory_path:str|None=Query(None,max_length=1600),
    user: User=Depends(get_current_user),db: Session=Depends(get_db),settings=Depends(require_library)):
    root=root_for(db,user,settings)
    query=filtered_files(root.id if root else -1,user.id,q,university,state,scope_university,scope_course,scope_type)
    if directory_path is not None:
        try:
            with open_directory(Path(settings.course_library_root).absolute(),directory_path): pass
        except ValueError: raise HTTPException(422,'请选择题库内的有效相对目录')
        except OSError: raise HTTPException(404,'该本地目录当前不可用，请返回题库根目录')
        if directory_path:
            prefix=directory_path+'/'
            query=query.where(func.substr(CourseLibraryFile.relative_path,1,len(prefix))==prefix)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    rows=db.scalars(query.order_by(CourseLibraryFile.mtime_ns.desc(),CourseLibraryFile.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return {'items':[row_view(r) for r in rows],'total':total,'page':page,'page_size':page_size}


@router.get('/universities')
def universities(user: User=Depends(get_current_user),db: Session=Depends(get_db),settings=Depends(require_library)):
    root=root_for(db,user,settings)
    return {'items':list(db.scalars(select(CourseLibraryFile.university).where(CourseLibraryFile.root_id==root.id,CourseLibraryFile.university!='').distinct().order_by(CourseLibraryFile.university)).all()) if root else []}


@router.get('/directory')
def directory(path:str=Query('',max_length=1600),q:str=Query('',max_length=200),page:int=Query(1,ge=1),page_size:int=Query(60,ge=1,le=200),
    alphabetic:bool=False,group_key:str=Query('',max_length=32),
    user:User=Depends(get_current_user),db:Session=Depends(get_db),settings=Depends(require_library)):
    try: entries=read_directory(Path(settings.course_library_root).absolute(),path)
    except ValueError: raise HTTPException(422,'请选择题库内的有效相对目录')
    except PermissionError: raise HTTPException(403,'该本地目录当前不可读取；原文件和已有登记保持原样')
    except OSError: raise HTTPException(404 if path else 503,'本地目录已移动、重命名或当前不可用，请返回上一级或题库根目录')
    folder_count=sum(e['kind']=='directory' for e in entries);file_count=len(entries)-folder_count
    pdf_count=sum(e['is_pdf'] for e in entries);total_entries=len(entries)
    if q: entries=[entry for entry in entries if q.casefold() in entry['name'].casefold()]
    total=len(entries);groups=[];active_group=''
    if alphabetic:
        groups=alphabetic_groups(entries)
        if groups:
            if group_key=='all': active_group='all'
            else:
                selected=next((group for group in groups if group['key']==group_key),None)
                if selected is None and group_key and group_key[0] in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
                    selected=next((group for group in groups if any(letter['initial']==group_key[0] for letter in group['letters'])),None)
                selected=selected or groups[0];active_group=selected['key'];entries=selected['items']
        for entry in entries: entry['course_initial']=course_initial(entry)
    else: entries=entries[(page-1)*page_size:page*page_size]
    root=root_for(db,user,settings);paths=[e['relative_path'] for e in entries if e['index_eligible']]
    indexed={}
    if root:
        for offset in range(0,len(paths),300):
            indexed.update({row.relative_path:row for row in db.scalars(select(CourseLibraryFile).where(CourseLibraryFile.root_id==root.id,CourseLibraryFile.user_id==user.id,CourseLibraryFile.relative_path.in_(paths[offset:offset+300]))).all()})
    for entry in entries:
        row=indexed.get(entry['relative_path']);entry.update(file_id=row.id if row else None,index_status=row.status if row else None,
            can_preview=bool(row and row.status=='ready' and row.signature==entry['signature']),revision_count=row.revision_count if row else 0)
        entry.pop('signature')
    return JSONResponse({'path':path,'parent_path':'/'.join(path.split('/')[:-1]) if path else None,'root_name':Path(settings.course_library_root).name,
        'items':entries,'total':total,'total_entries':total_entries,'folder_count':folder_count,'file_count':file_count,'pdf_count':pdf_count,
        'page':1 if alphabetic else page,'page_size':len(entries) if alphabetic else page_size,
        'groups':[{k:v for k,v in group.items() if k!='items'} for group in groups],'active_group':active_group,'group_target':60,
        'synced_at':shanghai_now().isoformat(),'refresh_seconds':5,'original_files_read_only':True},headers={'Cache-Control':'private, no-store'})


@router.get('/files/{file_id}')
def detail(file_id:int,user: User=Depends(get_current_user),db: Session=Depends(get_db),settings=Depends(require_library)):
    file,root=owned_file(db,file_id,user,settings)
    revisions=db.scalars(select(CourseLibraryRevision).where(CourseLibraryRevision.file_id==file.id,CourseLibraryRevision.user_id==user.id).order_by(CourseLibraryRevision.id.desc())).all()
    return {'file':row_view(file),'revisions':[row_view(r) for r in revisions],'source_path':str(Path(root.path)/file.relative_path),
        'history_note':'保留每次内容变化的指纹和版本记录；不复制原 PDF。旧版本内容变化后不保证仍可预览。'}


@router.get('/files/{file_id}/preview')
def preview(file_id:int,page:int=Query(1,ge=1,le=100000),revision_id:int|None=None,
    user: User=Depends(get_current_user),db: Session=Depends(get_db),settings=Depends(require_library)):
    file,root=owned_file(db,file_id,user,settings)
    revision=db.get(CourseLibraryRevision,revision_id or file.current_revision_id) if (revision_id or file.current_revision_id) else None
    if revision is None or revision.file_id!=file.id or revision.user_id!=user.id: raise HTTPException(404,'尚未完成文件指纹登记')
    if revision.id!=file.current_revision_id: raise HTTPException(409,'原 PDF 已更新；旧版本只保留指纹记录，请预览当前版本')
    if file.status!='ready': raise HTTPException(409,'原文件正在写入、待核对或不可用，请稍后刷新')
    fd=None; temporary=None
    try:
        fd=open_readonly(Path(root.path),file.relative_path)
        if signature(os.fstat(fd))!=file.signature: raise HTTPException(409,'原文件已有变化，等待本机监测完成后再预览')
        if revision.page_count is not None and page>revision.page_count: raise HTTPException(400,'页码超出范围')
        cache=settings.storage_dir/'course-library-previews'/str(user.id)
        cache.mkdir(parents=True,exist_ok=True)
        output=cache/f'{revision.sha256}-{page}-v2.png'
        # Identical PDFs at different paths may share a PNG cache, but each
        # content record still needs its own page count and preview metadata.
        if not output.is_file() or revision.page_count is None:
            handle,temporary=tempfile.mkstemp(prefix='render-',suffix='.png',dir=cache);os.close(handle)
            result=subprocess.run([sys.executable,'-m','backend.app.services.course_pdf_renderer',str(fd),str(page),temporary],
                pass_fds=(fd,),capture_output=True,text=True,timeout=25)
            try: meta=json.loads(result.stdout)
            except (ValueError,TypeError): meta={'error':'PDF 预览未完成，请检查文件格式'}
            if 'page_count' in meta: revision.page_count=meta['page_count']
            if result.returncode!=0 or meta.get('error'):
                if meta.get('page_count') and page>meta['page_count']: db.commit(); raise HTTPException(400,'页码超出范围')
                revision.pdf_status='unavailable';revision.preview_error=meta.get('error','PDF 暂不可预览');db.commit()
                raise HTTPException(422,revision.preview_error)
            if signature(os.fstat(fd))!=file.signature or signature(safe_path(Path(root.path),file.relative_path).stat())!=file.signature:
                raise HTTPException(409,'预览期间原文件已更新，请等待重新入库')
            os.replace(temporary,output);temporary=None
            revision.pdf_status='ready';revision.preview_error='';db.commit()
        return FileResponse(output,media_type='image/png',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
    except subprocess.TimeoutExpired: raise HTTPException(422,'该 PDF 渲染超时，原文件保持原样；可尝试其他页')
    except (OSError,ValueError): raise HTTPException(409,'原文件当前不可读，索引及历史仍保留')
    finally:
        if fd is not None: os.close(fd)
        if temporary and Path(temporary).exists(): Path(temporary).unlink()
