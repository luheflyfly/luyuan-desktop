# -*- coding: utf-8 -*-
"""路远 · 微信自动回复（纯 ctypes / Win32，不依赖任何第三方包）。

Stage 1（零触控语音回消息）：
- 不读屏幕内容、不调视觉模型；只认「当前打开的聊天」或「口述的名字」。
- 发送方式：把回复文本写进剪贴板 → 激活微信窗口 → 粘贴(Ctrl+V) → 回车发送。
- 全程失败兜底：任何一步出错都不抛异常，改为「复制文本到剪贴板 + 返回状态」，
  绝不让路远卡死或发错消息。

安全网：
- 目标解析严格（见 router.parse_wechat）；找不到目标（联系人/窗口）→ 不强发，
  复制文本交用户手动发。
- auto_send=false 时只生成文本不发（配置可切，适合先试手）。
- 发完由调用方回声确认；本模块不负责撤回（微信 PC 撤回无稳定全局快捷键，
  需手动右键，留待 Stage 2 用 UIAutomation 解决）。
"""
import ctypes
import os
import re
import time
import logging

log = logging.getLogger("wechat")
# 🔴 独立日志文件：本模块曾长期不落盘（独立 logger 未挂 handler），故障时查无痕迹。
#   每次发送的每一步都写 data/wechat.log，排障只看它。
log.propagate = False
if not log.handlers:
    try:
        _LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "wechat.log")
        _fh = logging.FileHandler(_LOG_PATH, encoding="utf-8")
        _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(_fh)
        log.setLevel(logging.INFO)
    except Exception:
        log.handlers.clear()
        log.propagate = True

try:
    _u32 = ctypes.WinDLL("user32.dll", use_last_error=True)
    _k32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    _WIN = True
except Exception as e:  # 非 Windows / DLL 缺失 → 降级为只复制文本
    _WIN = False
    log.warning("wechat: Win32 不可用（非 Windows 或 DLL 缺失）：%s", e)


# ---------------- Win32 原型声明（不写 argtypes 在 64 位下会崩） ----------------
if _WIN:
    _u32.EnumWindows.argtypes = [
        ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p),
        ctypes.c_void_p]
    _u32.EnumWindows.restype = ctypes.c_bool
    _u32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    _u32.IsWindowVisible.restype = ctypes.c_int
    _u32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
    _u32.GetWindowTextLengthW.restype = ctypes.c_int
    _u32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    _u32.GetWindowTextW.restype = ctypes.c_int
    _u32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    _u32.GetClassNameW.restype = ctypes.c_int
    _u32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _u32.ShowWindow.restype = ctypes.c_int
    _u32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    _u32.SetForegroundWindow.restype = ctypes.c_int
    _u32.OpenClipboard.argtypes = [ctypes.c_void_p]
    _u32.OpenClipboard.restype = ctypes.c_int
    _u32.CloseClipboard.argtypes = []
    _u32.CloseClipboard.restype = ctypes.c_int
    _u32.EmptyClipboard.argtypes = []
    _u32.EmptyClipboard.restype = ctypes.c_int
    _u32.GetClipboardData.argtypes = [ctypes.c_uint]
    _u32.GetClipboardData.restype = ctypes.c_void_p
    _u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    _u32.SetClipboardData.restype = ctypes.c_void_p
    _u32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    _u32.FindWindowW.restype = ctypes.c_void_p
    _u32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte,
                                 ctypes.c_uint, ctypes.c_void_p]
    _u32.keybd_event.restype = None
    _k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    _k32.GlobalAlloc.restype = ctypes.c_void_p
    _k32.GlobalLock.argtypes = [ctypes.c_void_p]
    _k32.GlobalLock.restype = ctypes.c_void_p
    _k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    _k32.GlobalUnlock.restype = ctypes.c_int

    # —— 前台/焦点判定（2026-09-13 新增：不确认前台就发按键会打到别的窗口）——
    _u32.GetForegroundWindow.argtypes = []
    _u32.GetForegroundWindow.restype = ctypes.c_void_p
    _u32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p,
                                              ctypes.POINTER(ctypes.c_ulong)]
    _u32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    _u32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int]
    _u32.AttachThreadInput.restype = ctypes.c_int
    _u32.BringWindowToTop.argtypes = [ctypes.c_void_p]
    _u32.BringWindowToTop.restype = ctypes.c_int
    _u32.IsIconic.argtypes = [ctypes.c_void_p]
    _u32.IsIconic.restype = ctypes.c_int
    _k32.GetCurrentThreadId.argtypes = []
    _k32.GetCurrentThreadId.restype = ctypes.c_ulong

    _CF_UNICODETEXT = 13
    _GMEM_MOVEABLE = 0x0002


