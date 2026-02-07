#!/usr/bin/env bash
set -euo pipefail

pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput --clear
