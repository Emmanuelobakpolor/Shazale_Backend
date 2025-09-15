@echo off
REM Script to run Django development server locally on Windows
REM Sets DEBUG=True for local development
set DEBUG=True
python manage.py runserver
