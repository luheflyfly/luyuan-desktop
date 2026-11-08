# -*- coding: utf-8 -*-
"""Windows 原生 Toast（winotify）。独立模块，主程序/后台线程都能用。

- launch：点弹窗正文打开的链接（如 http://127.0.0.1:8777/#n=<id>）
- actions：[(按钮文字, 链接), ...]
- 任何失败静默回退：自绘小窗（需 main 的 notifier，可选传入）→ 托盘气泡跳过。
"""
import logging

log = logging.getLogger("toast")


def native_toast(title, body="", launch="", actions=None, ms=5000, fallback=None):
    """弹原生通知。fallback: callable(title, body, ms) 兜底（如 main 的自绘小窗）。"""
    try:
        from winotify import Notification
        n = Notification(app_id="路远", title=title, msg=body, launch=launch or "")
        for label, url in (actions or []):
            if label and url:
                n.add_actions(label, url)
        n.show()
        return True
    except Exception as e:
        log.info("native toast failed (%s)", e)
        if fallback:
            try:
                fallback(title, body, ms)
            except Exception:
                pass
        return False
