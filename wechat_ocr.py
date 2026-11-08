# -*- coding: utf-8 -*-
"""微信读屏验证（派发单 A10）：发送前 OCR 确认「当前聊天是谁」。

为什么必须有这一步（2026-09-13 22:55 班级群事故的根治）：
  微信 4.x 是 Qt 自绘，UIA 树读不到任何内部元素；窗口标题恒为「微信」。
  搜索定位失败/零结果时，后续按键落点不可知 → 只有「亲眼读到」聊天名才能发。
  本模块读到目标名 → 放行；读不到 / 读到别的 / 引擎全挂 → 拒绝（fail-closed）。

最终判定规则（09-14 夜三轮实测迭代出的形态）：
  - 只 OCR 窗口顶部 25% 窄条；坐标绝对值不可信（RapidOCR 内部缩放），只用
    「第一行聚类」（y 最小值 + 1.5×平均块高以内 = 同一行）和「聊天名 = 第一行
    里 x 最靠右的块」（搜索框恒在聊天名左侧——这个相对关系锁死了搜索词误当
    聊天名的通道）
  - 匹配 = 标题块文本与目标名精确相等或包含（不用 fuzzy：2 字名 fuzz 阈值
    危险，OCR 错字宁可误拒也不误放，fail-closed 方向）
引擎：
  ① RapidOCR（onnxruntime，离线，~2.2s/张）主引擎
  ② qwen3.5:4b VL（Ollama，热调用 ~2.5s）兜底——①读不到任何文本时才用
  附：verify_text_on_screen() 是粘贴落位终检（防「假成功」），与聊天名验证互补。
"""
import io
import os
import re
import time
import base64
import logging

log = logging.getLogger("wechat")

# 🔴 进程级 DPI-aware：不做这个，DPI 缩放机器上 GetDC(0) 拿到的是系统缩过的模糊画面，
#   RapidOCR 对模糊小字直接失明（09-14 夜实测：读不出聊天名，全靠 VL 兜底 19s）。
#   声明后 GetWindowRect/BitBlt 全走物理像素，文字原生清晰。wechat.py 全程纯键盘
#   操作不依赖坐标，此声明对它无副作用。
try:
    import ctypes as _ct
    _ct.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_AWARE
except Exception:
    try:
        _ct.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

_TITLE_BAND = 0.25      # 只 OCR 窗口顶部 25% 窄条（第一行=搜索框+聊天名所在行）
_ENGINE = {"ocr": None}  # RapidOCR 懒加载单例（首次 ~2.6s，之后常驻）
_ENGINE_LOCK = None      # 懒加载互斥锁（server 多线程下防双初始化）


def _get_ocr():
    """RapidOCR 单例获取（带锁；锁也懒加载，避免模块导入期建线程锁的兼容问题）。"""
    global _ENGINE_LOCK
    import threading
    if _ENGINE_LOCK is None:
        _ENGINE_LOCK = threading.Lock()
    if _ENGINE["ocr"] is not None:
        return _ENGINE["ocr"]
    with _ENGINE_LOCK:
        if _ENGINE["ocr"] is None:
            from rapidocr_onnxruntime import RapidOCR
            _ENGINE["ocr"] = RapidOCR()
    return _ENGINE["ocr"]


def _grab_window(hwnd):
    """截微信窗口，返回 PIL.Image 或 None。

    🔴 必须用屏幕 DC 裁剪（GetDC(0)+BitBlt），不能用 PrintWindow：实测微信 4.x
    （Qt 合成窗口）PrintWindow+PW_RENDERFULLCONTENT 频繁抓到**旧帧**——输入框明明
    已有正文、搜索框明明已清空，截出来却是几秒前的画面（09-14 夜实测，OCR 验证会
    被旧帧骗过）。屏幕 DC 是所 present 即所得。代价：窗口必须在前台且未被遮挡——
    调用方（send/locate 流程）刚 activate 完，微信恰好在前台，条件天然成立。
    """
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        gdi = ctypes.windll.gdi32
        r = wintypes.RECT()
        if not u32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        w, hh = r.right - r.left, r.bottom - r.top
        if w <= 20 or hh <= 20:
            return None
        sdc = u32.GetDC(0)
        cdc = gdi.CreateCompatibleDC(sdc)
        bmp = gdi.CreateCompatibleBitmap(sdc, w, hh)
        gdi.SelectObject(cdc, bmp)
        # SRCCOPY|CAPTUREBLT：含分层窗口
        ok = gdi.BitBlt(cdc, 0, 0, w, hh, sdc, r.left, r.top, 0x00CC0020 | 0x40000000)

        class BMIHEADER(ctypes.Structure):
            _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                        ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                        ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                        ("biSizeImage", ctypes.c_uint32), ("biX", ctypes.c_int32),
                        ("biY", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                        ("biClrImportant", ctypes.c_uint32)]

        bmi = BMIHEADER()
        bmi.biSize = ctypes.sizeof(BMIHEADER)
        bmi.biWidth, bmi.biHeight = w, -hh
        bmi.biPlanes, bmi.biBitCount = 1, 32
        buf = ctypes.create_string_buffer(w * hh * 4)
        gdi.GetDIBits(cdc, bmp, 0, hh, buf, ctypes.byref(bmi), 0)
        from PIL import Image
        img = Image.frombuffer("RGB", (w, hh), bytes(buf), "raw", "BGRX", 0, 1)
        gdi.DeleteObject(bmp)
        gdi.DeleteDC(cdc)
        u32.ReleaseDC(0, sdc)
        return img if ok else None
    except Exception as e:
        log.info("wechat_ocr grab err: %s", e)
        return None


