@echo off
chcp 65001 >nul
cd /d "%~dp0"
:: 调试模式：带控制台，方便看报错
".venv\Scripts\python.exe" main.py
if errorlevel 1 pause
