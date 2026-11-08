# -*- coding: utf-8 -*-
"""微信线夜班批② · 一键复验脚本（路河重启微信 + 重启路远之后跑）。

用法：cd <project-root> && ./.venv/Scripts/python.exe verify_wechat_night.py
四道检查全过 = A10 完整闭环，可以考虑把 auto_send 改 true（决策材料见
`微信自动化现状与路线建议_2026-09-14.md`）。

⚠️ 检查 3/4 会真实操作微信窗口：需要微信在前台附近、别同时打字。
   全程不会按回车、不会发出任何消息（安全模式）。
"""
import io
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import router          # noqa: E402
import wechat          # noqa: E402


def main():
    results = []

    def record(name, ok, detail=""):
        results.append((name, ok, detail))
        print("%s %s %s" % ("✅" if ok else "❌", name, detail))

    # ── 1. 解析层（不碰微信）────────────────────────────────
    print("== 检查 1/4 · 解析层 ==")
    cases = [
        ("给妈妈说：明天开会", ("妈妈", "明天开会")),
        ("给张俊扬说训练改到周四", ("张俊杨", "训练改到周四")),   # 同音纠正
        ("帮我把明天开会的事告诉张三", ("张三", "明天开会的事")),  # 倒装
        ("给妈妈买药", None),
    ]
    bad = sum(1 for t, w in cases if router.parse_wechat_resolved(t) != w)
    record("解析层 %d 用例" % len(cases), bad == 0,
           "（%d 挂）" % bad if bad else "")

    # ── 2. 微信窗口 ────────────────────────────────────────
    print("== 检查 2/4 · 微信窗口 ==")
    h = wechat.find_wechat()
    record("微信窗口", bool(h), hex(h) if h else "没找到，先开微信")
    if not h:
        return _summary(results)

    # ── 3. 键盘是否解冻 + 定位/填正文全链路 ───────────────────
    print("== 检查 3/4 · 定位+填正文（安全模式，不发送）==")
    wechat.activate(h)
    r = wechat.locate_and_fill("路河", "夜班复验：看到本条说明链路全通（删掉即可）")
    record("定位「路河」并填正文", r.get("ok") is True, r.get("label", "")[:40])
    if not r.get("ok"):
        print("   → 若报「微信没响应键盘」= 冻结未解除，重启微信再跑一次本脚本")

    # ── 4. 错误名字拦截（读屏验证）────────────────────────────
    print("== 检查 4/4 · 错误名字拦截 ==")
    r = wechat.locate_and_fill("张俊杨", "本条不该被填进任何聊天")
    record("错误名「张俊杨」被拦", r.get("ok") is False, r.get("label", "")[:40])

    return _summary(results)


def _summary(results):
    ok = sum(1 for _, o, _ in results if o)
    print("-" * 50)
    print("复验结果：%d/%d 通过%s" % (ok, len(results),
          " —— A10 完整闭环 ✅" if ok == len(results) else " —— 有未过项，见上方 ❌"))
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