def ocr_image_path(path):
    """图片文件路径 → 纯文本（识别行按 y 聚行、行内按 x 排序）。
    空串 = 没字/引擎不可用。vc102 拍作业 OCR 闭环（transwatch 调）与 _ocr_texts 共享引擎单例。"""
    try:
        eng = _get_ocr()
    except Exception as e:
        log.info("rapidocr init err: %s", e)
        return ""
    try:
        res, _elapse = eng(path)
    except Exception as e:
        log.info("rapidocr infer err: %s", e)
        return ""
    items = []
    for box, text, _conf in (res or []):
        x = (box[0][0] + box[2][0]) / 2.0
        y = (box[0][1] + box[2][1]) / 2.0
        h = abs(box[3][1] - box[0][1]) or 1.0
        items.append((text, x, y, h))
    items.sort(key=lambda it: it[2])
    lines = []
    cur, cur_y, cur_h = [], None, None
    for it in items:
        if cur_y is None or abs(it[2] - cur_y) <= max(cur_h, it[3]) * 0.6:
            cur.append(it)
            cur_y = it[2] if cur_y is None else (cur_y + it[2]) / 2.0
            cur_h = max(cur_h or it[3], it[3])
        else:
            cur.sort(key=lambda t: t[1])
            lines.append("".join(t[0] for t in cur))
            cur, cur_y, cur_h = [it], it[2], it[3]
    if cur:
        cur.sort(key=lambda t: t[1])
        lines.append("".join(t[0] for t in cur))
    return "\n".join(lines).strip()


def _ocr_texts(img):
    """RapidOCR 全图识别。返回 [(text, x_center, y_center, block_h)] 或 None（引擎不可用）。"""
    try:
        eng = _get_ocr()
    except Exception as e:
        log.info("rapidocr init err: %s", e)
        return None
    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "data", "_wechat_ocr_frame.png")
    try:
        img.save(tmp)
        res, _elapse = eng(tmp)
    except Exception as e:
        log.info("rapidocr infer err: %s", e)
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    out = []
    for box, text, conf in (res or []):
        x = (box[0][0] + box[2][0]) / 2.0
        y = (box[0][1] + box[2][1]) / 2.0
        h = abs(box[3][1] - box[0][1])   # 块高（同行判定用，坐标系内相对可比）
        out.append((text, x, y, h))
    return out