# WeChat PC 主窗口类名：3.x 固定 WeChatMainWndForPC；
# 4.x（Qt 重写版）类名形如 Qt51514QWindowIcon，只能靠窗口标题「微信」识别。
_WECHAT_CLASS = "WeChatMainWndForPC"


# ---------------- 窗口查找 ----------------
def _get_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    _u32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _get_title(hwnd):
    length = _u32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    _u32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _pid_is_wechat(hwnd):
    """窗口所属进程是否微信（title 暂空时的身份确认，pywin32 已在依赖）。"""
    try:
        import win32api
        import win32process
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        exe = (win32api.GetModuleFileNameEx(
            win32api.OpenProcess(0x0410, False, pid), 0) or "").lower()
        return "weixin" in exe or "wechat" in exe
    except Exception:
        return False


def _find_wechat_window(diag=None):
    """查找微信主窗口，返回 hwnd 或 None。

    主路径：按微信 3.x 类名直查（最快）。
    兜底：枚举顶层窗口打分择优——标题精确「微信/Weixin」最可信，
    其次 Qt 类名 + 标题含微信（微信 4.x 的 Qt 窗口无固定类名）。

    🔴 2026-09-13 修：**不再要求窗口必须可见**。微信 4.x 点关闭会收进托盘，
    此时窗口 still exists 但 `IsWindowVisible=0`，旧逻辑直接跳过 → 回执
    「没检测到微信窗口」而用户明明开着微信（用户实测踩到）。现在隐藏窗口也算
    候选（只降一档分），由 `activate()` 负责 ShowWindow 唤出来。
    diag: 传一个 list 进来可拿到诊断信息（排查「找不到窗口」用）。
    """
    if not _WIN:
        return None
    try:
        hwnd = _u32.FindWindowW(_WECHAT_CLASS, None)
        if hwnd:
            if diag is not None:
                diag.append("FindWindowW(%s) 直查命中 %s" % (_WECHAT_CLASS, hex(hwnd)))
            return hwnd
    except Exception as e:
        log.info("wechat FindWindow failed: %s", e)

    best = [None, 0, False]          # hwnd, score, visible
    seen = []                        # 诊断：所有看起来像微信的候选
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p,
                                         ctypes.c_void_p)

    def _enum(hwnd, _lp):
        try:
            cls = _get_class(hwnd)
            title = _get_title(hwnd)
            if cls == _WECHAT_CLASS:
                score = 100
            elif title.strip() in ("微信", "Weixin"):
                score = 90
            elif "微信" in title and cls.startswith("Qt"):
                score = 70
            elif cls.startswith("Qt") and not title.strip() and _pid_is_wechat(hwnd):
                # 09-15 凌晨实测：微信最小化瞬间 Qt 窗口标题可能暂空 →
                # 旧打分全部不命中 → 「没找到微信窗口」。进程名确认后仍算高分候选。
                score = 80
            else:
                return True
            vis = bool(_u32.IsWindowVisible(hwnd))
            if not vis:
                score -= 15          # 托盘隐藏态：仍是候选，但让可见的优先
            seen.append("%s cls=%s vis=%s title=%r score=%d"
                        % (hex(hwnd), cls, vis, title, score))
            if score > best[1]:
                best[0], best[1], best[2] = hwnd, score, vis
        except Exception:
            pass
        return True

    try:
        _u32.EnumWindows(EnumWindowsProc(_enum), 0)
    except Exception as e:
        log.warning("wechat enum windows failed: %s", e)
    if diag is not None:
        diag.append("枚举到 %d 个微信候选：%s" % (len(seen), " | ".join(seen) or "（无）"))
    if best[0]:
        log.info("wechat window: %s visible=%s score=%d",
                 hex(best[0]), best[2], best[1])
    else:
        log.info("wechat window not found（枚举到 %d 个候选）", len(seen))
    return best[0]


