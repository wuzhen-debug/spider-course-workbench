"""Public-place lookup with district/POI/coordinate cross-checks, no user GPS."""
import ast
import asyncio
import math
from pathlib import Path
import re

import httpx

ROOT=Path(__file__).resolve().parent
SOURCE='amap-poi-detail+reverse-geocode'


class LocationError(ValueError):pass


def text(value):return value.strip() if isinstance(value,str) else ''


def district_code(value):
    return bool(re.fullmatch(r'\d{6}',text(value)) and not value.endswith('00'))


def coordinates(value):
    try:lng,lat=map(float,text(value).split(','))
    except (TypeError,ValueError):raise LocationError('地点坐标无效，请重新检索所在地') from None
    if not all(math.isfinite(x) for x in [lng,lat]) or not (-180<=lng<=180 and -90<=lat<=90):
        raise LocationError('地点坐标无效，请重新检索所在地')
    return lng,lat


def location_is_valid(location):
    if not isinstance(location,dict):return False
    dto=location.get('dto');proof=location.get('validation')
    if not isinstance(dto,dict) or not isinstance(proof,dict):return False
    if proof.get('version')!=2 or proof.get('source')!=SOURCE:return False
    if not district_code(dto.get('divisionId')) or not text(dto.get('poiId')) or not text(dto.get('poiName')):return False
    if dto['divisionId']!=proof.get('adcode') or dto['poiId']!=proof.get('poi_id'):return False
    if not text(proof.get('poi_district')) or proof['poi_district']!=proof.get('reverse_district'):return False
    try:
        lng,lat=coordinates(proof.get('poi_location'))
        gps_lat,gps_lng=map(float,text(dto.get('gps')).split(','))
        return math.isfinite(gps_lat) and math.isfinite(gps_lng) and abs(gps_lng-lng)<=.000001 and abs(gps_lat-lat)<=.000001
    except (ValueError,TypeError):return False


def parse_city_candidate(district,places):
    """Find the exact public city POI, without assigning a divisionId yet."""
    if str(places.get('status'))!='1':return None
    for place in places.get('pois',[]):
        if place.get('name')!=district.get('name') or not text(place.get('typecode')).startswith('1901'):continue
        if not text(place.get('id')):continue
        try:
            lng,lat=coordinates(place.get('location'));cx,cy=coordinates(district.get('center'))
        except LocationError:continue
        if abs(lng-cx)+abs(lat-cy)>.1:continue
        return {'poi_id':place['id'],'name':place['name'],'location':place['location'],'public_city':True}
    return None


def verified_location(poi_id,poi,reverse,public_city=False):
    """Use the POI's actual district, never the user's province/city search code."""
    if poi.get('id')!=poi_id or not text(poi.get('name')):raise LocationError('地点编号未匹配，请重新检索所在地')
    if str(reverse.get('status'))!='1':raise LocationError('无法核对地点所在区县，请重新检索')
    component=(reverse.get('regeocode') or {}).get('addressComponent') or {}
    adcode=text(component.get('adcode'));district=text(component.get('district'))
    if not district_code(adcode) or not district or text(poi.get('adname'))!=district:
        raise LocationError('地点与区县未匹配，请重新选择带有效区县的所在地')
    if text(poi.get('adcode')) and text(poi['adcode'])!=adcode:
        raise LocationError('地点行政区划与坐标不一致，请重新检索')
    lng,lat=coordinates(poi.get('location'))
    city=text(component.get('city')) or text(component.get('province'))
    region=' · '.join(dict.fromkeys(p for p in [city,district] if p))
    label=region+'（公共城市中心）' if public_city else region+' · '+poi['name']
    result={'label':label,'dto':{'divisionId':adcode,'gps':f'{lat:.6f},{lng:.6f}',
        'poiId':poi_id,'poiName':poi['name']},'validation':{'version':2,'source':SOURCE,
        'adcode':adcode,'poi_id':poi_id,'poi_district':poi['adname'],'reverse_district':district,'poi_location':poi['location']}}
    if not location_is_valid(result):raise LocationError('所在地校验未通过，请重新检索')
    return result


async def search_public_locations(query):
    tree=ast.parse((ROOT/'source/backend-web/app/services/amap_inputtips_service.py').read_text())
    key=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and
        any(isinstance(t,ast.Name) and t.id=='AMAP_WEB_KEY' for t in n.targets))
    params={'s':'rsv3','key':key,'platform':'JS','logversion':'2.0','sdkversion':'2.0','appname':'https://seller.goofish.com'}
    headers={'Origin':'https://seller.goofish.com','Referer':'https://seller.goofish.com/'}
    try:
        async with httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=20,headers=headers) as client:
            async def get(path,**extra):
                response=await client.get('https://restapi.amap.com/v3/'+path,params={**params,**extra})
                body=response.json()
                if response.status_code!=200 or not isinstance(body,dict) or str(body.get('status'))!='1':
                    raise LocationError('地点检索暂不可用，请稍后再试')
                return body
            async def resolve(poi_id,public_city=False):
                detail=await get('place/detail',id=poi_id,extensions='base')
                poi=next((p for p in detail.get('pois',[]) if p.get('id')==poi_id),None)
                if not poi:raise LocationError('未查到对应地点，请重新检索')
                coordinates(poi.get('location'))
                reverse=await get('geocode/regeo',location=poi['location'],extensions='base',radius='100')
                return verified_location(poi_id,poi,reverse,public_city)
            district=await get('config/district',keywords=query,subdistrict='0',extensions='base')
            exact=next((d for d in district.get('districts',[]) if d.get('level') in {'city','province','district'} and
                text(d.get('name')).removesuffix('市')==query.removesuffix('市')),None)
            if exact:
                places=await get('place/text',keywords=exact['name'],types='190100',city=exact['adcode'],citylimit='true',extensions='base',offset='10')
                candidate=parse_city_candidate(exact,places)
                if candidate:return [await resolve(candidate['poi_id'],True)]
            tips=await get('assistant/inputtips',keywords=query,city='全国',citylimit='false',datatype='all')
            ids=list(dict.fromkeys(t['id'] for t in tips.get('tips',[]) if isinstance(t,dict) and text(t.get('id'))))[:5]
            results=await asyncio.gather(*(resolve(poi_id) for poi_id in ids),return_exceptions=True)
            return [item for item in results if isinstance(item,dict) and location_is_valid(item)]
    except (httpx.HTTPError,ValueError,KeyError,TypeError,AttributeError):
        raise LocationError('所在地无法核对到区县，请重新检索城市或公共地点') from None
