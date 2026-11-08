# -*- coding: utf-8 -*-
"""课务系统（独立本地应用，127.0.0.1:8790）的接入层。

路远面板「课务」页用 iframe 把课务系统装进来，本模块只做两件事：
  · status() —— 探测 8790 在不在
  · ensure() —— 不在就静默拉起一个后台进程（带 --no-browser，不弹浏览器窗口）

课务系统自己的 data/*.json 一概不碰：路远这边只读它的页面，不写它的数据。
路径/端口如需改动，在 config.json 里加一节（不加就用下面的默认值）：
  "keiwu": {"dir": "D:\\ALL ai work studio\\QWEN\\课务系统", "port": 8790}
"""
import os
import socket
import subprocess
import sys
import time

import config

DEFAULT_DIR = r"D:\ALL ai work studio\QWEN\课务系统"
HOST = "127.0.0.1"
DEFAULT_PORT = 8790

_proc = None          # 只记我们自己拉起的那个，别人手动开的进程不管


def _cfg():
    try:
        return config.load().get("keiwu", {}) or {}
    except Exception:
        return {}


def keiwu_dir():
    return _cfg().get("dir") or DEFAULT_DIR


def keiwu_port():
    try:
        return int(_cfg().get("port") or DEFAULT_PORT)
    except (TypeError, ValueError):
        return DEFAULT_PORT


def keiwu_url():
    return "http://%s:%d" % (HOST, keiwu_port())


def is_running(timeout=0.6):
    """TCP 握手探活：端口开得起来就算在跑（不读 HTTP，省一次超时）。"""
    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex((HOST, keiwu_port())) == 0
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def status():
    d = keiwu_dir()
    return {"ok": True, "running": is_running(), "url": keiwu_url(), "dir": d,
            "has_server": os.path.isfile(os.path.join(d, "server.py")),
            "mine": _proc is not None and _proc.poll() is None}


def ensure(wait=3.0):
    """在跑就直接回；没在跑就拉一个后台进程，最多等 wait 秒。失败只回错误，不抛。"""
    global _proc
    if is_running():
        return status()
    d = keiwu_dir()
    script = os.path.join(d, "server.py")
    if not os.path.isfile(script):
        return {"ok": False, "running": False, "url": keiwu_url(), "dir": d, "has_server": False,
                "error": "找不到课务系统的 server.py：" + script}
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        _proc = subprocess.Popen([sys.executable, script, "--no-browser"], cwd=d,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, creationflags=flags)
    except Exception as e:
        return {"ok": False, "running": False, "url": keiwu_url(), "dir": d, "has_server": True,
                "error": ("拉起失败：" + str(e))[:200]}
    deadline = time.time() + wait
    while time.time() < deadline:
        if is_running():
            break
        time.sleep(0.25)
    st = status()
    st["ok"] = bool(st["running"])
    return st
