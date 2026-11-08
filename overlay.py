#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路远 · 悬浮层 v2.3（tkinter 引擎 + 超采样位图 UI，严格对齐视觉稿）。

v2.3（2026-09-07 午后 · 用户实测四连反馈）：
  ① quicknote 消息改「开/关切换」——速记卡开着再按天禧键=收起（切换做在悬浮层内部，
     主程序无脑发同一条消息也不会失步；Esc 收起后下次按键也不会反向失步）
  ② 弹出即聚焦：focus() → focus_force()（overrideredirect 窗口必须 force，
     否则还要点一下文本框才能打字），保存后同样 force 回焦点可连记
  ③ 记忆位置有效性校验 _valid_pos：负坐标/几乎全在屏外 → 视为无效落默认位，
     保存前同样校验（修「收到左上角屏幕外」）
  ④ 速记卡开着时录音结束（rec_phase/rec_stop）不再去动不存在的胶囊件（防 TclError+误收起）

v2.0（2026-09-07）：pywebview 因 WebView2 自动更新反复损坏 → 方案二纯 tkinter 重写。
v2.1：Canvas 手绘胶囊——多边形模拟圆角有锯齿、灰垫层假投影发闷、点制字体×像素制
      窗口在高 DPI 缩放屏上比例失调。
v2.2（2026-09-07 · WorkBuddy 接手 UI）：按《悬浮层视觉稿》(ui_drafts/overlay-mockup.html)
重写渲染层，数据与窗口逻辑一行未动：
  · 圆角胶囊 / 速记卡 / chips / 按钮 / 圆点 全部改为 4x 超采样位图（纯标准库 zlib+struct
    手写 PNG 编码，二值 alpha → 边缘平滑无锯齿、无透明色彩边），零第三方依赖
  · 呼吸环 / 识别 spinner = 12 帧预渲染位图轮播（替代锯齿 canvas oval/arc）
  · 全要素 DPI 等比缩放：窗口尺寸、间距、字号（负数字号=像素）统一按 s=dpi/96 缩放
  · 间距/字号/配色逐项对齐视觉稿：胶囊 padding 14/18、圆点 12、标题 14、计时 12 等宽、
    把手 4×26；速记卡 344 宽 radius 20、logo 16、输入 17px、chips 11px、蓝色保存按钮
  · 去掉灰垫层假投影（位图方案只能做实心灰块反而更丑；干净 1px 描边更贴"纸白"语言）
消息协议（UDP 8780）与窗口管理逻辑不变：
  rec_start → 聆听中胶囊   rec_phase → 识别中   rec_stop → 已记录
  quicknote → 速记卡片     hide → 收起           quit → 退出
