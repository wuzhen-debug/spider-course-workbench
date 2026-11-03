"""Project-owned native MySQL, Redis and draft-only Xianyu service on macOS.

Never starts the upstream websocket/scheduler, installs a LaunchAgent, or changes
another installation. Configuration and credentials stay in private/ (0700).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / 'private'
RUNTIME = ROOT / 'runtime'
MYSQL = ROOT / 'deps/mysql-8.4.11-macos15-arm64/bin'
REDIS = ROOT / 'deps/redis-7.2.17/src/redis-server'
PYTHON = ROOT / '.venv/bin/python'
CONFIG = PRIVATE / 'config.json'
SOCKET_DIR = Path('/private/tmp') / ('spider-xianyu-' + hashlib.sha256(str(ROOT).encode()).hexdigest()[:10])
SOCKET = SOCKET_DIR / 'mysql.sock'
URL = 'http://127.0.0.1:18089'


def write_private(path, text):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
        f.write(text)
    path.chmod(0o600)


def configure():
    os.umask(0o077)
    for p in [PRIVATE, RUNTIME, ROOT/'data', ROOT/'data/redis', ROOT/'data/assets', SOCKET_DIR]:
        p.mkdir(parents=True, exist_ok=True, mode=0o700)
        p.chmod(0o700)
    if not CONFIG.exists():
        from cryptography.fernet import Fernet
        write_private(CONFIG, json.dumps({
            'mysql_password': secrets.token_urlsafe(32),
            'mysql_root_password': secrets.token_urlsafe(32),
            'redis_password': secrets.token_urlsafe(32),
            'bridge_token': secrets.token_urlsafe(48),
            'fernet_key': Fernet.generate_key().decode(),
            'owner_user_id': 1,
            'upstream_ref': '888fe4164c0a9779065cabf2092c825b47200153',
            'brand_id': 'xingtu',
            'mode': 'draft_only',
        }, indent=2))
    c = json.loads(CONFIG.read_text())
    write_private(PRIVATE/'mysql-root.cnf', '[client]\nuser=root\npassword=' + c['mysql_root_password'] + '\nsocket=' + str(SOCKET) + '\n')
    write_private(PRIVATE/'redis.conf', '\n'.join([
        'bind 127.0.0.1', 'port 16379', 'protected-mode yes',
        'requirepass ' + c['redis_password'], 'appendonly yes',
        'dir "' + str(ROOT/'data/redis') + '"', 'maxmemory 128mb',
        'maxmemory-policy noeviction', 'daemonize no',
    ]) + '\n')
    return c


def owned_pid(name):
    path = RUNTIME/(name+'.json')
    if not path.exists(): return None
    state = json.loads(path.read_text())
    p = subprocess.run(['ps', '-p', str(state['pid']), '-o', 'command='], capture_output=True, text=True)
    return state['pid'] if p.returncode == 0 and state['marker'] in p.stdout else None


def free_port(port):
    with socket.socket() as sock:
        return sock.connect_ex(('127.0.0.1', port)) != 0


def launch(name, args, port=None, env=None):
    pid = owned_pid(name)
    if pid: return pid
    if port and not free_port(port):
        raise RuntimeError(f'{port} 端口已被其他进程占用，未停止该进程')
    with (RUNTIME/(name+'.log')).open('ab') as log:
        p = subprocess.Popen(args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                             stdout=log, stderr=log, start_new_session=True)
    marker = str(args[1]) if name == 'api' else str(args[0])
    write_private(RUNTIME/(name+'.json'), json.dumps({'pid': p.pid, 'marker': marker}))
    return p.pid


def mysql_ready(c, bootstrap=False):
    args = [str(MYSQL/'mysqladmin')]
    if bootstrap: args += ['--no-defaults', '--protocol=socket', '--socket='+str(SOCKET), '-u', 'root']
    else: args += ['--defaults-extra-file='+str(PRIVATE/'mysql-root.cnf'), '--protocol=socket']
    return subprocess.run(args+['ping'], capture_output=True).returncode == 0


def wait_ready(probe, label, seconds=45):
    for _ in range(seconds):
        if probe(): return
        time.sleep(1)
    raise RuntimeError(label+' 未就绪，请查看 runtime 下对应日志')


def mysql_args():
    return [str(MYSQL/'mysqld'), '--no-defaults', '--basedir='+str(MYSQL.parent),
            '--datadir='+str(ROOT/'data/mysql'), '--socket='+str(SOCKET),
            '--mysqlx=0', '--pid-file='+str(RUNTIME/'mysql-server.pid'),
            '--log-error='+str(RUNTIME/'mysql-error.log'),
            '--character-set-server=utf8mb4', '--collation-server=utf8mb4_unicode_ci',
            '--innodb-buffer-pool-size=128M', '--max-connections=50',
            '--default-time-zone=+08:00']


def init_mysql(c):
    datadir = ROOT/'data/mysql'
    if not (datadir/'auto.cnf').exists():
        datadir.mkdir(mode=0o700, exist_ok=True)
        with (RUNTIME/'mysql-init.log').open('ab') as log:
            subprocess.run(mysql_args()+['--initialize-insecure'], stdout=log, stderr=log, check=True)
    marker = PRIVATE/'mysql-initialized.json'
    if marker.exists(): return
    # An empty new DB is bootstrapped over an owner-only socket; TCP stays off.
    launch('mysql', mysql_args()+['--skip-networking'])
    wait_ready(lambda: mysql_ready(c, bootstrap=True), 'MySQL 初始化')
    sql = (
        "CREATE DATABASE IF NOT EXISTS spider_xianyu CHARACTER SET utf8mb4;\n"
        "CREATE USER IF NOT EXISTS 'spider_xianyu'@'127.0.0.1' IDENTIFIED BY '"+c['mysql_password']+"';\n"
        "GRANT ALL ON spider_xianyu.* TO 'spider_xianyu'@'127.0.0.1';\n"
        "ALTER USER 'root'@'localhost' IDENTIFIED BY '"+c['mysql_root_password']+"';\n"
    )
    result = subprocess.run([str(MYSQL/'mysql'), '--no-defaults', '--protocol=socket',
                             '--socket='+str(SOCKET), '-u', 'root'], input=sql, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('MySQL 初始化 SQL 失败，未输出含凭据的命令或响应')
    write_private(marker, json.dumps({'database':'spider_xianyu', 'initialized':True}))
    subprocess.run([str(MYSQL/'mysqladmin'), '--defaults-extra-file='+str(PRIVATE/'mysql-root.cnf'), 'shutdown'], check=True, capture_output=True)
    wait_ready(lambda: owned_pid('mysql') is None, 'MySQL 初始化进程退出', 20)


def health():
    try:
        with urlopen(URL+'/health', timeout=2) as r: return json.load(r)
    except Exception: return None


def start():
    c = configure()
    init_mysql(c)
    launch('mysql', mysql_args()+['--bind-address=127.0.0.1', '--port=33079'], port=33079)
    wait_ready(lambda: mysql_ready(c), 'MySQL')
    launch('redis', [str(REDIS), str(PRIVATE/'redis.conf')], port=16379)
    env = os.environ.copy()
    env.update(PYTHONUNBUFFERED='1', LOGURU_DIAGNOSE='NO')
    launch('api', [str(PYTHON), str(ROOT/'run_service.py')], port=18089, env=env)
    wait_ready(lambda: bool((health() or {}).get('ready')), '闲鱼草稿服务', 60)
    print(json.dumps(health(), ensure_ascii=False))


def stop():
    for name in ['api','redis','mysql']:
        pid = owned_pid(name)
        if pid:
            os.kill(pid, signal.SIGTERM)
            wait_ready(lambda: owned_pid(name) is None, name+' 正常退出', 30)
    print('已正常停止本目录管理的闲鱼服务，数据保留。')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['configure','start','stop','status'])
    args = p.parse_args()
    if args.action == 'start': start()
    elif args.action == 'stop': stop()
    elif args.action == 'configure': configure(); print('独立配置已生成，凭据未输出。')
    else: print(json.dumps({'url':URL,'health':health(),'processes':{n:owned_pid(n) for n in ['api','mysql','redis']}}, ensure_ascii=False))
