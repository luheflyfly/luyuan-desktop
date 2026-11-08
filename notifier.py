#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路远 桌面通知器：独立的 tkinter 进程（用带 tkinter 的 Python 启动）。

监听本地 UDP 8779，收到消息后在屏幕右下角弹出：
  - 瞬时通知 toast（自动消失）
  - 录音中常驻小窗（红点闪烁 + 计时），停止时消失

主程序 main.py 通过 UDP 发消息，本进程无需具备录音/转写能力。
单实例：若 8779 已被占用（已有通知器在跑），直接退出。
"""
import json
import os
import socket
import sys
import time

import tkinter as tk

HOST = "127.0.0.1"
PORT = 8779

# ---------- 配色（指示窗） ----------
BG = "#1b2030"        # 底色
LINE = "#2c3654"      # 边框
TXT = "#e8efff"       # 主文字
SUB = "#93a1c4"       # 次文字/计时
DOT_ON = "#6ea8ff"    # 呼吸点亮
DOT_OFF = "#2c4a86"   # 呼吸灯暗
DOT_PHASE = "#ffce5a" # 识别中
BAR_LISTEN = "#6ea8ff"
BAR_PHASE = "#ffce5a"


def _win11_round(widget):
    """Win11 DWM 真·圆角 + 投影（失败静默，Win10 无圆角但不报错）。"""
    try:
        import ctypes
        hwnd = widget.winfo_id()
        if not hwnd:
            return
        # overrideredirect 顶层窗口：winfo_id 即顶层 hwnd；保险再取一次父窗
        pref = ctypes.c_int(2)  # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(pref), 4)  # DWMWA_WINDOW_CORNER_PREFERENCE
    except Exception:
        pass


class Notifier:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        try:
            self.root.attributes("-topmost", True)
        except Exception:
            pass
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind((HOST, PORT))
        except OSError:
            # 已有通知器在运行，单实例，直接退出
            sys.exit(0)
        self.sock.setblocking(False)
        self.toasts = []          # (win, expire_ms, height)
        self.rec = None           # 录音常驻窗
        self.rec_start = 0.0
        self._blink = False
        self.root.after(60, self._poll)
        self.root.mainloop()

    # ---------- 网络 ----------
    def _poll(self):
        try:
            while True:
                data, _ = self.sock.recvfrom(65535)
                try:
                    self._handle(json.loads(data.decode("utf-8", "ignore")))
                except Exception:
                    pass
        except BlockingIOError:
            pass
        except Exception:
            pass
        self._tick()
        self.root.after(60, self._poll)

    def _handle(self, msg):
        kind = (msg or {}).get("kind")
        if kind == "toast":
            self._toast(msg.get("title", ""), msg.get("body", ""),
                        int(msg.get("ms", 3000)))
        elif kind == "rec_start":
            self._rec_show(msg.get("title", "聆听中"), msg.get("body", ""))
        elif kind == "rec_phase":
            # 录音结束进入转写：同一窗换状态，黄点 + 黄色条，撤掉提示小字
            if self.rec is not None and self.rec.winfo_exists():
                try:
                    self.rec_label.config(text=msg.get("title", "识别中…"))
                    self.rec_dot.config(fg=DOT_PHASE)
                    self.rec_bar.config(bg=BAR_PHASE)
                    if self.rec_body is not None:
                        self.rec_body.destroy()
                        self.rec_body = None
                except Exception:
                    pass
        elif kind == "rec_stop":
            self._rec_hide()
            if msg.get("body"):
                self._toast(msg.get("title", "✅ 已记录"), msg.get("body", ""),
                            int(msg.get("ms", 3000)))
        elif kind == "hide":
            self._rec_hide()
        elif kind == "quit":
            self.root.after(0, self.root.destroy)

    # ---------- 瞬时 toast ----------
    def _toast(self, title, body, ms):
        w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg=BG, highlightthickness=1, highlightbackground=LINE)
        bar = tk.Frame(w, bg=BAR_LISTEN, width=4)
        bar.pack(side="left", fill="y")
        inner = tk.Frame(w, bg=BG)
        inner.pack(side="left", fill="both", expand=True, padx=12, pady=9)
        if title:
            tk.Label(inner, text=title, bg=BG, fg=TXT,
                     font=("Microsoft YaHei UI", 11, "bold"),
                     anchor="w").pack(anchor="w")
        if body:
            tk.Label(inner, text=body, bg=BG, fg=SUB,
                     font=("Microsoft YaHei UI", 10), anchor="w",
                     wraplength=300, justify="left").pack(anchor="w", pady=(4, 0))
        w.update_idletasks()
        _win11_round(w)
        h = w.winfo_height()
        self.make_draggable(w)
        self.toasts.append((w, time.time() * 1000 + ms, h))
        self._layout()

    # ---------- 录音指示窗 ----------
    def _rec_show(self, title, body):
        self._rec_hide()
        w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg=BG, highlightthickness=1, highlightbackground=LINE)
        row = tk.Frame(w, bg=BG)
        row.pack(padx=16, pady=10)
        self.rec_bar = tk.Frame(w, bg=BAR_LISTEN, width=4)
        self.rec_bar.pack(side="left", fill="y")
        self.rec_dot = tk.Label(row, text="●", fg=DOT_ON, bg=BG,
                                font=("Microsoft YaHei UI", 10))
        self.rec_dot.pack(side="left")
        self.rec_label = tk.Label(row, text=title, fg=TXT, bg=BG,
                                  font=("Microsoft YaHei UI", 11, "bold"))
        self.rec_label.pack(side="left", padx=(9, 0))
        self.rec_time = tk.Label(row, text="00:00", fg=SUB, bg=BG,
                                 font=("Consolas", 11))
        self.rec_time.pack(side="left", padx=(12, 0))
        self.rec_body = None
        if body:
            self.rec_body = tk.Label(w, text=body, fg=SUB, bg=BG,
                                     font=("Microsoft YaHei UI", 9))
            self.rec_body.pack(anchor="w", padx=16, pady=(0, 9))
        self.rec = w
        self.rec_start = time.time()
        w.update_idletasks()
        _win11_round(w)
        self.make_draggable(w)
        self._layout()
        self._rec_tick()

    def _rec_hide(self):
        if self.rec is not None:
            try:
                self.rec.destroy()
            except Exception:
                pass
            self.rec = None
        self._layout()

    def _rec_tick(self):
        if self.rec is None or not self.rec.winfo_exists():
            return
        el = int(time.time() - self.rec_start)
        self.rec_time.config(text="%02d:%02d" % (el // 60, el % 60))
        self._blink = not self._blink
        self.rec_dot.config(fg=DOT_ON if self._blink else DOT_OFF)
        self.rec.after(500, self._rec_tick)

    # ---------- 拖拽 ----------
    def make_draggable(self, win):
        """让无边框窗口可鼠标拖动；拖动后记住位置，自动布局不再覆盖。"""
        win._drag_pos = None
        win._drag_data = {"x": 0, "y": 0}

        def start(ev):
            win._drag_data["x"] = ev.x_root
            win._drag_data["y"] = ev.y_root

        def move(ev):
            dx = ev.x_root - win._drag_data["x"]
            dy = ev.y_root - win._drag_data["y"]
            x = win.winfo_x() + dx
            y = win.winfo_y() + dy
            win.geometry("+%d+%d" % (x, y))
            win._drag_data["x"] = ev.x_root
            win._drag_data["y"] = ev.y_root
            win._drag_pos = (x, y)

        for target in (win,) + tuple(win.winfo_children()):
            target.bind("<ButtonPress-1>", start)
            target.bind("<B1-Motion>", move)
            try:
                target.configure(cursor="fleur")
            except Exception:
                pass

    # ---------- 布局 ----------
    def _layout(self):
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
        except Exception:
            return
        if self.rec is not None and self.rec.winfo_exists():
            self.rec.update_idletasks()
            rh = self.rec.winfo_height()
            pos = getattr(self.rec, "_drag_pos", None)
            if pos:
                rx, ry = pos
            else:
                rx = sw - self.rec.winfo_width() - 18
                ry = sh - rh - 18
            self.rec.geometry("+%d+%d" % (rx, ry))
            base = 18 + rh + 10
        else:
            base = 18
        y = sh - base
        for (w, exp, h) in self.toasts:
            if not w.winfo_exists():
                continue
            tw = w.winfo_width()
            pos = getattr(w, "_drag_pos", None)
            if pos:
                wx, wy = pos
            else:
                wx = sw - tw - 18
                wy = y - h
            w.geometry("+%d+%d" % (wx, wy))
            y -= h + 10

    def _tick(self):
        now = time.time() * 1000
        changed = False
        for item in list(self.toasts):
            w, exp, h = item
            if not w.winfo_exists() or now >= exp:
                try:
                    w.destroy()
                except Exception:
                    pass
                self.toasts.remove(item)
                changed = True
        if changed:
            self._layout()


if __name__ == "__main__":
    Notifier()