def get_foreground():
    """当前前台窗口 hwnd（失败返回 None）。"""
    try:
        return _u32.GetForegroundWindow()
    except Exception:
        return None


def foreground_is(hwnd):
    """前台窗口是否就是 hwnd。"""
    if not hwnd:
        return False
    try:
        return _u32.GetForegroundWindow() == hwnd
    except Exception:
        return False


def foreground_ready(hwnd):
    """窗口可接收按键的完整条件：在前台 + 非最小化 + 可见。
    🔴 只查 foreground 不够：最小化窗口照样是 foreground（09-14 实测）。"""
    if not hwnd:
        return False
    try:
        if _u32.GetForegroundWindow() != hwnd:
            return False
        if _u32.IsIconic(hwnd) or not _u32.IsWindowVisible(hwnd):
            return False
        return True
    except Exception:
        return False


def activate(hwnd, timeout=2.0):
    """把微信真正切到前台并**确认成功**，返回 bool。

    为什么必须确认：Windows 有「前台锁」——后台进程调 SetForegroundWindow 常被
    静默拒绝（返回 0，不报错）。若不确认就发按键，Ctrl+V/回车会打到当时的别的窗口
    （2026-09-13 实测：微信 4.x 在后台，按键落到了 WorkBuddy 上，消息压根没发出，
    模块却回了 sent=true）。
    三重手段：ALT 敲击解前台锁 → TOPMOST 强制激活 → AttachThreadInput（仅最后备选）→ 轮询确认。

    🔴 09-14 实测补丁：**最小化的窗口也可以是 foreground**（GetForegroundWindow
    照样返回它）——旧代码开头 foreground_is 就 return True，restore 逻辑根本走不到，
    后续 Ctrl+V 全发给最小化窗口，「粘贴成功」其实啥都没发生。所以唤出（restore/
    show）必须在 foreground 判定**之前**，且最终确认要加 IsIconic 复查。
    """
    if not hwnd:
        return False
    _release_modifiers()   # 先清场：任何卡住的 Ctrl/Alt 都会毁掉后续按键
    # ⓪ 先唤出（不可见/最小化 → restore），再做前台判定
    try:
        if not _u32.IsWindowVisible(hwnd):
            _u32.ShowWindow(hwnd, 5)   # SW_SHOW：把托盘里的微信唤回桌面
            time.sleep(0.35)
        if _u32.IsIconic(hwnd):
            _u32.ShowWindow(hwnd, 9)   # SW_RESTORE
            time.sleep(0.3)
    except Exception as e:
        log.info("wechat show(hidden) err: %s", e)
    # ① 敲一下 ALT：Windows 视「最近有输入事件」的进程可抢占前台
    try:
        _key_down(0x12)
        _key_up(0x12)
    except Exception:
        _release_modifiers()
    # ③ TOPMOST 大法（首选手段，2026-09-13）：调用进程往往从无输入权（如 server
    #   进程代发速记窗消息），ALT 绕不开前台锁。SetWindowPos 带 HWND_TOPMOST 直接
    #   改 z-order 并激活窗口 —— 不吃前台锁。置顶 → 确认前台 → NOTOPMOST 还原。
    try:
        _u32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)  # TOPMOST, NOMOVE|NOSIZE|SHOWWINDOW
        time.sleep(0.15)
        _u32.SetForegroundWindow(hwnd)
        time.sleep(0.12)
        _u32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002)          # NOTOPMOST 还原（finally 语义，尽早）
    except Exception as e:
        log.info("wechat activate topmost err: %s", e)
        _release_modifiers()
    if foreground_ready(hwnd):
        time.sleep(0.15)   # 等前台渲染稳定，按键才不吃掉
        return True
    # ④ AttachThreadInput（🔴 最后备选，2026-09-13 降级）：把自己/前台线程与目标
    #   线程的输入队列挂在一起绕过前台锁。⚠️ 调用线程若无消息泵（server/控制台
    #   进程），跨队列同步可能令目标 UI 冻结——这就是它被降为最后手段的原因。
    attached = []
    tid_target = 0
    try:
        tid_target = _u32.GetWindowThreadProcessId(hwnd, None)
        fg = _u32.GetForegroundWindow()
        tid_fg = _u32.GetWindowThreadProcessId(fg, None) if fg else 0
        tid_me = _k32.GetCurrentThreadId()
        for t in (tid_fg, tid_me):
            if t and t != tid_target and t not in attached:
                if _u32.AttachThreadInput(t, tid_target, 1):
                    attached.append(t)
        _u32.BringWindowToTop(hwnd)
        _u32.SetForegroundWindow(hwnd)
    except Exception as e:
        log.info("wechat activate err: %s", e)
    finally:
        for t in attached:
            try:
                _u32.AttachThreadInput(t, tid_target, 0)
            except Exception:
                pass
    # ⑤ 轮询确认（最长 timeout 秒）
    deadline = time.time() + max(0.3, timeout)
    while time.time() < deadline:
        if foreground_ready(hwnd):
            time.sleep(0.15)   # 等前台渲染稳定，按键才不吃掉
            return True
        time.sleep(0.1)
    return foreground_ready(hwnd)


