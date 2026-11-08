@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  路远 · 桌面端  一键启动
echo ============================================

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 没找到 python。请先安装 Python 3.11 或更高版本，并在安装时勾选 "Add python.exe to PATH"。
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] 建虚拟环境 .venv ...
  python -m venv .venv || goto fail
) else (
  echo [1/3] 虚拟环境已存在，跳过
)

echo [2/3] 安装依赖（首次较慢，之后秒过）...
".venv\Scripts\python.exe" -m pip install -U pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q || goto fail

if not exist "config.json" (
  echo [提示] 没找到 config.json，先复制一份模板（改不改都能先跑）
  copy /y config.example.json config.json >nul
)

if not exist "models" (
  echo [提示] 没找到 models 目录：语音转写需要先跑一次 python download_models.py（约 1 GB）
)

echo [3/3] 启动 ...
".venv\Scripts\python.exe" main.py
goto end

:fail
echo [错误] 安装依赖失败，把上面的报错贴出来再排查。
pause
exit /b 1

:end
pause
