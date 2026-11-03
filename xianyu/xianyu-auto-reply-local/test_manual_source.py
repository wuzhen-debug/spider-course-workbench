"""Synthetic source bindings; no real library/account/network operations."""
from copy import deepcopy
import hashlib
import json
import time
import pytest
from fastapi import HTTPException
from manual_source import SourceBinding,checked_pdf,digest_source,save_source,load_source,binding_signature


@pytest.fixture
def bound(tmp_path):
    root=tmp_path/'library';root.mkdir();pdf=root/'ECON10003.pdf';pdf.write_bytes(b'%PDF-synthetic source fixture')
    draft={'id':2,'row_version':4,'brand_id':'xingtu','source':{'origin':'spider-pdf-dual','file_id':1,'revision_id':2,'platform_pair_id':3,'platform_pair_version':2,
        'sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),'page_count':70,'university':'墨尔本大学','course_code':'ECON10003','preview_brand':{'id':'xingtu'}},
        'images':[{'page':n,'sha256':str(n)*64,'width':1200,'height':1800} for n in range(1,10)]}
    config={'bridge_token':'synthetic-signing-key','owner_user_id':1}
    data={'row_version':4,'library_root':str(root),'relative_path':pdf.name,'source_digest':digest_source(draft),'issued_at':int(time.time()),
        **{k:draft['source'][k] for k in ['file_id','revision_id','platform_pair_id','platform_pair_version','sha256']}}
    binding=SourceBinding(**data,signature=binding_signature(config['bridge_token'],1,draft['id'],data))
    return tmp_path/'private-bindings',config,pdf,draft,binding


def test_save_read_reverify_and_keep_private_history(bound):
    storage,config,pdf,draft,binding=bound
    result=save_source(storage,1,config,draft,binding)
    assert result['ready'] and str(pdf.parent) not in json.dumps(result)
    assert load_source(storage,1,config,draft)==pdf
    assert len(list((storage/'1/2').glob('*.json')))==2
    save_source(storage,1,config,draft,binding)
    assert len(list((storage/'1/2').glob('*.json')))==2
    assert (storage/'1/2/current.json').stat().st_mode&0o777==0o600
    changed=deepcopy(draft);changed['row_version']=5;changed['description']='Allowed independent copy edit'
    assert load_source(storage,1,config,changed)==pdf
    pdf.write_bytes(b'%PDF-source changed')
    with pytest.raises(HTTPException) as error:load_source(storage,1,config,draft)
    assert error.value.status_code==409


@pytest.mark.parametrize('change',['traversal','absolute','root','symlink','source','image','brand','page','row_version'])
def test_paths_identity_images_brand_and_version_fail_closed(bound,change):
    storage,config,pdf,draft,binding=bound;value=binding.model_dump()
    if change=='traversal':value['relative_path']='../library/ECON10003.pdf'
    elif change=='absolute':value['relative_path']=str(pdf)
    elif change=='root':value['library_root']=str(pdf.parent.parent)
    elif change=='symlink':
        link=pdf.parent/'alias.pdf';link.symlink_to(pdf);value['relative_path']=link.name
    elif change=='source':draft['source']['file_id']=99
    elif change=='image':draft['images'][0]['sha256']='f'*64
    elif change=='brand':draft['brand_id']='wenguo'
    elif change=='page':draft['images'][0]['page']=99;value['source_digest']=digest_source(draft)
    else:value['row_version']=3
    value['signature']=binding_signature(config['bridge_token'],1,draft['id'],value)
    with pytest.raises(HTTPException):save_source(storage,1,config,draft,SourceBinding(**value))
    assert not storage.exists()


def test_unregistered_source_and_wrong_owner_cannot_reuse_binding(bound):
    storage,config,pdf,draft,binding=bound
    with pytest.raises(HTTPException):load_source(storage,1,config,draft)
    save_source(storage,1,config,draft,binding)
    with pytest.raises(HTTPException):load_source(storage,2,config,draft)


@pytest.mark.parametrize('change',['signature','draft','owner','expiry','path_after_signature'])
def test_signature_binds_exact_draft_file_owner_and_fresh_request(bound,change):
    storage,config,pdf,draft,binding=bound;data=binding.model_dump();owner=1
    if change=='signature':data['signature']='f'*64
    elif change=='draft':draft['id']=99
    elif change=='owner':owner=2
    elif change=='path_after_signature':data['relative_path']='other.pdf'
    else:data['issued_at']-=600;data['signature']=binding_signature(config['bridge_token'],1,draft['id'],data)
    with pytest.raises(HTTPException):save_source(storage,owner,config,draft,SourceBinding(**data))
    assert not storage.exists()
