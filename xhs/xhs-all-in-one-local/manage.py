"""Start and stop this local XHS_ALL_IN_ONE installation only."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import time
from urllib.request import urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
REPO = ROOT / "XHS_ALL_IN_ONE"
PYTHON = ROOT / ".venv/bin/python"
CONFIG = ROOT / "config.local.yaml"
RUNTIME = ROOT / "runtime"
PIDFILE = RUNTIME / "server.json"
LOG = RUNTIME / "server.log"
URL = "http://127.0.0.1:8000"


def configure():
    os.umask(0o077)
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    if CONFIG.exists():
        return
    # CONFIG_FILE is the upstream-supported YAML override. Passing YAML fields
    # as Settings constructor arguments otherwise takes precedence over .env.
    body = (
        "server:\n  host: '127.0.0.1'\n  port: 8000\n"
        "  cors_origins: 'http://127.0.0.1:8000,http://localhost:8000'\n"
        "database:\n  type: 'sqlite'\n  sqlite_path: '../data/spider_xhs.db'\n"
        "security:\n  secret_key: '" + secrets.token_urlsafe(48) + "'\n"
        "  fernet_key: '" + base64.urlsafe_b64encode(os.urandom(32)).decode() + "'\n"
        "scheduler:\n  enabled: false\n  interval_seconds: 60\n"
        "frontend:\n  serve_static: true\n  build_dir: './frontend/dist'\n"
    )
    with CONFIG.open("x", encoding="utf-8") as stream:
        stream.write(body)
    CONFIG.chmod(0o600)


def healthy():
    try:
        with urlopen(URL + "/api/health", timeout=2) as response:
            return json.load(response).get("status") == "ok"
    except Exception:
        return False


def owned_pid():
    if not PIDFILE.exists():
        return None
    state = json.loads(PIDFILE.read_text())
    pid = int(state["pid"])
    check = subprocess.run(["ps", "-p", str(pid), "-o", "command="], text=True, capture_output=True)
    if check.returncode == 0 and str(REPO / "main.py") in check.stdout:
        return pid
    return None


def start(open_browser=False):
    configure()
    pid = owned_pid()
    if pid and healthy():
        print("XHS_ALL_IN_ONE 已在运行：" + URL)
    else:
        if not (REPO / "frontend/dist/index.html").exists():
            raise SystemExit("前端尚未构建；请查看安装说明。")
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 8000)) == 0:
                raise SystemExit("8000 端口已被其他进程占用；没有停止或替换该进程。")
        env = os.environ.copy()
        env["CONFIG_FILE"] = str(CONFIG)
        env["PYTHONUNBUFFERED"] = "1"
        env["LOGURU_DIAGNOSE"] = "NO"
        env["PATH"] = "/usr/local/bin:/opt/homebrew/bin:" + env.get("PATH", "")
        with LOG.open("ab") as stream:
            proc = subprocess.Popen([str(PYTHON), str(REPO / "main.py"), "--host", "127.0.0.1", "--port", "8000"],
                                    cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=stream,
                                    stderr=subprocess.STDOUT, start_new_session=True)
        PIDFILE.write_text(json.dumps({"pid": proc.pid, "repo": str(REPO),
            "started_at_shanghai": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()}, indent=2))
        for _ in range(25):
            if healthy():
                print("XHS_ALL_IN_ONE 已启动：" + URL)
                break
            if proc.poll() is not None:
                raise SystemExit("启动未成功，请查看：" + str(LOG))
            time.sleep(1)
        else:
            proc.terminate()
            raise SystemExit("启动超时，已结束本次启动的进程。日志：" + str(LOG))
    if open_browser:
        subprocess.run(["open", URL], check=True)


def stop():
    pid = owned_pid()
    if not pid:
        print("本安装的服务未运行。")
        return
    os.kill(pid, signal.SIGTERM)
    print("已向本安装的服务发送正常停止信号。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["configure", "start", "stop", "status"])
    parser.add_argument("--open", action="store_true", dest="open_browser")
    args = parser.parse_args()
    if args.action == "configure":
        configure()
        print("本地配置已准备好；密钥未输出。")
    elif args.action == "start":
        start(args.open_browser)
    elif args.action == "stop":
        stop()
    else:
        print(json.dumps({"managed_pid": owned_pid(), "healthy": healthy(), "url": URL}))
