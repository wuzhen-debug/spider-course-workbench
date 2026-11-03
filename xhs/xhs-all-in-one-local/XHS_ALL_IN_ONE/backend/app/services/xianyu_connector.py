"""Fixed local sidecar transport with explicit human-publication routes only."""
import json
from pathlib import Path
import re

from fastapi import HTTPException
import httpx


CONFIG_PATH = Path(__file__).resolve().parents[4] / 'runtime/xianyu-connector.json'
ALLOWED = re.compile(r'^/(?:health|bridge/(?:accounts|login(?:/[a-f0-9-]{36})?|assets/[a-f0-9]{64}|drafts(?:/\d+(?:/images/\d+|/publish-state|/publish-source|/publish-options|/publish-preview|/publish)?)?|publish-locations|publications/[a-f0-9-]{36}(?:/reconcile)?))$')


class XianyuConnector:
    def __init__(self, config_path=CONFIG_PATH):
        try:
            self.config=json.loads(config_path.read_text())
        except (OSError,ValueError): raise HTTPException(503,'闲鱼独立服务尚未配置')
        if self.config.get('base_url')!='http://127.0.0.1:18089': raise HTTPException(503,'闲鱼连接地址需要本机核对')

    def request(self,method,path,owner,*,payload=None,content=None,binary=False):
        if owner!=self.config.get('owner_user_id'): raise HTTPException(403,'当前用户尚未配置闲鱼工作台')
        if not ALLOWED.fullmatch(path) or method not in {'GET','POST','PUT','PATCH'}: raise HTTPException(403,'未开放的闲鱼工作台接口')
        headers={'Authorization':'Bearer '+self.config['bridge_token'],'X-Spider-User':str(owner)}
        try:
            with httpx.Client(trust_env=False,timeout=httpx.Timeout(90,connect=3),follow_redirects=False) as client:
                response=client.request(method,self.config['base_url']+path,headers=headers,json=payload,content=content)
        except httpx.HTTPError: raise HTTPException(503,'闲鱼独立服务暂不可用；已保存的草稿仍保留，请恢复服务后刷新')
        if response.status_code>=400:
            try: detail=response.json().get('detail')
            except ValueError: detail=None
            raise HTTPException(response.status_code if response.status_code in {401,403,404,409,413,422,502,503} else 502,
                                detail if isinstance(detail,str) else '闲鱼草稿服务未完成请求，请刷新核对后继续')
        if response.is_redirect: raise HTTPException(502,'闲鱼本机接口返回了未预期的跳转')
        if binary:
            if not response.headers.get('content-type','').startswith('image/png'): raise HTTPException(502,'样张响应格式异常')
            return response.content
        try: return response.json()
        except ValueError: raise HTTPException(502,'闲鱼草稿服务响应格式异常')


def get_xianyu_connector(): return XianyuConnector()