def find_wechat():
    """对外：微信是否在运行（返回 hwnd 或 None）。"""
    return _find_wechat_window()


# ---------------- 剪贴板（写文本 / 读文本） ----------------
def _get_clipboard_text():
    if not _WIN:
        return None
    try:
        if not _u32.OpenClipboard(0):
            return None
        h = _u32.GetClipboardData(_CF_UNICODETEXT)
        if not h:
            _u32.CloseClipboard()
            return None
        p = _k32.GlobalLock(h)
        if not p:
            _u32.CloseClipboard()
            return None
        text = ctypes.c_wchar_p(p).value or ""
        _k32.GlobalUnlock(h)
        _u32.CloseClipboard()
        return text
    except Exception:
        try:
            _u32.CloseClipboard()
        except Exception:
            pass
        return None


def _set_clipboard_text(text, retries=8):
    """写文本到剪贴板。

    🔴 2026-09-13 截图铁证：OpenClipboard 被其他进程占用（微信自己也频繁访问剪贴板）
    时返回 False，旧代码**不重试、调用方也不检查** → Ctrl+V 粘出用户剪贴板里的旧整句，
    进了微信搜索框（搜出一堆小说，用户截图为证）。OpenClipboard 冲突是瞬态的，重试必成。
    """
    if not _WIN:
        return False
    for _attempt in range(retries):
        try:
            if _u32.OpenClipboard(0):
                try:
                    _u32.EmptyClipboard()
                    buf = (ctypes.c_wchar * (len(text) + 1))()
                    for i, ch in enumerate(text):
                        buf[i] = ch
                    buf[len(text)] = "\0"
                    h = _k32.GlobalAlloc(_GMEM_MOVEABLE, (len(text) + 1) * 2)
                    if not h:
                        continue
                    p = _k32.GlobalLock(h)
                    ctypes.memmove(p, ctypes.byref(buf), (len(text) + 1) * 2)
                    _k32.GlobalUnlock(h)
                    _u32.SetClipboardData(_CF_UNICODETEXT, h)
                    return True
                finally:
                    _u32.CloseClipboard()
        except Exception as e:
            log.warning("wechat set clipboard failed: %s", e)
            try:
                _u32.CloseClipboard()
            except Exception:
                pass
        time.sleep(0.06)
    return False


def _paste_text(text):
    """写剪贴板（重试 + 读回校验）→ Ctrl+V。返回 False = 剪贴板不可用，
    调用方必须放弃按键——宁可不发，也不能把错误内容粘出去（截图事故的教训）。"""
    if not _set_clipboard_text(text):
        log.warning("paste: clipboard write FAILED after retries, abort keys")
        return False
    got = _get_clipboard_text()
    if got != text:
        log.warning("paste: clipboard verify mismatch (got=%r), rewrite once", (got or "")[:30])
        if not _set_clipboard_text(text):
            return False
    _ctrl_v()
    time.sleep(0.25)
    return True


def _ctrl_a():
    try:
        _key_down(0x11)
        _press(0x41)      # A
    finally:
        _key_up(0x11)


# ---------------- 键盘模拟 ----------------
_MODIFIERS = (0x11, 0x12, 0x10, 0x5B)   # Ctrl Alt Shift Win


