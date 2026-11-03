"""Bounded Goofish transport for a human-approved single listing.

Protocol fields follow the pinned AGPL-3.0 upstream's personal/direct publisher,
category and media modules. This client intentionally has no password login,
account enablement, message, order, delivery, scheduler, or write retry code.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

import httpx
from PIL import Image

ROOT=Path(__file__).resolve().parent
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36'
READ_APIS={
    'mtop.idle.pc.backend.idleitem.preget':'1.0',
    'mtop.idle.pc.idleitem.preget':'1.0',
    'mtop.taobao.idle.kgraph.pc.property.recommend':'2.0',
    'mtop.taobao.idle.pc.detail':'1.0',
}
WRITE_APIS={'personal':'mtop.idle.pc.idleitem.publish','shop':'mtop.idle.pc.backend.idleitem.publish'}
UPLOAD_URL='https://stream-upload.goofish.com/api/upload.api?floderId=0&appkey=fleamarket&_input_charset=utf-8'
INVALID_MAP_LOCATION='FAIL_BIZ_ITEM_EDIT_INVALID_MAP_LOCATION'
LOCATION_REJECTION_MESSAGE='闲鱼拒绝了商品所在地，商品未发布；请重新检索所在地并核对后再确认发布'


class GatewayError(Exception):
    def __init__(self,message,code='PLATFORM_ERROR',*,unknown=False):
        super().__init__(message);self.message=message;self.code=code;self.unknown=unknown


def cookie_map(value):
    return dict(part.strip().split('=',1) for part in value.split(';') if '=' in part)


def safe_code(value):
    value=str(value).split('::',1)[0]
    return value if re.fullmatch(r'[A-Z0-9_]{1,100}',value) else 'PLATFORM_ERROR'


def response_has_item_reference(value):
    if isinstance(value,dict):
        return any((str(key).lower() in {'itemid','item_id','idleitemid'} and bool(current)) or
            response_has_item_reference(current) for key,current in value.items())
    if isinstance(value,list):return any(response_has_item_reference(item) for item in value)
    return isinstance(value,str) and ('goofish.com/item' in value or value.lstrip().startswith(('{','[')))


def parse_categories(response):
    """Return only real platform options; no invented category IDs or labels."""
    data=response.get('data') or {};cards=data.get('cardList') or []
    if isinstance(cards,str):
        try:cards=json.loads(cards)
        except ValueError:cards=[]
    cards=[c['cardData'] for c in cards if isinstance(c,dict) and isinstance(c.get('cardData'),dict)]
    categories=[];properties=[]
    for card in cards:
        pid=str(card.get('propertyId') or '');name=str(card.get('propertyName') or '')
        options=[]
        for value in card.get('valuesList') or []:
            if not isinstance(value,dict):continue
            t=value.get('transportData') or {}
            if not isinstance(t,dict):t={}
            label=str(value.get('catName') or value.get('text') or value.get('valueName') or t.get('valueName') or t.get('text') or '')
            if not label and '##' in str(value.get('properties') or t.get('properties') or ''):
                label=str(value.get('properties') or t.get('properties')).rsplit('##',1)[-1]
            if not label:continue
            if pid=='-10000':
                item={'cat_id':str(value.get('catId') or t.get('catId') or ''),
                    'cat_name':label,'channel_cat_id':str(value.get('channelCatId') or t.get('channelCateId') or ''),
                    'channel_cat_name':str(value.get('channelCatName') or t.get('channelCateName') or label),
                    'tb_cat_id':str(value.get('tbCatId') or t.get('tbCatId') or ''),
                    'leaf_id':str(value.get('leafId') or t.get('leafId') or ''),
                    'selected':str(value.get('isClicked') or value.get('isUserClick') or '') in {'1','true','True'}}
                categories.append(item)
            else:
                vid=str(value.get('valueId') or t.get('valueId') or '')
                options.append({'property_id':pid,'property_name':name,'value_id':vid,
                    'value_name':label,'properties':str(value.get('properties') or t.get('properties') or '')})
        if pid and pid!='-10000' and name:
            properties.append({'property_id':pid,'property_name':name,'options':options,
                'multiple':str(card.get('isMultiple') or '').lower() in {'1','true'},
                'required':str(card.get('required') or card.get('isRequired') or '').lower() in {'1','true'}})
    prediction=data.get('categoryPredictResult') or {}
    if isinstance(prediction,str):
        try:prediction=json.loads(prediction)
        except ValueError:prediction={}
    if isinstance(prediction,dict):
        # Fill a prediction only when a real candidate positively matches.
        pred={key:str(prediction.get(k) or prediction.get(alt) or '') for key,k,alt in [
            ('cat_id','catId','categoryId'),('channel_cat_id','channelCatId','channelCategoryId'),
            ('tb_cat_id','tbCatId','taobaoCategoryId'),('cat_name','catName','categoryName')]}
        for c in categories:
            comparable=[key for key in ['cat_id','channel_cat_id','tb_cat_id'] if c[key] and pred[key]]
            if ((comparable and all(c[key]==pred[key] for key in comparable)) or
                (not comparable and pred['cat_name'] and c['cat_name']==pred['cat_name'])):
                for key in ['cat_id','channel_cat_id','tb_cat_id']:c[key]=c[key] or pred[key]
                break
    return {'categories':categories,'properties':properties,'cards':cards}


def category_selection(cards,category):
    """Pure upstream selection helper, with no HTTP or database imports."""
    from app.services.platform_category_selection import build_category_selection
    return build_category_selection(cards,category)


def parse_capability(raw):
    c=raw.get('commissionConfig') or {};url=str(c.get('tipUrl') or '')
    title=str(c.get('commissionTitle') or c.get('defaultCommissionTitle') or '')
    if 'fish-shop-service-fee-rule' in url or '鱼小铺' in title:mode='shop'
    elif 'fish-seller-service-fee-rule' in url or c.get('defaultCommissionTitle')=='基础软件服务费':mode='personal'
    else:mode=None
    return {'mode':mode,'commission':{key:str(c.get(key) or '') for key in
        ['commissionTitle','defaultCommissionTitle','commissionTips','percent','maxCommission','tipUrl']}}


def listing_payload(snapshot,images,unique_code):
    d=snapshot['draft'];settings=snapshot['settings'];category=settings['category']
    if not location_is_valid(settings['location']):raise GatewayError('所在地尚未通过区县校验，请重新检索','INVALID_LOCAL_LOCATION')
    cents=str(int(Decimal(d['price'])*100))
    labels=[{'channelCateName':category['channel_cat_name'],'valueId':None,
        'channelCateId':category['channel_cat_id'],'valueName':None,'tbCatId':category['tb_cat_id'],
        'subPropertyId':None,'labelType':'common','subValueId':None,'labelId':None,
        'propertyName':'分类','isUserClick':'1','isUserCancel':None,'from':'newPublishChoice',
        'propertyId':'-10000','labelFrom':'newPublish','text':category['cat_name'],
        'properties':f'-10000##分类:{category["channel_cat_id"]}##{category["cat_name"]}'}]
    for value in settings['attributes']:
        labels.append({**{k:None for k in ['subPropertyId','subValueId','labelId','isUserCancel']},
            'channelCateName':category['channel_cat_name'],'channelCateId':category['channel_cat_id'],
            'tbCatId':category['tb_cat_id'],'valueId':value['value_id'],'valueName':value['value_name'],
            'propertyId':value['property_id'],'propertyName':value['property_name'],'labelType':'common',
            'isUserClick':'1','from':'newPublishChoice','labelFrom':'newPublish','text':value['value_name'],
            'properties':value['properties'] or f'{value["property_id"]}##{value["property_name"]}:{value["value_id"]}##{value["value_name"]}'})
    mode=snapshot['capability']['mode']
    result={'freebies':False,'itemTypeStr':'b','quantity':1 if mode=='shop' else '1','simpleItem':'true',
        'imageInfoDOList':images,'itemTextDTO':{'desc':d['description'],'title':d['title'],'titleDescSeparate':True},
        'itemLabelExtList':labels,'itemPriceDTO':{'origPriceInCent':cents,'priceInCent':cents},
        'userRightsProtocols':[{'enable':False,'serviceCode':code} for code in
            ['FAST_DELIVERY_48_HOUR','FAST_DELIVERY_24_HOUR','NONCONFORMITY_FREE_REFUND']] if mode=='shop' else [],
        'itemPostFeeDTO':{'canFreeShipping':False,'supportFreight':False,'onlyTakeSelf':False},
        'itemAddrDTO':settings['location']['dto'],'defaultPrice':False,
        'itemCatDTO':{'catId':category['cat_id'],'catName':category['cat_name'],
            'channelCatId':category['channel_cat_id'],'tbCatId':category['tb_cat_id']},
        'uniqueCode':unique_code,'sourceId':'pcMainPublish' if mode=='personal' else 'pcBackendPublish',
        'bizcode':'pcMainPublish','publishScene':'pcMainPublish' if mode=='personal' else 'pcBackendPublish'}
    if mode=='shop':result['itemCatDTO']['leafId']=category['leaf_id']
    return result


class GoofishGateway:
    def __init__(self,cookie,account_id):
        self.cookie=cookie.replace('\r','').replace('\n','');self.account_id=account_id
        if cookie_map(self.cookie).get('unb')!=account_id:raise GatewayError('账号身份不一致，请重新扫码','ACCOUNT_MISMATCH')

    def _merge(self,response):
        values=cookie_map(self.cookie)
        for cookie in response.cookies.jar:values[cookie.name]=cookie.value
        if values.get('unb')!=self.account_id:raise GatewayError('平台返回的账号身份变化，请重新扫码','ACCOUNT_MISMATCH')
        self.cookie='; '.join(f'{k}={v}' for k,v in values.items())

    async def _call(self,api,version,data,*,seller=False,write=False):
        attempts=1 if write else 2
        for attempt in range(attempts):
            t=str(int(time.time()*1000));token=cookie_map(self.cookie).get('_m_h5_tk','').split('_')[0]
            body=json.dumps(data,ensure_ascii=False,separators=(',',':'))
            sign=hashlib.md5(f'{token}&{t}&34839810&{body}'.encode()).hexdigest()
            params={'jsv':'2.7.2','appKey':'34839810','t':t,'sign':sign,'v':version,
                'type':'originaljson','accountSite':'xianyu','dataType':'json','timeout':'20000',
                'api':api,'sessionOption':'AutoLoginOnly','spm_cnt':'a21107h.42826273.0.0' if seller else 'a21ybx.publish.0.0'}
            origin='https://seller.goofish.com' if seller else 'https://www.goofish.com'
            headers={'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded',
                'Origin':origin,'Referer':origin+'/?site=COMMONPRO' if seller else origin+'/publish',
                'User-Agent':UA,'Cookie':self.cookie}
            if seller:params['idle_site_biz_code']='COMMONPRO';headers['idle_site_biz_code']='COMMONPRO'
            try:
                async with httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=30) as client:
                    r=await client.post(f'https://h5api.m.goofish.com/h5/{api}/{version}/',params=params,data={'data':body},headers=headers)
                self._merge(r)
                if r.status_code!=200:raise GatewayError('闲鱼接口暂未返回有效结果','HTTP_ERROR',unknown=write)
                result=r.json()
                if not isinstance(result,dict) or not isinstance(result.get('ret'),list) or not result['ret']:
                    raise GatewayError('闲鱼返回的结果不完整','INVALID_RESPONSE',unknown=write)
            except (httpx.HTTPError,ValueError):
                raise GatewayError('闲鱼连接超时或响应异常，请核对后再操作','NETWORK_ERROR',unknown=write) from None
            ret=str(result['ret'][0]);code=safe_code(ret)
            if 'SUCCESS::' in ret:return result
            if code==INVALID_MAP_LOCATION and len(result['ret'])==1 and not response_has_item_reference(result.get('data')):
                raise GatewayError(LOCATION_REJECTION_MESSAGE,code,unknown=False)
            if code==INVALID_MAP_LOCATION:
                raise GatewayError('闲鱼返回所在地错误，但响应含有待核对信息，请先核对商品状态',code,unknown=write)
            if ('TOKEN_EX' in code or 'TOKEN_EMPTY' in code) and not write and attempt==0:continue
            if 'SESSION_EXPIRED' in code or 'LOGIN' in code:
                raise GatewayError('闲鱼登录已失效，请重新扫码','LOGIN_EXPIRED')
            if any(word in code for word in ['VALIDATE','RGV','PUNISH','FLOOD','FLOW_LIMIT']):
                raise GatewayError('闲鱼要求本人验证或稍后再试，请在闲鱼 App 核对','VERIFICATION_REQUIRED')
            raise GatewayError(f'闲鱼未完成请求（{code}）',code,unknown=write and not any(x in code for x in ['TOKEN_EX','TOKEN_EMPTY','PARAM_MISSING','PARAM_INVALID']))

    async def read(self,api,data,*,seller=False):
        if api not in READ_APIS:raise GatewayError('未开放的读取接口','API_NOT_ALLOWED')
        return await self._call(api,READ_APIS[api],data,seller=seller)

    async def capability(self):
        try:
            r=await self.read('mtop.idle.pc.backend.idleitem.preget',{'publishScene':'pcBackendPublish'},seller=True)
            value=parse_capability(r.get('data') or {})
            if value['mode']:return value
            raise GatewayError('平台未能确认账号发布类型，请在闲鱼官方页面核对','CAPABILITY_UNCERTAIN')
        except GatewayError as error:
            if error.code in {'LOGIN_EXPIRED','VERIFICATION_REQUIRED','NETWORK_ERROR','INVALID_RESPONSE','HTTP_ERROR','CAPABILITY_UNCERTAIN'} or error.code.startswith('FAIL_SYS_'):
                raise
        r=await self.read('mtop.idle.pc.idleitem.preget',{})
        value=parse_capability(r.get('data') or {})
        if not value['mode']:raise GatewayError('平台未能确认账号发布类型','CAPABILITY_UNCERTAIN')
        return value

    async def categories(self,draft,category=None,cards=None):
        data={'title':draft['title'],'description':draft['description'],'lockCpv':False,
            'multiSKU':False,'publishScene':'pcBackendPublish','scene':'shopPcPublish',
            'uniqueCode':str(int(time.time()*1000))+self.account_id[-4:]}
        if category:
            selected=category_selection(cards or [],category)
            data.update(currentCardList=selected['current_card_list'],selectedList=selected['selected_list'],
                catId=selected['cat_id'],catName=selected['cat_name'],channelCatId=selected['channel_cat_id'])
        r=await self.read('mtop.taobao.idle.kgraph.pc.property.recommend',data,seller=True)
        return parse_categories(r)

    async def upload(self,content,name):
        with Image.open(io.BytesIO(content)) as image:width,height=image.size
        # Keep the complete SHA-256 in local storage/provenance. Goofish rejects
        # a 64-hex-character filename with FILE_NAME_LENGTH_IS_OVER_RANGE.
        filename='sample_'+hashlib.sha256(content).hexdigest()[:16]+'.png'
        try:
            async with httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=60) as client:
                r=await client.post(UPLOAD_URL,files={'file':(filename,content,'image/png')},
                    headers={'Cookie':self.cookie,'User-Agent':UA,'Origin':'https://seller.goofish.com',
                             'Referer':'https://seller.goofish.com/?site=COMMONPRO','X-Requested-With':'XMLHttpRequest'})
            self._merge(r);value=r.json()
        except (httpx.HTTPError,ValueError,AttributeError):raise GatewayError('样张上传失败，未提交商品发布','IMAGE_UPLOAD_FAILED') from None
        if not isinstance(value,dict):raise GatewayError('样张上传响应格式异常，未提交商品发布','IMAGE_UPLOAD_FAILED')
        if value.get('success') is not True:
            code=safe_code(value.get('errorCode') or 'IMAGE_UPLOAD_FAILED')
            reason={'FILE_NAME_LENGTH_IS_OVER_RANGE':'上传文件名过长'}.get(code,'闲鱼拒绝图片上传（'+code+'）')
            raise GatewayError(reason+'，未提交商品发布',code)
        item=value.get('object')
        if not isinstance(item,dict):raise GatewayError('闲鱼未返回样张信息，未提交商品发布','IMAGE_UPLOAD_FAILED')
        url=str(item.get('url') or '');url='https:'+url if url.startswith('//') else url
        host=urlsplit(url).hostname or ''
        if r.status_code!=200 or value.get('success') is not True or urlsplit(url).scheme!='https' or not any(host==h or host.endswith('.'+h) for h in ['alicdn.com','goofish.com','taobaocdn.com']):
            raise GatewayError('闲鱼未返回有效的样张地址，未提交商品发布','IMAGE_UPLOAD_FAILED')
        pix=str(item.get('pix') or '')
        if re.fullmatch(r'\d{1,5}x\d{1,5}',pix.lower()):
            resized_width,resized_height=map(int,pix.lower().split('x'))
            if resized_width>0 and resized_height>0:width,height=resized_width,resized_height
        return {'extraInfo':{'isH':'false','isT':'false','raw':'false'},'isQrCode':False,
                'url':url,'heightSize':height,'widthSize':width,'major':False,'type':0,'status':'done'}

    async def publish_once(self,snapshot,images,unique_code):
        mode=snapshot['capability']['mode']
        if mode not in WRITE_APIS:raise GatewayError('发布账号类型未确认','CAPABILITY_UNCERTAIN')
        payload=listing_payload(snapshot,images,unique_code)
        return await self._call(WRITE_APIS[mode],'1.0',
            {'inputJson':json.dumps(payload,ensure_ascii=False,separators=(',',':'))} if mode=='shop' else payload,
            seller=mode=='shop',write=True)

    async def detail(self,item_id):
        if not re.fullmatch(r'\d{1,32}',str(item_id)):raise GatewayError('商品编号无效','INVALID_ITEM')
        r=await self.read('mtop.taobao.idle.pc.detail',{'itemId':str(item_id)})
        return r.get('data') or {}


from manual_location import (LocationError,location_is_valid,parse_city_candidate as parse_city_location,search_public_locations)


async def search_locations(query):
    try:return await search_public_locations(query)
    except LocationError as error:raise GatewayError(str(error),'LOCATION_INVALID') from None
