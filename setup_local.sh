#!/usr/bin/env bash
set -e
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_hbl
echo "HBL Ultra 3.0 instalado. Ejecuta: python manage.py createsuperuser && python manage.py runserver"
echo "Panel: http://127.0.0.1:8000/control/"
