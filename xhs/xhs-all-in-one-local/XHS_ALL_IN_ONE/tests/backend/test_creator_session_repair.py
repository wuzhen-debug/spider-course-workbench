"""Isolated auth repair: no uploads, post requests, live credentials or network."""
from contextlib import contextmanager
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from test_login_session_recovery import binding,db_read
from test_api import app,client,_register_and_get_access_token
from backend.app.api import accounts,login_sessions,publish
from backend.app.core.security import decrypt_text,encrypt_text
from backend.app.models import AccountCookieVersion,PlatformAccount,PublishJob,PublishAsset,Task,LoginSession
from backend.app.adapters.xhs.creator_api_adapter import CreatorRequestRejected

IDENTITY='fixture-bound-account'

def creator():
 def insert(db):
  account=PlatformAccount(user_id=1,platform='xhs',sub_type='creator',external_user_id=IDENTITY,nickname='Fixture creator',status='active')
  db.add(account);db.flush()
  db.add(AccountCookieVersion(platform_account_id=account.id,encrypted_cookies=encrypt_text(json.dumps({'a1':'creator-a1','customer-sso-sid':'private-cas-only'}))))
  db.commit();return account.id
 return db_read(insert)

def snapshot():
 return db_read(lambda db:deepcopy({m.__tablename__:[tuple(r) for r in db.execute(m.__table__.select()).all()]
  for m in [PlatformAccount,AccountCookieVersion,PublishJob,PublishAsset,Task]}))

def add_pc(external=IDENTITY):
 def insert(db):
  row=PlatformAccount(user_id=1,platform='xhs',sub_type='pc',external_user_id=external,nickname='Fixture creator',status='active')
  db.add(row);db.flush();db.add(AccountCookieVersion(platform_account_id=row.id,encrypted_cookies=encrypt_text(json.dumps({'a1':'pc-a1','web_session':'issued-pc-session'}))))
  db.commit();return row.id
 return db_read(insert)

class CreatorBridge:
 identity=IDENTITY
 def exchange_from_user_cookies(self,cookies):
  assert cookies.get('web_session')
  return {'cookies':{**cookies,'customer-sso-sid':'fresh-creator-cas'}}
 def get_user_info(self,cookies):
  return {'external_user_id':self.identity,'nickname':'Fixture creator','profile':{}}

class SessionProbe:
 calls=0
 def __init__(self,cookies):assert 'web_session=' in cookies
 def inspect_session(self):type(self).calls+=1

def install_bridge(bridge=None):
 SessionProbe.calls=0
 app.dependency_overrides[accounts.get_creator_account_adapter]=lambda:bridge or CreatorBridge()
 app.dependency_overrides[accounts.get_creator_session_adapter_factory]=lambda:SessionProbe

def test_missing_pc_gives_repair_action_without_reading_other_accounts_or_mutating(binding):
 adapter,headers=binding;aid=creator();add_pc('another-platform-user');install_bridge();before=snapshot()
 response=client.post(f'/api/accounts/{aid}/repair-publish-session',headers=headers)
 assert response.status_code==200 and response.json()['repair']['requires_pc_login']
 assert response.json()['repair']['matching_pc_account_id'] is None and SessionProbe.calls==0
 assert snapshot()==before
 listed=client.get('/api/accounts?platform=xhs',headers=headers).json()['items']
 assert next(a for a in listed if a['id']==aid)['publish_session']['state']=='pc_login_required'
 assert 'private-cas-only' not in json.dumps(listed)

def test_same_identity_refresh_adds_cookie_version_keeps_old_and_never_changes_notes(binding):
 _,headers=binding;aid=creator();pid=add_pc();install_bridge();before=snapshot()
 response=client.post(f'/api/accounts/{aid}/repair-publish-session',headers=headers)
 assert response.status_code==200,response.text
 assert response.json()['session_ok'] and response.json()['publish_permission']=='not_tested'
 assert response.json()['repair']['matching_pc_account_id']==pid and SessionProbe.calls==1
 after=snapshot();assert after['account_cookie_versions'][:-1]==before['account_cookie_versions']
 assert len(after['platform_accounts'])==len(before['platform_accounts'])
 for table in ['publish_jobs','publish_assets','tasks']:assert after[table]==before[table]
 text=db_read(lambda db:decrypt_text(db.scalars(select(AccountCookieVersion).where(AccountCookieVersion.platform_account_id==aid).order_by(AccountCookieVersion.id.desc())).first().encrypted_cookies))
 assert json.loads(text)['web_session']=='issued-pc-session'

