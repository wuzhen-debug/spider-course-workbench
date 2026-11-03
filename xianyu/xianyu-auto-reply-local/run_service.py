"""Restricted entry point: upstream login/models plus local draft extension only."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
c = json.loads((ROOT/'private/config.json').read_text())
os.umask(0o077)
os.environ.update({
    'MYSQL_HOST':'127.0.0.1', 'MYSQL_PORT':'33079',
    'MYSQL_USER':'spider_xianyu', 'MYSQL_PASSWORD':c['mysql_password'],
    'MYSQL_DATABASE':'spider_xianyu',
    'REDIS_HOST':'127.0.0.1', 'REDIS_PORT':'16379', 'REDIS_PASSWORD':c['redis_password'],
    'DB_POOL_SIZE':'600', 'DB_MAX_OVERFLOW':'0', 'REDIS_POOL_SIZE':'600',
    'SQL_ECHO':'false', 'AUTO_START_CRAWL_JOBS':'false',
    'ENABLE_REMOTE_ADS':'false', 'ENABLE_REMOTE_ANNOUNCEMENTS':'false',
    'ENABLE_REMOTE_POPUP_ANNOUNCEMENTS':'false', 'LOGURU_DIAGNOSE':'NO',
    'SPIDER_DRAFT_ONLY':'true',
})
sys.path.insert(0, str(ROOT/'source'))
sys.path.insert(0, str(ROOT/'source/backend-web'))

if __name__ == '__main__':
    import uvicorn
    from draft_service import app
    uvicorn.run(app, host='127.0.0.1', port=18089, access_log=False)
