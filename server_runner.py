"""路远 Web 服务独立进程入口（由 main.py 拉起，与 GUI 进程解耦）。

单独成进程的好处：即使托盘 / 浮层 / 剪贴板等 GUI 原生组件在异常会话里
崩溃（例如无交互桌面的自动化环境），Web 服务（面板 + REST API）依然存活，
不会被连带拖垮。等同于此前能稳定存活的诊断用 uvicorn 形态。

单实例保护：端口已被占用（另一个路远进程已监听）时直接退出，
避免并发拉起 / 重启产生第二个 server_runner 抢端口、互相清场互杀。
"""
import os
import sys
import socket
import logging
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import config
import server

log = logging.getLogger("server_runner")
logging.basicConfig(level=logging.INFO)

cfg = config.load()["server"]
host = cfg["host"]
port = cfg["port"]


def _port_already_listening(host, port):
    """探测端口是否已被监听（自己人已占用）。0.0.0.0 绑定时用 127.0.0.1 探活。"""
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(1.0)
        s.connect((probe_host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _parent_alive(ppid):
    """父进程（main.py）是否还活着。探测异常一律返回 True（宁可多活，不误自杀）。"""
    if not ppid or int(ppid) <= 0:
        return True
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                           ctypes.POINTER(wintypes.DWORD)]
        h = k32.OpenProcess(0x1000, False, int(ppid))   # QUERY_LIMITED_INFORMATION
        if not h:
            return False                                # 打不开 = 进程已不存在
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == 259                    # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    except Exception:
        return True


def _parent_watchdog(ppid, interval=3.0):
    """主程序退出/被杀后自动收掉服务进程，杜绝「孤儿 server_runner 占着 8777」
    → 新实例一看端口被占就误判「已在运行」而拒绝启动（2026-09-13 根因修复）。"""
    while True:
        time.sleep(interval)
        if not _parent_alive(ppid):
            log.info("父进程 %s 已退出，server_runner 自尽（杜绝孤儿占端口）", ppid)
            os._exit(0)


if _port_already_listening(host, port):
    log.info("端口 %s:%s 已被其他路远进程监听，server_runner 单实例退出", host, port)
    sys.exit(0)

# 父进程看门狗（2026-09-13）：主程序退出/被杀后，服务进程自己收掉，
# 从源头杜绝「孤儿 server_runner 占着 8777 → 新实例误判已在运行 → 拒绝启动」。
threading.Thread(target=_parent_watchdog, args=(os.getppid(),), daemon=True).start()

try:
    server.run(host=host, port=port)
except OSError as e:
    # 极端竞态下两个进程同时到达绑定：后到者绑不上也直接退出，不报错不残留
    msg = str(e).lower()
    if "address already in use" in msg or "10048" in msg:
        log.info("端口 %s:%s 绑定被占（竞态），server_runner 退出", host, port)
        sys.exit(0)
    raise