def _vl_read_title(img):
    """VL 兜底：读标题带聊天名。返回名字文本（读不出/不是聊天页返回 ""）。"""
    try:
        import json
        import urllib.request
        import vision
        model = vision.vl_model()
        if not model:
            return ""
        from PIL import Image
        w, hh = img.size
        crop = img.crop((0, 0, w, 170))
        b64 = base64.b64encode(_pil_to_png(crop)).decode("ascii")
        prompt = ("这是微信窗口顶部截图。右侧聊天面板顶部标题显示的聊天对象名字是什么？"
                  "只输出名字本身；如果右侧不是聊天对话框（比如还是列表页/搜索页），只输出 NONE。")
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt, "images": [b64]}],
            "stream": False, "think": False,
            "options": {"temperature": 0, "num_predict": 30}}).encode("utf-8")
        req = urllib.request.Request(vision.ollama_base() + "/api/chat", data=payload,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.loads(r.read().decode("utf-8")).get("message", {}).get("content", "")
        out = (out or "").strip()
        return "" if not out or "NONE" in out.upper() else out
    except Exception as e:
        log.info("vl read title err: %s", e)
        return ""


def _pil_to_png(img):
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    return bio.getvalue()


def _norm(s):
    return re.sub(r"\s+", "", s or "")


def verify_text_on_screen(text, hwnd):
    """OCR 全图找正文特征片段（粘贴落位终检）。返回 (ok, detail)。

    🔴 用途：冻结检测的最后一环——「微信拒绝注入键盘」时剪贴板读回、聊天名
    验证都可能假通过（目标名恰好是当前聊天标题），只有「正文真的出现在屏幕上」
    才证明粘贴生效。探针取正文中最长的连续可读段（中文/字母/数字）前 6 字，
    再退到前 3 字重试一次（OCR 小字偶尔错一字）。
    找不到探针（正文全是 emoji 等）→ True（无法验证时不拦，交给用户肉眼）。
    """
    t = _norm(text)
    m = re.search(r"[0-9A-Za-z\u4e00-\u9fff]{4,}", text or "")
    probe = m.group(0)[:6] if m else None
    if not probe:
        return True, "正文无可读探针，跳过落位验证"
    img = _grab_window(hwnd)
    if img is None:
        return False, "截不到微信窗口"
    texts = _ocr_texts(img)
    if not texts:
        return False, "读屏没读到内容"
    joined = _norm("".join(x[0] for x in texts))
    if _norm(probe) in joined:
        return True, "正文已上屏"
    short = probe[:3]
    if short and short in joined:
        return True, "正文已上屏（模糊命中）"
    return False, "正文没出现在屏幕上（微信疑似没响应键盘粘贴）"


def verify_chat_name(target, hwnd, vl_fallback=True):
    """读屏验证当前聊天对象是否为 target。返回 (ok: bool, detail: str)。

    fail-closed：OCR 空 / 越界 / 引擎全挂 → (False, 原因)，调用方必须拒绝发送。
    detail 里带读到的候选名，供人话回执。
    """
    t = _norm(target)
    if not t or not hwnd:
        return False, "参数空"
    # 屏幕截图要求微信在前台（_grab_window 的前提），不满足就拒绝
    try:
        import ctypes
        if ctypes.windll.user32.GetForegroundWindow() != hwnd:
            return False, "微信不在前台，读屏不可信"
    except Exception:
        pass
    img = _grab_window(hwnd)
    if img is None:
        return False, "截不到微信窗口"
    # 🔴 只 OCR 顶部窄条，判定用「第一行聚类」：RapidOCR 返回的 box 坐标在它内部
    #   缩放图的坐标系里（缩放系数随输入尺寸变，绝对坐标/比例都不可信），但同一
    #   结果集内的**相对距离**不受缩放影响。聊天页第一行 = 搜索框+聊天名；列表页
    #   第一行只有搜索框（列表项在第二行以下，被同行判定排除）。
    w, hh = img.size
    band_img = img.crop((0, 0, w, max(60, int(hh * _TITLE_BAND))))
    texts = _ocr_texts(band_img)
    if texts:
        y0 = min(x[2] for x in texts)
        h_avg = sum((x[3] for x in texts), 0.0) / len(texts)
        first_row = [x for x in texts if (x[2] - y0) <= h_avg * 1.5]
        # 🔴 聊天名 = 第一行里 x 最靠右的块。搜索框恒在聊天名左边（列表页布局固定），
        #   这样即使搜索框里正好有目标词（搜索浮层未关 + 右侧开着别的聊天），也不会
        #   把搜索词误当聊天名放行——拼整行匹配有这个误放行通道，09-14 夜测堵上。
        title = _norm(max(first_row, key=lambda b: b[1])[0])
        # 🔴 搜一搜页标题形如「张俊杨－搜一搜」——它包含目标名（搜索词=目标名时）
        # 会穿透下面的子串匹配造成误放行（09-15 凌晨实测：填进了搜一搜页）。
        # 含「搜一搜」一律拒绝，优先级最高。
        if "搜一搜" in title or "搜素" in title:
            return False, "打开的是搜一搜页不是聊天（%s），没敢填" % title[:20]
        if title and title == t:
            return True, "标题读到「%s」" % title[:20]
        # 某些布局聊天名旁带图标字（OCR 粘连）→ 允许标题块包含目标名的精确子串
        if title and t in title:
            return True, "标题读到「%s」" % title[:20]
        if title:
            return False, "当前聊天不是「%s」（标题读到「%s」）" % (target, title[:20])
        all_txt = _norm("".join(x[0] for x in texts))
        return False, "顶部没有聊天名（读到「%s」）——不像在聊天页" % all_txt[:20]
    # 窄条一个字都没读到（搜索浮层盖脸/渲染抽风/引擎挂）→ VL 兜底或拒绝
    if vl_fallback:
        name = _vl_read_title(img)
        if name and t in _norm(name):
            return True, "VL 读到「%s」" % name[:20]
        if name:
            return False, "当前聊天不是「%s」（VL 读到「%s」）" % (target, name[:20])
    return False, "读屏没读到聊天名（可能在搜索页/浮层）"
