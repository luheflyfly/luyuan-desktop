"""线程安全的"触发捕获"桥：连接 Web 面板(FastAPI) 与桌面捕获逻辑(main)。"""
import time
import threading

_handler = None
_lock = threading.Lock()
_last_status = {"state": "idle", "text": "", "ts": 0.0, "error": ""}
_stop_event = threading.Event()


def set_capture_handler(fn):
    with _lock:
        global _handler
        _handler = fn


def request_capture():
    """请求一次语音捕获。返回是否成功派发（未设置处理器则失败）。"""
    with _lock:
        if _handler:
            threading.Thread(target=_handler, daemon=True).start()
            return True
    return False


def set_status(state, text="", error=""):
    with _lock:
        _last_status["state"] = state
        _last_status["text"] = text
        _last_status["error"] = error
        _last_status["ts"] = time.time()


def get_status():
    with _lock:
        return dict(_last_status)


def is_busy():
    """捕获流水线是否正在占用麦克风（聆听/识别中）。"""
    with _lock:
        return _last_status["state"] not in ("idle",)


def clear_stop():
    """新一轮录音前清空停止信号。"""
    _stop_event.clear()


def request_stop():
    """请求正在进行的录音停止（手动结束）。"""
    _stop_event.set()


def stop_requested():
    return _stop_event.is_set()


def get_stop_event():
    """录音函数需要轮询的停止事件。"""
    return _stop_event


# ---------------- 唤醒词冷却期 ----------------
# 一次捕获（录音 / 识别）结束后，给唤醒词监听一段"静默期"，
# 避免用户刚说的话里含唤醒词而被立刻再次触发（表现为"录完又来 / 停不掉"）。
_ww_cooldown_until = 0.0


def set_ww_cooldown(seconds):
    """设置唤醒词在接下来 seconds 秒内不自动触发。"""
    global _ww_cooldown_until
    _ww_cooldown_until = time.time() + float(seconds)


def ww_in_cooldown():
    """当前是否处于唤醒词静默期。"""
    return time.time() < _ww_cooldown_until


def request_capture_safe():
    """触发一次捕获，但若流水线正忙则忽略（防止重复堆叠）。"""
    if is_busy():
        return False
    return request_capture()
