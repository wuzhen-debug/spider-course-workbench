#!/bin/zsh
set -e
cd -- "$(dirname -- "$0")"
.venv/bin/python manage.py start
cd ../../xhs/xhs-all-in-one-local
.venv/bin/python manage.py start --open