def _release_modifiers():
    """无条件松开所有修饰键。卡键 = 全系统假死（2026-09-13 实录：微信『被卡死』
    实为 Ctrl 卡在按下态），任何发送/激活流程的 except 里都必须调它兜底。"""
    for vk in _MODIFIERS:
        try:
            _u32.keybd_event(vk, 0, 2, 0)   # KEYEVENTF_KEYUP
        except Exception:
            pass


def _key_down(vk):
    _u32.keybd_event(vk, 0, 0, 0)


def _key_up(vk):
    _u32.keybd_event(vk, 0, 2, 0)


def _press(vk):
    _key_down(vk)
    _key_up(vk)


def _ctrl_v():
    try:
        _key_down(0x11)   # Ctrl
        _press(0x56)      # V
    finally:
        _key_up(0x11)


def _ctrl_f():
    try:
        _key_down(0x11)
        _press(0x46)      # F
    finally:
        _key_up(0x11)


def _enter():
    _press(0x0D)


def _focus_wechat(hwnd):
    """兼容旧调用：切前台并确认（失败返回 False）。"""
    return activate(hwnd)


def _paste_and_send():
    """假设微信消息输入框已聚焦：粘贴 + 回车。

    🔴 时序教训（2026-09-13）：Ctrl+V 后只等 0.08s 就回车，微信 Qt 界面刚被抢前台
    时内部焦点尚未交给输入框 → 粘贴落空、回车无效 → 「聊天窗开了但消息没发」。
    现等 0.25s 再回车。"""
    _ctrl_v()
    time.sleep(0.25)
    _enter()
    return True


# ---------------- 对外主接口 ----------------
def _to_label(to):
    return "当前聊天" if to in ("current", "last") else to


# ---------------- 搜索定位（send_reply / locate_and_fill 共用） ----------------
def _ctrl_c():
    try:
        _key_down(0x11)
        _press(0x43)      # C
    finally:
        _key_up(0x11)


def _verify_text_on_screen(text, hwnd):
    """A10 落位终检包装。安全模式（locate）下 OCR 不可用时放行（用户肉眼可见）；
    探针为空（纯 emoji 正文）时 wechat_ocr 侧已返回 True。"""
    try:
        import wechat_ocr
        return wechat_ocr.verify_text_on_screen(text, hwnd)
    except Exception as e:
        log.info("verify text on screen err: %s", e)
        return True, "落位验证模块出错（跳过）"


def _wait_foreground(hwnd, timeout=2.5):
    """enter 后焦点交接轮询：微信恢复/搜索动画期间 foreground 会短暂漂移，
    一次判定失败太急（09-14 23:01 路河在电脑前操作时三连败实录）。
    最多等 timeout 秒，期间每 0.25s 复查一次。"""
    deadline = time.time() + timeout
    while True:
        if foreground_ready(hwnd):
            time.sleep(0.15)
            return True
        if time.time() >= deadline:
            return False
        time.sleep(0.25)


def _verify_chat(to, hwnd):
    """A10 读屏验证：OCR 确认当前聊天对象就是 to。fail-closed，出错一律 False。"""
    try:
        import wechat_ocr
        ok, detail = wechat_ocr.verify_chat_name(to, hwnd)
        log.info("verify chat %r -> %s (%s)", to, ok, detail)
        return ok, detail
    except Exception as e:
        log.info("verify chat err: %s", e)
        return False, "读屏验证出错"


