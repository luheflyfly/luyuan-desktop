# -*- coding: utf-8 -*-
"""稍后读（灵感.md 用户点名功能）：剪贴板仅对网址自动触发 + 热键手动双通道。

- 只认「整条剪贴板就是一个网址」——密码/验证码/普通文本一律不碰（隐私红线）。
- 抓标题+正文存笔记打「稍后读」标签，原图链接永远在笔记里。
- 抓取失败重试 3 次后标记放弃（笔记留着，用户可手动开链接）。
- 状态记在笔记自有字段 rl_state：pending→done/failed（SYNC_FORMAT 未知字段
  两端一律忽略，零契约变更）。
"""
import ctypes
import html as _html
import html.parser as _hp
import json
import logging
import os
import re
import threading
import time

import config
import store

log = logging.getLogger("readlater")

_BASE = os.path.dirname(os.path.abspath(__file__))
_URL_RE = re.compile(r"^https?://[^\s]+$", re.I)
_TRAIL = "。，、）】」》\"'”’)]>}＞>."
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_STRIP_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.I | re.S)

_FETCHING = {}          # nid -> True（并发守卫）
_NEXT_TRY = {}          # nid -> 下次可重试的 epoch（退避，仅内存）
_cfg_cache = {}


def _cfg():
    key = "rl_cfg"
    c = _cfg_cache.get(key)
    if c:
        return c
    r = config.load().get("readlater", {})
    c = {
        "enabled": bool(r.get("enabled", True)),
        "interval": max(2, int(r.get("interval", 3) or 3)),
        "max_body": int(r.get("max_body", 30000) or 30000),
        "retries": int(r.get("retries", 3) or 3),
        "timeout": int(r.get("timeout", 15) or 15),
    }
    _cfg_cache[key] = c
    return c


def normalize_url(text):
    """整条文本 → 网址（去首尾空白与中文标点尾巴）；不是纯网址返回 None。"""
    t = (text or "").strip()
    if len(t) > 2000:
        return None
    while t and t[-1] in _TRAIL:
        t = t[:-1].rstrip()
    return t if _URL_RE.match(t) else None


# ---------------- 剪贴板（ctypes，零新依赖） ----------------
# ⚠️ 2026-09-08 深夜血案根因（托盘/热键全灭的真凶）：windll 函数不声明原型时
# 返回值按 32 位 c_int 截断——64 位 Windows 上 GetClipboardData/GlobalLock 的
# 句柄被切掉高 32 位，**剪贴板非空时** → _ctypes.pyd 原生段错误（0xc0000005）
# → 整个 main.py 无声暴毙（空剪贴板时句柄为 0 提前返回，所以"时好时坏"）。
# 修复=全部显式声明 argtypes/restype，句柄按 64 位 c_void_p 走。
_CLIP_PROTO_DONE = False


def _clip_prototypes(user32, kernel32):
    global _CLIP_PROTO_DONE
    if _CLIP_PROTO_DONE:
        return
    import ctypes
    user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
    user32.IsClipboardFormatAvailable.restype = ctypes.c_int
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_int
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_int
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_int
    _CLIP_PROTO_DONE = True


def get_clipboard_text():
    import ctypes
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        _clip_prototypes(user32, kernel32)
        # 无交互桌面（服务/无界面会话）下读剪贴板会段错误，直接跳过；
        # 交互桌面会话里 GetDesktopWindow 返回非空句柄，照常读取。
        if not user32.GetDesktopWindow():
            return None
        CF_UNICODETEXT = 13
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        if not user32.OpenClipboard(None):
            return None
    except Exception:
        return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.c_wchar_p(p).value
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


# ---------------- 抓取 ----------------

class _TextOut(_hp.HTMLParser):
    """只收 p/h1-h3/li/blockquote 的正文文本，躲开导航菜单噪音。"""
    _KEEP = {"p", "h1", "h2", "h3", "li", "blockquote", "figcaption"}
    _SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip_depth = 0
        self._keep_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._KEEP:
            self._keep_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._KEEP and self._keep_depth:
            self._keep_depth -= 1
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth or not self._keep_depth:
            return
        t = data.strip()
        if t:
            self.parts.append(t + " ")


