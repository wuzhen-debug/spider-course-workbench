"""Bind an exported review to its owned, unchanged PDF before manual preview."""
import hashlib
import hmac
import json
import os
import time
from fastapi import HTTPException
from backend.app.api.course_library_drafts import stable_source,unchanged
from backend.app.models.course_platform_pair import CoursePlatformPair
from backend.app.services.course_brands import saved_brand


def source_digest(draft):
    value={k:draft[k] for k in ['brand_id','source','images']}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def prepare_publish_source(draft_id,user,db,settings,connector):
    draft=connector.request('GET',f'/bridge/drafts/{draft_id}',user.id)
    source=draft.get('source') or {}
    if source.get('origin')!='spider-pdf-dual':
        if not draft.get('publishing_supported'):raise HTTPException(422,'这份历史草稿未关联可核对的 PDF，请从双平台稿重新导入；原稿保留')
        return {'ready':True,'draft_id':draft_id,'source_sha256':source['sha256']}
    pair=db.get(CoursePlatformPair,source.get('platform_pair_id'))
    if pair is None or pair.user_id!=user.id:raise HTTPException(404,'双平台来源不存在')
    if (source.get('file_id'),source.get('revision_id'))!=(pair.file_id,pair.revision_id):
        raise HTTPException(409,'商品与 PDF 来源版本未匹配，请重新导入待审核稿')
    exported=next((v for v in pair.xianyu_history if v.get('service_draft_id')==draft_id and
        v.get('exported_from_version')==source.get('platform_pair_version')),None)
    if exported is None:raise HTTPException(409,'未找到这份闲鱼商品的双平台导入记录，未准备发布')
    expected=exported['source']
    keys=['filename','university','course_code','term','material_type','sha256','page_count','revision_id','preview_layout','preview_brand']
    if any(source.get(k)!=expected.get(k) for k in keys) or saved_brand(expected['preview_brand'])['id']!=draft['brand_id']:
        raise HTTPException(409,'商品课程、品牌或 PDF 指纹与原导入记录不一致')
    images=[{k:im[k] for k in ['page','sha256','width','height']} for im in exported['images']]
    if images!=draft['images']:raise HTTPException(409,'商品样张与原导入记录未匹配，请重新核对')
    file,root,revision,fd=stable_source(db,user,settings,pair.file_id,pair.revision_id)
    try:
        if revision.sha256!=source['sha256']:raise HTTPException(409,'PDF 指纹与商品来源未匹配')
        # The absolute path stays on the authenticated localhost bridge. It is
        # never added to a public draft, frontend response or frozen preview.
        binding={'row_version':draft['row_version'],'file_id':pair.file_id,'revision_id':pair.revision_id,
            'platform_pair_id':pair.id,'platform_pair_version':source['platform_pair_version'],
            'source_digest':source_digest(draft),'sha256':revision.sha256,
            'library_root':root.path,'relative_path':file.relative_path,'issued_at':int(time.time())}
        proof=json.dumps({'owner':user.id,'draft_id':draft_id,'binding':binding},sort_keys=True,ensure_ascii=False).encode()
        binding['signature']=hmac.new(connector.config['bridge_token'].encode(),proof,hashlib.sha256).hexdigest()
        unchanged(file,root,fd)
        return connector.request('PUT',f'/bridge/drafts/{draft_id}/publish-source',user.id,payload=binding)
    finally:os.close(fd)
