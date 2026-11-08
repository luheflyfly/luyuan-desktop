@echo off
chcp 65001 >nul
cd /d %~dp0
rem 解释器：优先用环境变量 PY，其次 python
if not defined PY set PY=python
set ICO=%~dp0app.ico

echo [1/3] clean
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [2/3] pyinstaller
"%PY%" -m PyInstaller --noconfirm --clean --onedir --windowed --name Luyuan --icon "%ICO%" --manifest "%~dp0dpi.manifest" --add-data "%ICO%;." --collect-all webview --collect-all pythonnet --collect-all pystray --hidden-import clr --hidden-import System.Windows.Forms --hidden-import System.Drawing shell.py
if errorlevel 1 goto fail

echo [3/3] finalize
copy /y "dist\Luyuan\Luyuan.exe" "dist\Luyuan\Luyuan_run.exe" >nul
copy /y "%ICO%" "dist\Luyuan\app.ico" >nul
echo BUILD_OK
exit /b 0

:fail
echo BUILD_FAIL
exit /b 1