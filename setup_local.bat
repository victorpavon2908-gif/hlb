@echo off
setlocal
python -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_hbl
echo.
echo ==========================================================
echo HBL Ultra 3.0 instalado.
echo 1. Ejecuta: python manage.py createsuperuser
echo 2. Ejecuta: python manage.py runserver
echo 3. Abre: http://127.0.0.1:8000/control/
echo ==========================================================
endlocal
