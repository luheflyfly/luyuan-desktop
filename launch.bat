@echo off
chcp 65001 >nul
:: 路远启动器（双击即可）。用 VBScript 隐藏 python 控制台窗口，
:: 同时保持 Web 服务可靠运行（pythonw 无控制台模式曾导致服务静默崩溃）。
start "" wscript "%~dp0run_hidden.vbs"