def fetch_title_body(url, timeout=None, max_body=None):
    """抓网页 → (标题, 正文)。失败抛异常。"""
    import requests
    cfg = _cfg()
    timeout = timeout or cfg["timeout"]
    max_body = max_body or cfg["max_body"]
    r = requests.get(url, timeout=timeout, allow_redirects=True, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LuyuanReadLater/1.0",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9"})
    r.raise_for_status()
    if (r.encoding or "").lower() in ("", "iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding or "utf-8"
    raw = r.text
    m = _TITLE_RE.search(raw)
    title = _html.unescape(m.group(1)).strip() if m else ""
    title = re.sub(r"\s+", " ", title)[:120]
    clean = _STRIP_RE.sub("", raw)
    p = _TextOut()
    try:
        p.feed(clean)
    except Exception:
        pass
    body = "\n".join(x.strip() for x in "".join(p.parts).split("\n") if x.strip())
    if len(body) < 100:   # 正文区没抓到东西 → 全页纯文本兜底
        plain = re.sub(r"<[^>]+>", " ", clean)
        plain = _html.unescape(re.sub(r"\s+", " ", plain)).strip()
        body = plain
    return title, body[:max_body]


# ---------------- 存入 ----------------

def _notify_safe(notify, title, nid):
    if not notify:
        return
    try:
        notify(title, nid)
    except Exception as e:
        log.info("notify error: %s", e)


def _find_dup(url):
    for n in store.list_notes(limit=None):
        if n.get("link") == url and "稍后读" in (n.get("tags") or []):
            return n
    return None


def save_from_clipboard(manual=False, notify=None):
    """热键手动 / 剪贴板监视共用入口。返回 note 或 None。"""
    txt = get_clipboard_text()
    url = normalize_url(txt)
    if not url:
        if manual:
            _notify_safe(notify, "剪贴板里没有网址，复制一个链接再按", None)
        return None
    dup = _find_dup(url)
    if dup:
        if manual:
            _notify_safe(notify, "这个网址已经收过稍后读了", dup["id"])
        return dup
    n = store.add_note(url, source="pc",
                       tags=["稍后读"],
                       extra={"link": url, "rl_state": "pending", "rl_retry": 0})
    if n:
        log.info("read later saved: %s", url[:80])
        threading.Thread(target=_fetch_one, args=(n["id"], url, notify),
                         daemon=True).start()
    return n


# ---------------- 选中即存（组合键：默认 Ctrl+Alt+C） ----------------

def _send_ctrl_c():
    """向当前前台窗口发 Ctrl+C，把选中文本拷进剪贴板（ctypes，零新依赖）。

    关键点：本函数由 Ctrl+Alt+C 全局热键触发，触发瞬间用户手指仍按着
    Ctrl + Alt。若直接发 Ctrl+C，OS 实际收到的是 Ctrl+Alt+Ctrl+C，而多数
    程序在 Alt 仍按住时不认 Ctrl+C（不复制）→ 组合键「没反应」。
    因此先合成 Alt / Ctrl 的 key-up 把它们清掉，再发纯Ctrl+C。
    """
    try:
        user32 = ctypes.windll.user32
        VK_MENU = 0x12   # Alt
        # 1) 先松开还按着的 Alt / Ctrl（合成 key-up），避免干扰复制
        user32.keybd_event(VK_MENU, 0, 2, 0)   # Alt up
        user32.keybd_event(0x11, 0, 2, 0)       # Ctrl up
        time.sleep(0.02)
        # 2) 发纯 Ctrl+C 到前台窗口
        user32.keybd_event(0x11, 0, 0, 0)   # Ctrl down
        user32.keybd_event(0x43, 0, 0, 0)   # C down
        user32.keybd_event(0x43, 0, 2, 0)   # C up
        user32.keybd_event(0x11, 0, 2, 0)   # Ctrl up
    except Exception as e:
        log.info("send ctrl+c error: %s", e)


def _save_content(text, notify=None):
    """一段文本存进路远：纯网址→稍后读（抓正文），其它文字→收藏笔记。"""
    text = (text or "").strip()
    if not text:
        _notify_safe(notify, "没有可保存的内容", None)
        return None
    url = normalize_url(text)
    if url:
        dup = _find_dup(url)
        if dup:
            _notify_safe(notify, "这个网址已经收过稍后读了", dup["id"])
            return dup
        n = store.add_note(url, source="pc",
                           tags=["稍后读"],
                           extra={"link": url, "rl_state": "pending", "rl_retry": 0})
        if n:
            log.info("read later saved (select): %s", url[:80])
            threading.Thread(target=_fetch_one, args=(n["id"], url, notify),
                             daemon=True).start()
            _notify_safe(notify, "📖 已收进稍后读：" + url[:50], n["id"])
        return n
    n = store.add_note(text, source="pc", tags=["收藏"])
    if n:
        log.info("snippet saved (select): %d chars", len(text))
        _notify_safe(notify, "✅ 已存进路远：" + text[:40], n["id"])
    return n


def save_selection_to_luyuan(notify=None):
    """选中文字 → 组合键触发 → 自动 Ctrl+C 拷进剪贴板 → 存进路远。

    剪贴板在发键前后都没变（说明没选中内容）→ 提示，不误存旧内容。
    """
    log.info("[诊断] save_selection_to_luyuan 被调用")
    old = get_clipboard_text()
    _send_ctrl_c()
    time.sleep(0.18)
    new = get_clipboard_text()
    if not new or new == old:
        _notify_safe(notify, "先选中要保存的文字，再按组合键", None)
        return None
    return _save_content(new, notify)


# ---------------- 抓取队列 ----------------

def _claim_pending():
    """认领：带「稍后读」标签、待抓/待重试的笔记。返回 [(nid, url)]。"""
    out = []
    now = time.time()
    for n in store.list_notes(limit=None):
        if "稍后读" not in (n.get("tags") or []):
            continue
        st = n.get("rl_state")
        if st in ("done", "failed"):
            continue
        nid = n["id"]
        if st is None:                       # 新笔记（终端/手机分享来的裸网址）
            url = normalize_url(n.get("text", ""))
            if not url:
                continue
            store.set_field(nid, "rl_state", "pending")
            store.set_field(nid, "link", url)
        else:                                # pending：重试路径（含退避）
            if _NEXT_TRY.get(nid, 0) > now:
                continue
            if int(n.get("rl_retry", 0) or 0) >= _cfg()["retries"]:
                store.set_field(nid, "rl_state", "failed")
                continue
            url = n.get("link") or normalize_url(n.get("text", ""))
            if not url:
                continue
        out.append((nid, url))
    return out


def _fetch_one(nid, url, notify=None):
    if _FETCHING.get(nid):
        return
    _FETCHING[nid] = True
    try:
        title, body = fetch_title_body(url)
        text = ((title or url) + "\n" + url + "\n\n" + body).strip()
        store.update_note(nid, text)
        store.set_field(nid, "rl_state", "done")
        store.set_field(nid, "rl_title", title or url)
        _notify_safe(notify, "📖 已收进稍后读：" + (title or url)[:50], nid)
        log.info("fetched %s (%d chars)", url[:60], len(body))
    except Exception as e:
        log.info("fetch failed %s: %s", url[:60], e)
        n = store.get_note(nid)
        retry = int((n or {}).get("rl_retry", 0)) + 1
        store.set_field(nid, "rl_retry", retry)
        if retry >= _cfg()["retries"]:
            store.set_field(nid, "rl_state", "failed")
            _notify_safe(notify, "稍后读抓了 %d 次没抓到，链接还在笔记里" % retry, nid)
        else:
            _NEXT_TRY[nid] = time.time() + retry * 20   # 退避：20s/40s…再试
    finally:
        _FETCHING.pop(nid, None)


def _process_pending(notify=None):
    if _FETCHING:
        return
    for nid, url in _claim_pending():
        threading.Thread(target=_fetch_one, args=(nid, url, notify),
                         daemon=True).start()
        break   # 一轮最多并发一个，温和抓取


def pending_items():
    """稍后读队列（面板/调试用）。"""
    out = {"pending": [], "failed": [], "done": 0}
    for n in store.list_notes(limit=None):
        if "稍后读" not in (n.get("tags") or []):
            continue
        st = n.get("rl_state")
        if st == "pending":
            out["pending"].append({"id": n["id"], "url": n.get("link", ""),
                                   "retry": n.get("rl_retry", 0)})
        elif st == "failed":
            out["failed"].append({"id": n["id"], "url": n.get("link", ""),
                                  "retry": n.get("rl_retry", 0)})
        elif st == "done":
            out["done"] += 1
    return out


def watch_loop(interval=None, notify=None):
    """主循环：剪贴板变 URL 自动收 + 认领待抓队列。由 main 后台线程调用。"""
    if not _cfg()["enabled"]:
        log.info("readlater disabled by config")
        return
    interval = interval or _cfg()["interval"]
    last_cb = None
    log.info("readlater watch loop start (interval=%ss)", interval)
    while True:
        try:
            txt = get_clipboard_text()
            if txt and txt != last_cb:
                last_cb = txt
                if normalize_url(txt):
                    save_from_clipboard(manual=False, notify=notify)
        except Exception as e:
            log.info("clipboard check error: %s", e)
        try:
            _process_pending(notify=notify)
        except Exception as e:
            log.info("readlater pending error: %s", e)
        time.sleep(interval)
