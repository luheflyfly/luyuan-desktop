# -*- coding: utf-8 -*-
"""微信登录恢复监视 + 自动复验（夜班一次性收尾工具）。

背景：04:1x 微信重启后停在「需在手机上完成登录」，路河醒来手机确认后本脚本
会在 10 分钟内检测到登录恢复，自动跑 verify_wechat_night.py 四道检查，把结果
追加进夜班值班日志（晨报素材）。最多监视 18 轮（约 3 小时）后自动退出。

用法：cd <project-root> && start /b .venv\\Scripts\\python.exe watch_wechat_login.py
（已在后台运行则无需再启；日志：data\\wechat_watch.log）
"""
import io
import os
import sys
import time
import subprocess
import ctypes

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "data", "wechat_watch.log")
DUTY = r"D:\ALL ai work studio\z code\luyuan2\夜班值班日志_2026-09-13.md"


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def wechat_state():
    """返回 'logged_in' / 'login_page' / 'closed'。用窗口尺寸区分登录小窗与主窗。"""
    try:
        import wechat
        h = wechat.find_wechat()
        if not h:
            return "closed", None
        from ctypes import wintypes
        r = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(h, ctypes.byref(r))
        w, hh = r.right - r.left, r.bottom - r.top
        # 登录小窗 ~350x250 逻辑；主窗 ≥700 宽
        if w >= 600 and hh >= 400:
            return "logged_in", h
        return "login_page", h
    except Exception as e:
        log("state err: %s" % e)
        return "closed", None


def run_verify():
    log("登录已恢复，跑 verify_wechat_night.py …")
    try:
        p = subprocess.run(
            [os.path.join(BASE, ".venv", "Scripts", "python.exe"),
             os.path.join(BASE, "verify_wechat_night.py")],
            capture_output=True, timeout=600)
        out = (p.stdout or b"").decode("utf-8", errors="replace")
        tail = "\n".join(out.strip().splitlines()[-8:])
        log("复验输出尾部：\n%s" % tail)
        ok = "4/4" in out or "复验结果：4/4" in out
        line = ("- 2026-09-14 %s | 微信登录恢复后自动复验（verify_wechat_night.py）：%s"
                % (time.strftime("%H:%M"),
                   "4/4 全过 —— A10 完整闭环 ✅（晨报引用此行）" if ok else "未全过，见 data/wechat_watch.log"))
        try:
            with open(DUTY, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
        return ok
    except Exception as e:
        log("verify err: %s" % e)
        return False


def main():
    log("watch 启动：每 10 分钟查一次微信登录状态，最多 18 轮")
    for i in range(18):
        state, h = wechat_state()
        if state == "logged_in":
            ok = run_verify()
            log("复验%s" % ("完成" if ok else "有未过项，详见上方输出"))
            return
        log("第 %d 轮：state=%s，继续等" % (i + 1, state))
        time.sleep(600)
    log("监视 3 小时到点退出，微信仍未登录恢复（路河醒来后手动跑 verify_wechat_night.py）")


if __name__ == "__main__":
    main()
