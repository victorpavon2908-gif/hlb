#!/usr/bin/env bash
set -o errexit
python -m pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py seed_hbl
python manage.py seed_payment_gateways