def _search_fill_name(name, hwnd=None):
    """微信已在前台的前提下：Ctrl+F → 清残留 → 粘名字 → 读回校验 → 等结果渲染。

    不按回车（开聊天/发正文由调用方决定）。校验失败抛 RuntimeError。

    🔴 2026-09-13 23:08 用户实录：粘名字后 0.30s 就回车，微信搜索结果还没渲染，
    回车落进「搜索小程序」入口 → 定位失败。0.30s → 1.20s（本地索引通常 <500ms，
    但 Qt 冷启动 + 焦点交接要吃掉大半）。名字有同音字错别字时搜索为空同样会跳
    小程序——同音字已由 router._resolve_wechat_name 兜住。

    🔴 09-14 增：键盘冻结实时检测。微信 4.x 偶发拒绝一切注入键盘（09-14 凌晨实录），
    此时剪贴板读回照样通过（剪贴板是独立系统设施），但字根本没进搜索框 → 后续
    每步全废却「看似成功」。传 hwnd 则粘贴后 OCR 搜索框：读得到内容却没有名字
    → 立刻报错降级（正文走剪贴板兜底），不演后续戏。OCR 读不到内容时不拦
    （兼容读不出的主题/字体，回退旧逻辑）。
    """
    _ctrl_f()
    time.sleep(0.45)          # 搜索框弹出的焦点交接
    _ctrl_a()                 # 清搜索框残留（上次搜索词/兜底复制的整句）
    _press(0x2E)              # Delete
    time.sleep(0.12)
    if not _paste_text(name):
        raise RuntimeError("剪贴板被占用，收件人写入失败")
    time.sleep(0.25)
    # 🔴 读回校验：Ctrl+A 全选搜索框 → Ctrl+C → 读剪贴板比对。
    #   防粘贴落在别的窗口（22:55 班级群事故：Ctrl+F 失效，名字粘进了聊天输入框）。
    _ctrl_a()
    _ctrl_c()
    time.sleep(0.15)
    got = (_get_clipboard_text() or "").strip()
    if got != name:
        raise RuntimeError("搜索框内容校验失败：期望「%s」实得「%s」" % (name, got[:30]))
    if hwnd:
        try:
            import wechat_ocr
            img = wechat_ocr._grab_window(hwnd)
            texts = wechat_ocr._ocr_texts(img) if img else None
            if texts:
                joined = re.sub(r"\s+", "", "".join(t[0] for t in texts))
                # 模糊判断：OCR 读名字偶尔错一字（「路河」→「路何」partial=50），
                # 阈值 50 容忍单字误差；漏报由 verify_text_on_screen 终检兜底。
                similar = False
                try:
                    from rapidfuzz import fuzz
                    similar = fuzz.partial_ratio(name, joined) >= 50
                except Exception:
                    similar = name in joined
                if (joined and not similar
                        and ("搜索" in joined or "搜素" in joined)):
                    raise RuntimeError(
                        "微信没响应键盘（疑似输入冻结）：搜索框里没有「%s」" % name[:12])
        except RuntimeError:
            raise
        except Exception as e:
            log.info("search box ocr check skipped: %s", e)
    time.sleep(1.20)          # 🔴 等搜索结果渲染完再让调用方回车


