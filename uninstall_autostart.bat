@echo off
chcp 65001 >nul
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "Luyuan" /f
echo 已移除开机自启。
pause
