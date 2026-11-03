#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
exec .venv/bin/python manage.py start --open