@pytest.mark.parametrize('failure',['wrong_identity','network'])
def test_failed_repair_never_replaces_current_creator_credentials(binding,failure):
 _,headers=binding;aid=creator();add_pc();bridge=CreatorBridge()
 if failure=='wrong_identity':bridge.identity='wrong-user'
 else:
  def fail(*args):raise RuntimeError('private-upstream-cookie')
  bridge.exchange_from_user_cookies=fail
 install_bridge(bridge);before=snapshot()
 response=client.post(f'/api/accounts/{aid}/repair-publish-session',headers=headers)
 assert response.status_code==(409 if failure=='wrong_identity' else 200)
 assert 'private-upstream-cookie' not in response.text and snapshot()==before
 assert SessionProbe.calls==0

def test_repair_ownership_prevents_credentials_lookup_and_login(binding):
 adapter,headers=binding;aid=creator();other=_register_and_get_access_token('repair-other');before=snapshot()
 for path,payload in [(f'/api/accounts/{aid}/repair-publish-session',{}),('/api/xhs/login-sessions/pc/qrcode',{'target_creator_account_id':aid})]:
  assert client.post(path,json=payload).status_code==401
  assert client.post(path,headers={'Authorization':f'Bearer {other}'},json=payload).status_code==404
 assert adapter.calls['qr']==0 and snapshot()==before

@pytest.mark.parametrize('matches',[True,False])
def test_targeted_pc_scan_checks_identity_before_saving_and_forces_creator_sync(binding,matches):
 adapter,headers=binding;aid=creator();before=snapshot()
 app.dependency_overrides[login_sessions.get_creator_login_adapter]=lambda:CreatorBridge()
 if not matches:adapter.get_user_info=lambda cookies:{'external_user_id':'wrong-user','nickname':'Other'}
 response=client.post('/api/xhs/login-sessions/pc/qrcode',headers=headers,json={'target_creator_account_id':aid,'sync_creator':False})
 assert response.status_code==200,response.text
 sid=response.json()['session_id']
 response=client.get(f'/api/xhs/login-sessions/{sid}',headers=headers)
 if not matches:
  assert response.status_code==409 and snapshot()==before
  assert db_read(lambda db:db.get(LoginSession,sid).status)=='expired'
 else:
  assert response.status_code==200,response.text
  assert response.json()['creator_account']['id']==aid and response.json()['account']['external_user_id']==IDENTITY
  assert response.json()['creator_account']['action']=='updated'
  after=snapshot();assert len(after['account_cookie_versions'])==len(before['account_cookie_versions'])+2
  assert after['account_cookie_versions'][0]==before['account_cookie_versions'][0]
  assert client.get(f'/api/xhs/login-sessions/{sid}',headers=headers).json()==response.json()
  assert adapter.calls['poll']==1
  for table in ['publish_jobs','publish_assets','tasks']:assert after[table]==before[table]

@pytest.mark.parametrize('missing_cookie',[True,False])
def test_bad_login_stops_before_upload_task_or_note_request(binding,missing_cookie):
 _,headers=binding;aid=creator();calls=[]
 def seed(db):
  if not missing_cookie:
   version=db.scalars(select(AccountCookieVersion).where(AccountCookieVersion.platform_account_id==aid)).first()
   version.encrypted_cookies=encrypt_text('{"a1":"fixture","web_session":"fixture-valid"}')
  job=PublishJob(user_id=1,platform='xhs',platform_account_id=aid,title='Fixture note',body='Fixture text',status='failed',publish_error='historical failure')
  db.add(job);db.flush();db.add(PublishAsset(publish_job_id=job.id,asset_type='image',file_path='fixture.png',upload_status='pending'))
  db.commit();return job.id
 jid=db_read(seed);before=snapshot()
 class Adapter:
  def __init__(self,cookies):
   assert not missing_cookie,'Missing credentials must stop before initializing SDK'
  @contextmanager
  def session(self):yield self
  def inspect_session(self):raise CreatorRequestRejected('HTTP 401 fixture',{'http_status':401})
  def upload_media(self,*args):calls.append('upload');pytest.fail('Must not upload with bad login')
  def post_note(self,*args):calls.append('note');pytest.fail('Must not send a note')
 app.dependency_overrides[publish.get_creator_publish_adapter_factory]=lambda:Adapter
 response=client.post(f'/api/publish/jobs/{jid}/publish',headers=headers)
 assert response.status_code==(409 if missing_cookie else 502),response.text
 assert calls==[] and snapshot()==before
