# -*- coding: utf-8 -*-
"""抓取指定标题的窗口内容（不受其他窗口遮挡）—— 供壳层验收截图用。
用法: python _shot_win.py "路远" out.png [--topmost]
"""
import ctypes
import sys

import win32gui
import win32ui
from PIL import Image


def shot(title, path):
    hwnd = win32gui.FindWindow(None, title)
    if not hwnd:
        raise SystemExit("窗口未找到: %s" % title)
    left, top, right, bot = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bot - top
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    save_bmp = win32ui.CreateBitmap()
    save_bmp.CreateCompatibleBitmap(mfc_dc, w, h)
    save_dc.SelectObject(save_bmp)
    # 2 = PW_RENDERFULLCONTENT（WebView2/Chromium 需要）
    ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)
    info = save_bmp.GetInfo()
    bits = save_bmp.GetBitmapBits(True)
    img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRX", 0, 1)
    img.save(path)
    win32gui.DeleteObject(save_bmp.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    print("saved", path, img.size)


if __name__ == "__main__":
    shot(sys.argv[1] if len(sys.argv) > 1 else "路远",
         sys.argv[2] if len(sys.argv) > 2 else "shot.png")