def locate_and_fill(to, text):
    """安全模式：定位到 to 的聊天窗口，把正文填进输入框——**绝不按回车**。

    🔴 2026-09-13 22:55 事故：Ctrl+F 偶发失效（微信焦点异常时），后续全部按键
    落进当前聊天输入框 → 「路平坦成河」「我要睡了」连发进班级群（真实班级群社死）。
    根治：路远永远不碰最后的回车。即使定位失败、粘贴落错窗口，没有回车就不会发出，
    用户看得见、可删除。UIA 实测微信 4.x 只暴露 2 个空 Pane，无法读当前聊天名做
    自动验证 → OCR 验证列为后续任务（见 派发单）。

    返回 dict 同 send_reply 结构（sent 恒为 False）。
    """
    diag = []
    hwnd = _find_wechat_window(diag=diag)
    if not hwnd:
        copied = _set_clipboard_text(text)
        log.info("locate: window NOT found. %s", " / ".join(diag))
        return {"ok": False, "sent": False, "copied": copied, "verified": False,
                "label": "没找到微信窗口，已复制到剪贴板，手动粘贴发送。", "to": to}

    saved = _get_clipboard_text()

    if not activate(hwnd):
        copied = _set_clipboard_text(text)
        log.info("locate: activate FAILED (window=%s)", hwnd)
        return {"ok": False, "sent": False, "copied": copied, "verified": False,
                "label": "没能把微信切到前台，已复制到剪贴板，手动粘贴发送。", "to": to}
    time.sleep(0.35)

    try:
        if to in ("current", "last"):
            if not foreground_ready(hwnd):
                raise RuntimeError("焦点被抢走或微信最小化")
            if not _paste_text(text):
                raise RuntimeError("剪贴板被占用，正文写入失败")
            where = "当前聊天"
        else:
            # 搜索定位带一次自愈重试（09-14 午实测：零结果回车会开「搜一搜」面板
            # 并残留，之后每次定位都被它干扰失败 → 失败时 Esc 收浮层，再试一轮）
            last_err = None
            for attempt in (1, 2):
                try:
                    log.info("locate: ctrl+f (attempt %s) ...", attempt)
                    _search_fill_name(to, hwnd=hwnd)
                    _enter()
                    time.sleep(1.10)     # Qt 打开聊天后内部焦点交接需要时间
                    if not _wait_foreground(hwnd):
                        raise RuntimeError("搜索后焦点被抢走或微信最小化")
                    # A10 读屏验证：亲眼读到「当前聊天=to」才填正文。读到别的/读不到
                    # → 宁可不填（正文留剪贴板），绝不往不确定的位置粘东西（23:19 事故）。
                    ok, detail = _verify_chat(to, hwnd)
                    if not ok:
                        raise RuntimeError(detail)
                    log.info("locate: chat opened, fill body (NO enter) ...")
                    if not _paste_text(text):
                        raise RuntimeError("剪贴板被占用，正文写入失败")
                    # 正文落位终检：冻结场景下粘贴静默失败，OCR 确认真的上屏了
                    time.sleep(0.6)
                    _ok_fill, _det = _verify_text_on_screen(text, hwnd)
                    if not _ok_fill:
                        raise RuntimeError(_det)
                    where = to
                    last_err = None
                    break
                except RuntimeError as e:
                    last_err = e
                    _release_modifiers()
                    if attempt == 1:
                        log.info("locate attempt1 failed (%s), Esc + retry", e)
                        _press(0x1B)          # 收掉可能开着的搜索浮层/搜一搜面板
                        time.sleep(0.6)
            if last_err:
                raise last_err
        if saved:
            try:
                _set_clipboard_text(saved)
            except Exception:
                pass
        log.info("locate: filled for %s, waiting for manual enter", where)
        return {"ok": True, "sent": False, "copied": False, "verified": False,
                "label": "已定位到「%s」的聊天并把正文填进输入框（未发送）。"
                         "请确认聊天对象没错后自己按回车；若内容落在错误的聊天里，删掉即可。"
                         % _to_label(where), "to": to}
    except Exception as e:
        log.warning("locate_and_fill error: %s", e)
        _release_modifiers()
        copied = _set_clipboard_text(text)
        return {"ok": False, "sent": False, "copied": copied, "verified": False,
                "label": "定位出错（%s），已复制到剪贴板，手动粘贴发送。" % str(e)[:40],
                "to": to}


