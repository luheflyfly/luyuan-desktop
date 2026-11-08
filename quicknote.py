#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路远 · 速记悬浮窗：独立 tkinter 进程（系统 Python 3.14 运行）。

联想键/托盘唤出的小窗：打字 → Enter 直接保存，不进主界面。
- Enter    保存并清空（可连续记）
- Esc      关闭窗口
- 保存优先走本机 API(8777)；API 不在时直接按 SYNC_FORMAT 写 data/notes/（离线兜底）
- 单实例：UDP 8780；主程序发 {"kind":"show"} 唤出、{"kind":"quit"} 关闭
"""
import json
import os
import socket
import sys
import threading
import uuid
import datetime

import tkinter as tk

PORT = 8780
BASE = r"D:\Luyuan"
POS_FILE = os.path.join(BASE, "data", "quicknote_pos.json")

BG = "#1b2030"
LINE = "#2c3654"
TXT = "#e8efff"
SUB = "#93a1c4"


def _win11_round(widget):
    try:
        import ctypes
        hwnd = widget.winfo_id()
        pref = ctypes.c_int(2)  # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), 4)
    except Exception:
        pass


def _pos_load():
    try:
        with open(POS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _pos_save(x, y):
    try:
        with open(POS_FILE, "w", encoding="utf-8") as f:
            json.dump({"x": x, "y": y}, f)
    except Exception:
        pass


def save_note(text):
    text = (text or "").strip()
    if not text:
        return "（空）"
    # 优先走本机 API
    try:
        import urllib.request
        payload = json.dumps({"text": text, "source": "manual"}).encode("utf-8")
        req = urllib.request.Request("http://127.0.0.1:8777/api/notes",
                                     data=payload,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3)
        return "✓ 已保存"
    except Exception:
        pass
    # 离线兜底：直接按 SYNC_FORMAT 写文件
    try:
        nid = str(uuid.uuid4())
        note = {"id": nid,
                "created_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                "text": text, "source": "manual", "tags": []}
        d = os.path.join(BASE, "data", "notes")
        os.makedirs(d, exist_ok=True)
        fname = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + "_" + nid[:8] + ".json"
        with open(os.path.join(d, fname), "w", encoding="utf-8") as f:
            json.dump(note, f, ensure_ascii=False, indent=2)
        return "✓ 已保存（离线）"
    except Exception as e:
        return "✗ 保存失败：" + str(e)[:60]


class QuickNote:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("路远速记")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG, highlightthickness=1, highlightbackground=LINE)
        self._build()
        self._place()
        try:
            import ctypes
            hwnd = self.root.winfo_id()
            pref = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), 4)
        except Exception:
            pass
        # UDP 单实例 + 主程序消息
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(("127.0.0.1", PORT))
            self.sock.setblocking(False)
            self.root.after(80, self._poll)
        except OSError:
            sys.exit(0)   # 已有速记窗在跑

    def _build(self):
        row = tk.Frame(self.root, bg=BG)
        row.pack(fill="x", padx=(14, 10), pady=(10, 0))
        tk.Label(row, text="⚡ 速记", fg=TXT, bg=BG,
                 font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        tk.Label(row, text="Enter 保存 · Esc 关闭", fg=SUB, bg=BG,
                 font=("Microsoft YaHei UI", 9)).pack(side="right")
        self.text = tk.Text(self.root, width=42, height=6, bg=BG, fg=TXT,
                            insertbackground=TXT, relief="flat",
                            font=("Microsoft YaHei UI", 12), undo=True)
        self.text.pack(padx=14, pady=(6, 4))
        self._placeholder = "记点什么…"
        self.text.insert("1.0", self._placeholder)
        self.text.config(fg=SUB)
        self.text.bind("<KeyPress>", self._clear_ph)
        self.tip = tk.Label(self.root, text="", fg="#46d39a", bg=BG,
                            font=("Microsoft YaHei UI", 9))
        self.tip.pack(anchor="w", padx=14, pady=(0, 4))
        self.text.focus()
        self.text.bind("<Return>", self._on_return)
        self.root.bind("<Escape>", self._on_esc)
        self._drag = {"x": 0, "y": 0}
        for w in (self.root, row):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

    def _clear_ph(self, e=None):
        if self.text.get("1.0", "end").strip() == self._placeholder:
            self.text.delete("1.0", "end")
            self.text.config(fg=TXT)

    def _drag_start(self, e):
        self._drag = {"x": e.x, "y": e.y}

    def _drag_move(self, e):
        x = self.root.winfo_x() + e.x - self._drag["x"]
        y = self.root.winfo_y() + e.y - self._drag["y"]
        self.root.geometry("+%d+%d" % (x, y))

    def _place(self):
        pos = _pos_load()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if pos:
            x, y = int(pos.get("x", 0)), int(pos.get("y", 0))
        else:
            x, y = sw - 420, 160
        self.root.geometry("+%d+%d" % (max(0, min(x, sw - 380)), max(0, min(y, sh - 260))))

    def _on_return(self, e):
        if e.state & 0x0001:   # Shift+Enter = 换行
            return
        text = self.text.get("1.0", "end").strip()
        if not text or text == self._placeholder:
            return "break"
        self.tip.config(text=save_note(text), fg="#46d39a")
        self.text.delete("1.0", "end")
        self.text.focus()
        return "break"

    def _on_esc(self, e):
        _pos_save(self.root.winfo_x(), self.root.winfo_y())
        self.root.withdraw()   # 隐藏不销毁：下次唤出瞬时出现

    def _poll(self):
        try:
            while True:
                data, _ = self.sock.recvfrom(4096)
                try:
                    msg = json.loads(data.decode("utf-8", "ignore"))
                except Exception:
                    continue
                if msg.get("kind") == "show":
                    self.root.after(0, self._show)
                elif msg.get("kind") == "quit":
                    _pos_save(self.root.winfo_x(), self.root.winfo_y())
                    self.root.after(0, self.root.destroy)
                    return
        except BlockingIOError:
            pass
        except Exception:
            pass
        self.root.after(80, self._poll)

    def _show(self):
        self.root.deiconify()
        self.root.lift()
        self.text.focus()
        # 全选已有内容，直接打字即可覆盖
        self.text.tag_add("sel", "1.0", "end")


if __name__ == "__main__":
    QuickNote().root.mainloop()