窗口常驻（收起=移屏外，句柄永活 → 瞬时弹出；main.py 用 GetWindowRect left<0 判收起）。
保存优先本机 API(8777)，不在时按 SYNC_FORMAT 直接写 data/notes/（离线兜底）。
运行环境：系统 Python 3.14（自带 tkinter），由 main.py 拉起。
测试口：LUYUAN_OVERLAY_PORT / LUYUAN_OVERLAY_POS 环境变量可覆盖（默认行为不变）。
"""
import base64
import datetime
import json
import math
import os
import socket
import struct
import threading
import time
import urllib.request
import uuid
import zlib

import tkinter as tk
import tkinter.font as tkfont

PORT = int(os.environ.get("LUYUAN_OVERLAY_PORT", "8780"))
BASE = r"D:\Luyuan"
POS_FILE = os.environ.get("LUYUAN_OVERLAY_POS") or os.path.join(
    BASE, "data", "overlay_pos.json")

MAGIC = "#010203"          # 透明色（抠窗口四角；UI 内绝不使用此色）
CARD = "#ffffff"
CARD_LINE = "#e8ebf0"      # 1px 淡描边（视觉稿 border rgba(0,0,0,.06)）
TXT = "#1f2937"
SUB = "#6b7280"
BLUE = "#3b82f6"
BLUE_FADE = "#dbeafe"      # 呼吸环渐隐终点
BLUE_TINT = "#eff6ff"
BLUE_TINT_LINE = "#dbeafe"
GREEN = "#10b981"
AMBER = "#f59e0b"
CHIP_BG = "#f3f4f6"
CHIP_LINE = "#e5e7eb"
HANDLE = "#dfe3ea"

HIDDEN_X, HIDDEN_Y = -320, -200
FONT_UI = "Microsoft YaHei UI"


def _now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _pos_load():
    try:
        with open(POS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _pos_save(d):
    try:
        with open(POS_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception:
        pass


def _olog(msg):
    try:
        with open(os.path.join(BASE, "data", "overlay.log"), "a",
                  encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(msg) + "\n")
    except Exception:
        pass


def _parent_alive(ppid):
    """父进程（主程序 main.py）是否还活着。Windows：OpenProcess + GetExitCodeProcess。
    探测异常一律返回 True（宁可多活，不可误杀自己的浮层）。"""
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
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(ppid))
        if not h:
            return False              # 打不开句柄 = 进程已不存在
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    except Exception:
        return True


def _main_mutex_alive():
    """主程序的内核命名互斥锁是否还在（= 主进程活着）。
    比 ppid 探测更权威、无延迟：进程一死，内核立刻销毁它持有的锁。
    返回 True/False；探测本身异常返回 None（不表态，交由 ppid 兜底）。"""
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenMutexW.restype = wintypes.HANDLE
        k32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                   ctypes.c_wchar_p]
        SYNCHRONIZE = 0x00100000
        h = k32.OpenMutexW(SYNCHRONIZE, False, "Local\\LuyuanMainKernel")
        if h:
            k32.CloseHandle(h)
            return True          # 能打开 = 锁在 = 主进程活着
        return False             # 打不开 = 锁已随主进程销毁
    except Exception:
        return None


def _parent_watchdog(ppid, interval=3.0):
    """主程序退出/被杀后自动收掉浮层，杜绝孤儿浮窗（2026-09-13）。

    判定优先用「主程序内核锁是否还在」——权威且无延迟（进程一死锁立即消失）；
    锁明确不在 → 立即自尽。锁探测不确定（None）时才退回 ppid 判定。
    两者都不确定则不动手（宁可不误杀）。设 LUYUAN_OVERLAY_NO_WATCHDOG=1 可关闭。
    """
    if os.environ.get("LUYUAN_OVERLAY_NO_WATCHDOG"):
        return
    while True:
        time.sleep(interval)
        m = _main_mutex_alive()
        if m is False:
            _olog("main mutex gone -> overlay self-exit")
            os._exit(0)
        if m is None and not _parent_alive(ppid):
            _olog("parent %s gone -> overlay self-exit" % ppid)
            os._exit(0)


def _lerp(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _receipt_of(r):
    """把 /api/terminal 的返回压成一句速记窗回执。"""
    try:
        if not r.get("ok"):
            return "✗ " + str(r.get("error") or "没成功")[:20]
        for a in (r.get("actions") or []):
            lab = a.get("label")
            if lab:
                return str(lab)[:22]
        return "✓ 已保存"
    except Exception:
        return "✓ 已保存"


def save_note(text):
    """速记窗回车提交（2026-09-13 升级：接上「超级输入框」完整意图路由）。

    以前这里直接 POST /api/notes（只会存笔记），所以速记窗里输入
    「回他：书在三楼」也只会变成一条笔记、不会发出去。现在改走
    /api/terminal —— 与面板输入框行为完全一致：
      · 「回他：…」/「回复张三：…」 → 直接发微信
      · 「买咖啡 12」                → 记账
      · 其余普通文字                → 存笔记（router 兜底，内容永不丢）
    服务不可用时依次退到：直存笔记(/api/notes) → 本地文件兜底。
    """
    text = (text or "").strip()
    if not text:
        return "（空）"
    # 1) 完整意图路由（可能调本地模型，timeout 放宽到 15s；调用方已异步，不卡 UI）
    try:
        payload = json.dumps({"text": text, "source": "manual"}).encode("utf-8")
        req = urllib.request.Request("http://127.0.0.1:8777/api/terminal",
                                     data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", "ignore")
        return _receipt_of(json.loads(body or "{}"))
    except Exception:
        pass
    # 2) 路由不可用 → 退回直存笔记（至少内容不丢）
    try:
        payload = json.dumps({"text": text, "source": "manual"}).encode("utf-8")
        req = urllib.request.Request("http://127.0.0.1:8777/api/notes", data=payload,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3)
        return "✓ 已保存"
    except Exception:
        pass
    # 3) 服务全死 → 本地文件兜底
    try:
        nid = str(uuid.uuid4())
        note = {"id": nid, "created_at": _now_iso(),
                "text": text, "source": "manual", "tags": []}
        d = os.path.join(BASE, "data", "notes")
        os.makedirs(d, exist_ok=True)
        fname = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + "_" + nid[:8] + ".json"
        with open(os.path.join(d, fname), "w", encoding="utf-8") as f:
            json.dump(note, f, ensure_ascii=False, indent=2)
        return "✓ 已保存（离线）"
    except Exception as e:
        return "✗ " + str(e)[:50]


# ---------------- 位图渲染（纯标准库） ----------------

def _png_b64(w, h, rgba):
    """RGBA 像素 → base64 PNG（tk.PhotoImage 直接可吃）。"""
    stride = w * 4
    raw = bytearray()
    for y in range(h):
        raw.append(0)                       # filter: None
        raw += rgba[y * stride:(y + 1) * stride]
    comp = zlib.compress(bytes(raw), 9)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n" +
           chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
           chunk(b"IDAT", comp) + chunk(b"IEND", b""))
    return base64.b64encode(png).decode("ascii")


def _inside_rr(px, py, x1, y1, x2, y2, r):
    dx = max(x1 + r - px, px - (x2 - r), 0.0)
    dy = max(y1 + r - py, py - (y2 - r), 0.0)
    return dx * dx + dy * dy <= r * r


def _rr_png(w, h, radius, fill, outline=None, ow=1):
    """抗锯齿圆角矩形 → base64 PNG。
    4x 超采样后按 50% 覆盖率做二值 alpha：边缘平滑，且不产生与窗口透明色
    混合的半透明彩边（-transparentcolor 方案的已知坑）。"""
    ss, n = 4, 16
    half = n / 2.0
    offs = [((i + 0.5) / ss, (j + 0.5) / ss) for i in range(ss) for j in range(ss)]
    fr = (int(fill[1:3], 16), int(fill[3:5], 16), int(fill[5:7], 16))
    if outline:
        orr = (int(outline[1:3], 16), int(outline[3:5], 16), int(outline[5:7], 16))
    else:
        orr, ow = None, 0
    x2f, y2f = float(w), float(h)
    r_in = max(radius - ow, 0.0)
    corners = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (0.5, 0.5))
    buf = bytearray(w * h * 4)
    for y in range(h):
        base = y * w * 4
        for x in range(w):
            px0, py0 = float(x), float(y)
            pts = [(px0 + cx, py0 + cy) for cx, cy in corners]
            if ow:
                if all(_inside_rr(a, b, ow, ow, x2f - ow, y2f - ow, r_in) for a, b in pts):
                    idx = base + x * 4
                    buf[idx:idx + 4] = bytes((fr[0], fr[1], fr[2], 255))
                    continue
            elif all(_inside_rr(a, b, 0.0, 0.0, x2f, y2f, radius) for a, b in pts):
                idx = base + x * 4
                buf[idx:idx + 4] = bytes((fr[0], fr[1], fr[2], 255))
                continue
            cov_o = cov_i = 0
            for ox, oy in offs:
                a, b = px0 + ox, py0 + oy
                if _inside_rr(a, b, 0.0, 0.0, x2f, y2f, radius):
                    cov_o += 1
                    if ow and _inside_rr(a, b, ow, ow, x2f - ow, y2f - ow, r_in):
                        cov_i += 1
            if cov_o < half:
                continue                     # alpha 0 → 露出窗口透明色
            col = fr if (not ow or cov_i >= half) else orr
            idx = base + x * 4
            buf[idx:idx + 4] = bytes((col[0], col[1], col[2], 255))
    return _png_b64(w, h, buf)


def _ring_png(size, r_out, width, color, start=0.0, extent=360.0):
    """抗锯齿圆环（或环上扇段）→ base64 PNG。呼吸环 / spinner 用。"""
    ss, n = 4, 16
    half = n / 2.0
    offs = [((i + 0.5) / ss, (j + 0.5) / ss) for i in range(ss) for j in range(ss)]
    cr = (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))
    r_in = max(r_out - width, 0.0)
    c = size / 2.0
    full = extent >= 359.5
    buf = bytearray(size * size * 4)
    for y in range(size):
        base = y * size * 4
        for x in range(size):
            d0 = math.hypot(x + 0.5 - c, y + 0.5 - c)
            if d0 > r_out + 1.0 or d0 < r_in - 1.0:
                continue                     # 环带外快速跳过（环心是洞，同为全透明）
            cov = 0
            for ox, oy in offs:
                dx, dy = x + ox - c, y + oy - c
                d = math.sqrt(dx * dx + dy * dy)
                if r_in <= d <= r_out:
                    if full:
                        cov += 1
                    else:
                        ang = math.degrees(math.atan2(-dy, dx)) % 360.0
                        if (ang - start) % 360.0 <= extent:
                            cov += 1
            if cov >= half:
                idx = base + x * 4
                buf[idx:idx + 4] = bytes((cr[0], cr[1], cr[2], 255))
    return _png_b64(size, size, buf)


def rrect(cv, x1, y1, x2, y2, r, **kw):
    """平滑多边形模拟圆角矩形（仅剩把手这种小件在用）。"""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
           x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


class Overlay:
    def __init__(self, root):
        self.root = root
        self.root.title("luyuan_overlay")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=MAGIC)
        try:
            self.root.attributes("-transparentcolor", MAGIC)
        except Exception:
            pass
        self.mode = None          # "pill" | "quick"
        self.pill_kind = ""       # ""=聆听 | "phase" | "saved"
        pos = _pos_load()
        self.rec_xy = pos.get("rec")
        self.quick_xy = pos.get("quick")
        self.t0 = time.time()
        self._ph = "记一笔，回车即存…"
        self._anim_after = None
        self._tick_after = None
        self._press = None
        self._ph_cache = {}       # key -> tk.PhotoImage（防 GC）
        self._breath = None       # 呼吸环 12 帧
        self._spin = None         # spinner 12 帧
        # ---- DPI 等比缩放：设计稿以 96dpi CSS 像素为基准 ----
        try:
            self.s = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        except Exception:
            self.s = 1.0
        self.pill_w = int(round(224 * self.s))
        self.pill_h = int(round(46 * self.s))
        self.quick_w = int(round(344 * self.s))
        self.quick_h = int(round(132 * self.s))
        self._build()
        self.root.update_idletasks()
        self._no_taskbar()
        self.root.geometry("+%d+%d" % self._park_xy())   # 开局屏外驻留（按尺寸算）

    # ---------------- 小工具 ----------------
    def _px(self, v):
        return max(1, int(round(v * self.s)))

    def _fs(self, px):
        """CSS 像素字号 → tk 负数字号（负数=像素，正数=点会随 DPI 二次缩放）。"""
        return -max(1, int(round(px * self.s)))

    def _photo(self, key, b64):
        im = self._ph_cache.get(key)
        if im is None:
            im = tk.PhotoImage(data=b64, master=self.root)
            self._ph_cache[key] = im
        return im

    # ---------------- 构建 ----------------
    def _build(self):
        self.cv = tk.Canvas(self.root, bg=MAGIC, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        self.cv.bind("<ButtonPress-1>", self._drag_start)
        self.cv.bind("<B1-Motion>", self._drag_move)
        self.cv.bind("<ButtonRelease-1>", self._click_release)

        self.text = tk.Text(self.cv, bg=CARD, fg=TXT,
                            insertbackground=TXT, relief="flat", bd=0,
                            wrap="word", font=(FONT_UI, self._fs(17)),
                            spacing1=self._px(3), spacing2=self._px(3),
                            selectbackground=BLUE_TINT_LINE,
                            selectforeground=TXT)
        self.text.bind("<KeyPress>", self._clear_ph)
        self.text.bind("<Return>", self._on_return)
        self.text.bind("<Escape>", self._on_esc)
        self.root.bind("<Escape>", self._on_esc)

    # ---------------- 绘制：胶囊 ----------------
    def _draw_pill(self):
        cv = self.cv
        cv.delete("all")
        self.text.place_forget()
        W, H = self.pill_w, self.pill_h
        self.root.geometry("%dx%d" % (W, H))
        self.cv.configure(width=W, height=H)
        cy = H / 2.0
        cv.create_image(0, 0, anchor="nw",
                        image=self._photo("pill", _rr_png(W, H, H / 2.0, CARD,
                                                          CARD_LINE, 1)))
        # 圆点（视觉稿：padding-left 14 + 12px 圆点 → 圆心 x=20）
        self.it_dot = cv.create_image(self._px(20), cy,
                                      image=self._dot_img("blue"))
        self.it_title = cv.create_text(self._px(36), cy, anchor="w", text="聆听中",
                                       fill=TXT, font=(FONT_UI, self._fs(14), "bold"))
        self.it_tm = cv.create_text(W - self._px(28), cy, anchor="e", text="00:00",
                                    fill=SUB, font=("Consolas", self._fs(12)))
        # 拖拽把手 4×26
        x2 = W - self._px(18)
        self.it_handle = rrect(cv, x2 - self._px(4), cy - self._px(13), x2,
                               cy + self._px(13), 2, fill=HANDLE, outline="")
        self.it_ring = None

    def _dot_img(self, name):
        col = {"blue": BLUE, "amber": AMBER, "green": GREEN}[name]
        return self._photo("dot_" + name,
                           _rr_png(self._px(12), self._px(12), self._px(6), col))

    # ---------------- 绘制：速记卡 ----------------
    def _draw_quick(self):
        cv = self.cv
        cv.delete("all")
        W, H = self.quick_w, self.quick_h
        self.root.geometry("%dx%d" % (W, H))
        self.cv.configure(width=W, height=H)
        cv.create_image(0, 0, anchor="nw",
                        image=self._photo("card", _rr_png(W, H, self._px(20), CARD,
                                                          CARD_LINE, 1)))
        # 头部：logo「路」+ 说明
        lg = self._px(16)
        cv.create_image(self._px(24), self._px(20),
                        image=self._photo("logo", _rr_png(lg, lg, self._px(5), BLUE)))
        cv.create_text(self._px(24), self._px(20), text="路", fill="#ffffff",
                       font=(FONT_UI, self._fs(10), "bold"))
        cv.create_text(self._px(40), self._px(20), anchor="w", text="速记 · 随手一句",
                       fill=SUB, font=(FONT_UI, self._fs(12)))
        # 输入区（17px 大字）
        self.text.configure(font=(FONT_UI, self._fs(17)),
                            spacing1=self._px(3), spacing2=self._px(3))
        self.cv.create_window(self._px(17), self._px(38), anchor="nw",
                              window=self.text,
                              width=W - self._px(34), height=self._px(50))
        # 快捷键 chips（按文本实测宽度排布，杜绝截断）
        cy1, cy2 = H - self._px(36), H - self._px(12)
        x = self._px(16)
        x = self._chip("chip_f10", x, cy1, cy2, "F10 说话",
                       BLUE_TINT, BLUE_TINT_LINE, BLUE)
        x = self._chip("chip_save", x, cy1, cy2, "⏎ 保存", CHIP_BG, CHIP_LINE, SUB)
        self._chip("chip_esc", x, cy1, cy2, "Esc 收起", CHIP_BG, CHIP_LINE, SUB)
        # 保存按钮（比 chips 高一档，视觉稿同款胶囊）
        f_btn = tkfont.Font(family=FONT_UI, size=self._fs(12), weight="bold")
        bw = max(f_btn.measure("保存"), f_btn.measure("✓ 已存")) + self._px(28)
        bh = cy2 - cy1 + self._px(4)
        bx2 = W - self._px(16)
        byc = (cy1 + cy2) / 2.0
        self._btn_w, self._btn_h = bw, bh
        self.it_btn = cv.create_image(bx2 - bw / 2.0, byc,
                                      image=self._photo("btn_blue",
                                                        _rr_png(bw, bh, bh / 2.0, BLUE)))
        self._photo("btn_green", _rr_png(bw, bh, bh / 2.0, GREEN))   # 预渲染闪绿反馈
        self.it_btn_txt = cv.create_text(bx2 - bw / 2.0, byc, text="保存",
                                         fill="#ffffff", font=f_btn)
        cv.tag_bind(self.it_btn, "<ButtonRelease-1>", self._btn_save)
        cv.tag_bind(self.it_btn_txt, "<ButtonRelease-1>", self._btn_save)

    def _chip(self, key, x, y1, y2, label, bg, line, fg):
        f = tkfont.Font(family=FONT_UI, size=self._fs(11))
        w = f.measure(label) + self._px(20)
        img = self._photo(key, _rr_png(w, y2 - y1, (y2 - y1) / 2.0, bg, line, 1))
        self.cv.create_image(x + w / 2.0, (y1 + y2) / 2.0, image=img)
        self.cv.create_text(x + w / 2.0, (y1 + y2) / 2.0, text=label,
                            fill=fg, font=f)
        return x + w + self._px(8)

    # ---------------- 交互 ----------------
    def _clear_ph(self, e=None):
        if self.text.get("1.0", "end").strip() == self._ph:
            self.text.delete("1.0", "end")
            self.text.config(fg=TXT)

    def _on_return(self, e):
        if e.state & 0x0001:
            return
        self._do_save()
        return "break"

    def _btn_save(self, e=None):
        if self._press and abs(e.x_root - self._press[0]) + \
                abs(e.y_root - self._press[1]) > 6:
            return   # 拖动结束不算点击
        self._do_save()

    def _do_save(self):
        text = self.text.get("1.0", "end").strip()
        if not text or text == self._ph:
            return
        self.text.delete("1.0", "end")
        self.text.focus_force()   # 保存后继续连记，焦点立刻回来
        # 走完整路由可能调本地模型（几百 ms ~ 数秒），必须丢后台线程，
        # 否则 tkinter 主循环会假死（2026-09-13 随「速记窗接路由」一起改）。
        self._flash_btn("…")
        threading.Thread(target=self._save_worker, args=(text,), daemon=True).start()

    def _save_worker(self, text):
        """后台线程：真正提交（网络/模型调用都在这里，不阻塞 UI）。"""
        try:
            msg = save_note(text)
        except Exception as e:
            msg = "✗ " + str(e)[:18]
        try:
            self.root.after(0, lambda m=msg: self._flash_btn(m))
        except Exception:
            pass

    def _flash_btn(self, receipt):
        """按钮闪绿并显示极简回执，1.6s 后恢复「保存」。
        只显示 4 字内符号——按钮位图宽度固定，长文案会溢出圆角。"""
        if not (hasattr(self, "it_btn") and self.mode == "quick"):
            return
        green = self._ph_cache.get("btn_green")
        blue = self._ph_cache.get("btn_blue")
        if not (green and blue):
            return
        r = str(receipt or "")
        if r == "…":
            short = "…"
        elif r.startswith("✗"):
            short = "✗ 失败"
        elif ("已发" in r) or ("发给" in r):
            short = "✓ 已发"
        elif "复制" in r:
            short = "✓ 复制"
        else:
            short = "✓ 已存"
        self.cv.itemconfig(self.it_btn, image=green)
        self.cv.itemconfig(self.it_btn_txt, text=short)
        self.root.after(1600, lambda: (
            self.cv.itemconfig(self.it_btn, image=blue),
            self.cv.itemconfig(self.it_btn_txt, text="保存")))

    def _on_esc(self, e=None):
        self._remember_and_park()

    def _drag_start(self, e):
        self._press = (e.x_root, e.y_root)
        self._drag = {"x": e.x, "y": e.y}

    def _drag_move(self, e):
        if not self._press:
            return
        x = self.root.winfo_x() + e.x - self._drag["x"]
        y = self.root.winfo_y() + e.y - self._drag["y"]
        self.root.geometry("+%d+%d" % (x, y))

    def _click_release(self, e):
        self.root.after(50, lambda: setattr(self, "_press", None))

    # ---------------- 形态切换 ----------------
    def _cancel_anim(self):
        if self._anim_after:
            try:
                self.root.after_cancel(self._anim_after)
            except Exception:
                pass
            self._anim_after = None
        if self._tick_after:
            try:
                self.root.after_cancel(self._tick_after)
            except Exception:
                pass
            self._tick_after = None

    def _show_pill(self):
        self.mode = "pill"
        self.pill_kind = ""
        self._draw_pill()
        self.lbl_reset()
        self._cancel_anim()
        self._anim()
        self.t0 = time.time()
        self._tick()

    def lbl_reset(self):
        self.cv.itemconfig(self.it_title, text="聆听中")
        self.cv.itemconfig(self.it_tm, text="00:00")
        self.cv.itemconfig(self.it_dot, image=self._dot_img("blue"))

    def _pill_phase(self, label):
        if self.mode != "pill":
            return                     # 速记卡正开着时录音结束，别去动不存在的胶囊件
        self.pill_kind = "phase"
        self.cv.itemconfig(self.it_title, text=label)
        self.cv.itemconfig(self.it_tm, text="路远")
        self.cv.itemconfig(self.it_dot, image=self._dot_img("amber"))

    def _pill_saved(self):
        if self.mode != "pill":
            return
        self.pill_kind = "saved"
        self.cv.itemconfig(self.it_title, text="✅ 已记录")
        self.cv.itemconfig(self.it_tm, text="点击查看")
        self.cv.itemconfig(self.it_dot, image=self._dot_img("green"))
        if self.it_ring:
            self.cv.delete(self.it_ring)
            self.it_ring = None

    def _show_quick(self):
        self.mode = "quick"
        self.pill_kind = ""
        self._cancel_anim()
        self._draw_quick()
        cur = self.text.get("1.0", "end").rstrip("\n")
        self.text.delete("1.0", "end")
        if cur and cur != self._ph:
            self.text.insert("1.0", cur)
            self.text.config(fg=TXT)
            self.text.tag_add("sel", "1.0", "end")   # 有正文才全选覆盖
        else:
            self.text.insert("1.0", self._ph)
            self.text.config(fg=SUB)
        # ⚠️ focus_force 不在这里做：它可能阻塞（非前台进程 SetFocus 走
        # 前台锁超时路径），拖慢整个弹出；挪到 handle() 里定位完成之后。

    def _ensure_on_top(self):
        """弹出后强制上屏四连。2026-09-11 天禧键「机制全对但用户看不见」加固：
        layered+transparentcolor 窗口在 geometry 变更后，部分 Windows 构建会
        丢 topmost / 不重排 → 内容画了却不出现在屏幕上。每处弹出都调它，
        并把真实 rect/屏幕尺寸写进 overlay.log，出问题一眼定位。"""
        try:
            self.root.update_idletasks()
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            try:
                self.root.attributes("-transparentcolor", MAGIC)  # 变更后重贴色键
            except Exception:
                pass
        except Exception as e:
            _olog("ensure_on_top error: %r" % e)
        try:
            r = (self.root.winfo_x(), self.root.winfo_y(),
                 self.root.winfo_width(), self.root.winfo_height(),
                 self.root.winfo_screenwidth(), self.root.winfo_screenheight())
            return r
        except Exception:
            return None

    def _on_screen(self):
        return self.root.winfo_x() > 0 and self.root.winfo_y() > 0

    def _place_default(self, which):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if which == "pill":
            self.root.geometry("+%d+%d" % (sw - self.pill_w - 20, sh - self.pill_h - 150))
        else:
            self.root.geometry("+%d+%d" % (sw - self.quick_w - 24, sh - self.quick_h - 170))

    def _valid_pos(self, xy):
        """记忆位置有效性校验：负坐标 / 几乎全部在屏外 → 视为无效（落默认位）。
        防止拖到屏幕边缘外还记住、下次弹出到离谱位置（2026-09-07 用户实测）。"""
        if not xy or len(xy) < 2:
            return None
        try:
            x, y = int(xy[0]), int(xy[1])
        except Exception:
            return None
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if x < 0 or y < 0 or x > sw - 60 or y > sh - 40:
            return None
        return [x, y]

    def _popup_at(self, which):
        """弹出时总是落到「该模式自己记住的位置」，没有就用默认位。
        不能依赖窗口当前位置：胶囊与速记卡尺寸不同，若另一形态正开着，
        沿用其坐标会溢出屏幕（2026-09-07 实测 bug）。"""
        xy = self._valid_pos(self.rec_xy if which == "pill" else self.quick_xy)
        if xy:
            self.root.geometry("+%d+%d" % tuple(xy[:2]))
        else:
            self._place_default(which)

    def _park_xy(self):
        """收起位=按当前窗口尺寸算的屏外坐标。固定 -320/-200 是旧版 384 宽卡的标定，
        200% 缩放下速记卡 688 物理宽 → 挪到 -320 右下角还露出 368x64 一条在屏幕左上角
        （2026-09-07 用户实测「收回左上角」真凶）。"""
        w = max(self.pill_w, self.quick_w)
        h = max(self.pill_h, self.quick_h)
        return -(w + 120), -(h + 120)

    def _remember_and_park(self):
        xy = [self.root.winfo_x(), self.root.winfo_y()]
        if self._on_screen() and self._valid_pos(xy):
            if self.mode == "pill":
                self.rec_xy = xy
            elif self.mode == "quick":
                self.quick_xy = xy
            _pos_save({"rec": self.rec_xy, "quick": self.quick_xy})
        self._cancel_anim()
        self.root.geometry("+%d+%d" % self._park_xy())

    # ---------------- 动画（12 帧预渲染位图轮播） ----------------
    def _frames_breath(self):
        size = self._px(34)
        wd = max(2, int(round(2 * self.s)))
        frames = []
        for k in range(12):
            t = k / 12.0
            r = self._px(6.5 + 8.5 * t)
            col = _lerp(BLUE, BLUE_FADE, t)
            frames.append(self._photo("rb%d" % k,
                                      _ring_png(size, r, wd, col)))
        self._breath = frames

    def _frames_spin(self):
        size = self._px(26)
        wd = max(2, int(round(2.5 * self.s)))
        self._spin = [self._photo("sp%d" % k,
                                  _ring_png(size, self._px(9.5), wd, AMBER,
                                            start=k * 30.0, extent=115.0))
                      for k in range(12)]

    def _anim(self):
        if self.mode != "pill":
            return
        now = time.time() - self.t0
        if self.pill_kind == "":
            if self._breath is None:
                self._frames_breath()
            k = int(now / 1.6 * 12) % 12
            if self.it_ring is None:
                self.it_ring = self.cv.create_image(self._px(20), self.pill_h / 2.0,
                                                    image=self._breath[k])
            else:
                self.cv.itemconfig(self.it_ring, image=self._breath[k])
            self._anim_after = self.root.after(33, self._anim)
        elif self.pill_kind == "phase":
            if self._spin is None:
                self._frames_spin()
            k = int(now / 1.0 * 12) % 12
            if self.it_ring is None:
                self.it_ring = self.cv.create_image(self._px(20), self.pill_h / 2.0,
                                                    image=self._spin[k])
            else:
                self.cv.itemconfig(self.it_ring, image=self._spin[k])
            self._anim_after = self.root.after(33, self._anim)

    def _tick(self):
        if self.mode != "pill" or self.pill_kind:
            return
        el = int(time.time() - self.t0)
        self.cv.itemconfig(self.it_tm, text="%02d:%02d" % (el // 60, el % 60))
        self._tick_after = self.root.after(400, self._tick)

    def _no_taskbar(self):
        try:
            import ctypes
            hwnd = int(self.root.winfo_id())
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, -20)
            user32.SetWindowLongW(hwnd, -20, style | 0x00000080)
        except Exception as e:
            _olog("no_taskbar error: %r" % e)

    # ---------------- 消息处理（协议不变） ----------------
    def handle(self, msg):
        try:
            kind = msg.get("kind")
            # 防抖（2026-09-11 加固）：600ms 内重复的同类消息只认第一条，
            # 防按键抖动/双重触发导致「弹出立刻被 toggle 收回」的闪没。
            now = time.time()
            if kind in ("quicknote", "rec_start") and \
                    getattr(self, "_last_kind", None) == kind and \
                    now - getattr(self, "_last_kind_t", 0) < 0.6:
                _olog("%s debounced" % kind)
                return
            if kind in ("quicknote", "rec_start"):
                self._last_kind = kind
                self._last_kind_t = now
            if kind == "rec_start":
                self._show_pill()
                self._popup_at("pill")
                r = self._ensure_on_top()
                _olog("rec_start shown %r" % (r,))
            elif kind == "rec_phase":
                self._pill_phase(msg.get("title", "识别中"))
            elif kind == "rec_stop":
                self._pill_saved()
                self.root.after(2000, self._remember_and_park)
            elif kind == "quicknote":
                # 开/关切换（2026-09-07 用户拍板）：速记卡开着 → 收起；没开 → 弹出。
                # 切换做在悬浮层内部（它自己知道开没开），主程序无脑发同一条消息也不会失步。
                if self.mode == "quick" and self._on_screen():
                    _olog("quick toggled off")
                    self._remember_and_park()
                else:
                    self._show_quick()
                    self._popup_at("quick")
                    self._no_taskbar()
                    r = self._ensure_on_top()
                    # 焦点必须在定位+上屏之后给：overrideredirect 窗口 focus() 不够，
                    # 必须 force 才能直接打字；且不能让它的耗时挡住上屏动作
                    self.text.focus_force()
                    self.text.mark_set("insert", "1.0")
                    _olog("quick shown %r" % (r,))
            elif kind == "hide":
                self._remember_and_park()
            elif kind == "quit":
                self._remember_and_park()
                self.root.after(0, self.root.destroy)
                os._exit(0)
        except Exception as e:
            _olog("handle error: %r" % e)


def udp_loop(ov, sk):
    while True:
        try:
            while True:
                data, _ = sk.recvfrom(4096)
                try:
                    msg = json.loads(data.decode("utf-8", "ignore"))
                except Exception:
                    continue
                ov.root.after(0, ov.handle, msg)
        except BlockingIOError:
            pass
        except Exception as e:
            _olog("udp error: %r" % e)
        time.sleep(0.05)


if __name__ == "__main__":
    # 先抢端口：抢不到 = 已有实例 → 立即退出（绝不做僵尸）
    sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sk.bind(("127.0.0.1", PORT))
        sk.setblocking(False)
    except OSError:
        os._exit(0)
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    root = tk.Tk()
    ov = Overlay(root)
    threading.Thread(target=udp_loop, args=(ov, sk), daemon=True).start()
    # 父进程看门狗（2026-09-13）：主程序退出/被杀后自动收掉浮层，
    # 杜绝「主程序关了、语音浮窗还在」的孤儿窗口。
    threading.Thread(target=_parent_watchdog, args=(os.getppid(),),
                     daemon=True).start()
    root.mainloop()