def send_reply(to, text, cfg=None, dry_run=False):
    """发送一条微信回复。

    to:
      - "current" / "last" → 发给当前打开的聊天
      - 其它字符串 → 当作联系人名，Ctrl+F 搜名字开聊天再发
    text: 回复正文
    返回 dict: {ok, sent, copied, verified, label, to}
    verified=True 仅当「当前聊天」模式（前台已确认、目标就是用户当下开的聊天）；
    按名字搜时无法回执（微信 4.x 为 Qt 自绘，无 Win32 控件可读），故 verified=False。
    """
    cfg = cfg or {}
    text = (text or "").strip()
    if not text:
        return {"ok": False, "sent": False, "copied": False, "verified": False,
                "label": "回复内容为空，没发。", "to": to}
    tail = (text[:60] + "…") if len(text) > 60 else text

    # 草稿模式：不真正操作微信，仅验证解析 + 剪贴板流程（自检用）
    if dry_run:
        return {"ok": True, "sent": False, "verified": False,
                "copied": bool(_set_clipboard_text(text)),
                "label": "[草稿] 将回复%s：%s" % (_to_label(to), tail), "to": to}

    # 配置：要求确认（不自动发）→ 安全模式：定位聊天+填好正文，回车由用户按
    # 🔴 2026-09-13 22:55 班级群事故后，auto_send=false 的行为从「只复制」升级为此
    # 2026-09-18 检查批：缺 key 时默认收紧为 False（配置损坏也绝不自动发）
    if not cfg.get("auto_send", False):
        return locate_and_fill(to, text)

    if not _WIN:
        copied = _set_clipboard_text(text)
        return {"ok": False, "sent": False, "copied": copied, "verified": False,
                "label": "当前系统不支持自动发微信（非 Windows），已复制到剪贴板。",
                "to": to}

    diag = []
    hwnd = _find_wechat_window(diag=diag)
    if not hwnd:
        copied = _set_clipboard_text(text)
        # 日志留全诊（排查「找不到窗口」必看这条）：FindWindow 结果 + 枚举候选清单
        log.info("wechat send: window NOT found. %s", " / ".join(diag))
        return {"ok": False, "sent": False, "copied": copied, "verified": False,
                "label": "没找到微信窗口（微信没登录，或它在别的桌面/会话？），"
                         "已复制到剪贴板，手动粘贴发送。", "to": to}

    saved = _get_clipboard_text()   # 发完尽量恢复用户原剪贴板

    # ★ 关键闸门：必须确认微信真的在前台。否则按键会落在别的窗口上
    #   （历史 bug：不确认就发 → 消息没出去，却回 sent=true）
    if not activate(hwnd):
        copied = _set_clipboard_text(text)
        log.info("send: activate FAILED (window=%s)", hwnd)
        return {"ok": False, "sent": False, "copied": copied, "verified": False,
                "label": "没能把微信切到前台（可能被系统前台锁拦住），已复制到剪贴板，"
                         "手动粘贴发送。", "to": to}
    time.sleep(0.35)   # 🔴 微信刚被抢前台，给它消化 activate event 的时间，否则后续按键落空

    try:
        if to in ("current", "last"):
            # 当前聊天：输入框默认聚焦，粘贴 + 回车
            if not foreground_ready(hwnd):
                raise RuntimeError("发送前焦点被抢走或微信最小化")
            if not _paste_text(text):
                raise RuntimeError("剪贴板被占用，正文写入失败")
            _enter()
            log.info("send: current-chat paste+enter done")
            verified = True          # 前台已确认、目标是用户当下打开的聊天
            label = "已发给当前聊天：%s" % tail
        else:
            # 按名字搜：定位+读回校验统一走 _search_fill_name → 回车开聊天 → 粘正文 → 回车发
            # 🔴 每步落日志（data/wechat.log）——2026-09-13 两次「窗口开了没发出去」查无痕迹的教训
            log.info("send: activate ok, ctrl+f ...")
            _search_fill_name(to, hwnd=hwnd)
            _enter()                 # 打开搜索结果首条聊天
            time.sleep(1.10)         # 🔴 Qt 打开聊天后内部焦点交接需要时间
            if not _wait_foreground(hwnd):
                raise RuntimeError("搜索后焦点被抢走或微信最小化")
            # A10 读屏验证：自动发送的最后闸门。读不到目标名 = 绝不回车。
            ok, detail = _verify_chat(to, hwnd)
            if not ok:
                raise RuntimeError("发送拦截：%s" % detail)
            log.info("send: chat opened, paste body ...")
            if not _paste_text(text):
                raise RuntimeError("剪贴板被占用，正文写入失败")
            _enter()
            log.info("send: paste+enter done")
            # 微信 4.x 是 Qt 自绘界面，无 Win32 控件可读，无法回执「聊天是否真的匹配到」
            verified = False
            label = "已尝试发给%s：%s（微信未回执，请瞄一眼确认）" % (to, tail)

        if saved:
            try:
                _set_clipboard_text(saved)
            except Exception:
                pass
        return {"ok": True, "sent": True, "verified": verified, "copied": False,
                "label": label, "to": to}
    except Exception as e:
        log.warning("wechat send_reply error: %s", e)
        _release_modifiers()   # 🔴 卡键 = 全系统假死，异常路径必须松键
        copied = _set_clipboard_text(text)
        return {"ok": False, "sent": False, "copied": copied, "verified": False,
                "label": "发送出错（%s），已复制到剪贴板，手动发。" % str(e)[:40],
                "to": to}


def recall_last():
    """尝试撤回上一条已发消息（best-effort）。

    微信 PC 端撤回没有稳定全局快捷键（需右键菜单），纯 Win32 无法可靠触发，
    故本函数仅把微信窗口提到前台并提示手动撤回。Stage 2 用 UIAutomation 再做真正撤回。
    """
    if not _WIN:
        return {"ok": False, "label": "当前系统不支持。"}
    hwnd = _find_wechat_window()
    if not hwnd:
        return {"ok": False, "label": "没检测到微信窗口。"}
    _focus_wechat(hwnd)
    return {"ok": False,
            "label": "微信 PC 撤回需手动右键（2 分钟内），暂不支持自动撤回。"}
