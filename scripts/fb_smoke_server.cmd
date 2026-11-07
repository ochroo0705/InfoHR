@echo off
rem Local smoke server on the Firebird scratch clone (db\work\smoke_clone.fdb), port 8010.
rem Scratch use only: the clone is a copy of the MACS test data with demo rows. Never point this at the real database.
rem Run from anywhere; it changes to the repo root first.
cd /d "%~dp0.."
set DB_ENGINE=firebird
set FIREBIRD_NAME=E:\WorkProjects\Info HR\db\work\smoke_clone.fdb
set DJANGO_DEBUG=true
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
".venv\Scripts\python" app\manage.py runserver 8010 --noreload
