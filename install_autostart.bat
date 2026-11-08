@echo off
chcp 65001 >nul
set "PY=%~dp0.venv\Scripts\pythonw.exe"
set "MAIN=%~dp0main.py"
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "Luyuan" /t REG_SZ /d "\"%PY%\" \"%MAIN%\"" /f
echo 已添加开机自启。重启电脑后路远会自动在后台运行（托盘里能看到）。
pause
