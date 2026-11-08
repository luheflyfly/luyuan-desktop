@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Luyuan P1 - Voice Note
".venv\Scripts\python.exe" voice_note.py
if errorlevel 1 pause
