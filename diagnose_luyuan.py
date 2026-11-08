# -*- coding: utf-8 -*-
"""路远启动诊断脚本：把环境、端口、依赖状态打印到控制台。"""
from __future__ import print_function
import sys
import os
import subprocess

BASE = r"D:\Luyuan"
sys.path.insert(0, BASE)


def section(title):
    print("\n" + "=" * 40)
    print(title)
    print("=" * 40)


section("Python 环境")
print("可执行文件:", sys.executable)
print("版本:", sys.version.replace("\n", " "))

section("关键依赖检查")
libs = [
    "fastapi", "uvicorn", "pystray", "pynput", "sounddevice",
    "funasr", "librosa", "numpy", "soundfile"
]
for m in libs:
    try:
        __import__(m)
        print("[OK ]", m)
    except Exception as e:
        print("[ERR]", m, "->", e)

section("配置")
try:
    import config
    cfg = config.load()
    print("server:", cfg.get("server"))
    print("wakeword enabled:", cfg.get("wakeword", {}).get("enabled"))
except Exception as e:
    print("读取 config 失败:", e)

section("端口 8777 占用情况")

def port_pid(port):
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"], stderr=subprocess.DEVNULL,
            encoding="gbk", errors="ignore", timeout=10
        )
    except Exception as e:
        print("netstat 失败:", e)
        return None
    for ln in out.splitlines():
        c = ln.split()
        if len(c) >= 5 and (":%d" % port) in c[1] and c[3] == "LISTENING":
            pid = c[4]
            if pid.isdigit():
                return int(pid)
    return None

pid = port_pid(8777)
if pid:
    print("占用 PID:", pid)
    try:
        cmd = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter 'ProcessId=%d').CommandLine" % pid],
            stderr=subprocess.DEVNULL, encoding="gbk", errors="ignore", timeout=10
        ).strip()
        print("命令行:", cmd[:300])
    except Exception as e:
        print("取命令行失败:", e)
else:
    print("8777 端口空闲")

section("尝试 import main")
try:
    import main
    print("[OK ] import main 成功")
except Exception as e:
    print("[ERR] import main 失败:", e)

section("尝试单独启动 Web 服务并访问 health")
try:
    import threading
    import time
    import urllib.request
    import server
    t = threading.Thread(
        target=server.run, kwargs={"host": "127.0.0.1", "port": 8777}, daemon=True
    )
    t.start()
    time.sleep(3)
    r = urllib.request.urlopen(
        "http://127.0.0.1:8777/api/health", timeout=5
    ).read().decode()
    print("[OK ] /api/health:", r)
except Exception as e:
    print("[ERR] 启动 Web 服务失败:", e)

section("笔记数量")
try:
    import store
    notes = store.list_notes(limit=1000)
    print("现有笔记数:", len(notes))
except Exception as e:
    print("读取笔记失败:", e)

print("\n诊断结束。请把上面的文字复制给助手。")
