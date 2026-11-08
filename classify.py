# -*- coding: utf-8 -*-
"""笔记智能处理（后台）：归类打标签 + 自动抽取时间承诺设提醒。

- 分类/抽取走 smart.py 统一智能层（优先小模型 qwen2.5:1.5b）。
- 类别列表来自 categories.txt（用户可在面板增删）。
- 设了自动提醒会弹原生通知（点开直达面板那条笔记）。
- Ollama 没开 → 全部静默跳过，绝不影响记事主流程。
"""
import logging
import threading
from datetime import datetime

import config
import store
import smart
from toast import native_toast

log = logging.getLogger("classify")

CATEGORIES = ["待办", "购物", "想法", "日常"]  # 兜底（实际以 categories.txt 为准）


def _panel_url(nid=""):
    try:
        port = config.load()["server"]["port"]
    except Exception:
        port = 8777
    return f"http://127.0.0.1:{port}/#n={nid}"


def process_async(nid, text):
    """后台线程：归类 + 抽提醒 + 弹可见提示。不抛异常、不阻塞。"""
    def work():
        try:
            cats = store.read_categories()
            res = smart.process_note(text or "", cats)
            # --- 联系人捕获（先于打标签：信息类笔记会被移出主列表） ---
            try:
                import contacts as _ct
                moved = False
                hits = _ct.capture_for_contacts(text or "")
                if not hits:
                    # 精确匹配没中 → 确定性拼音扫描兜底（同音错字，
                    # 如"谢凤您"与"谢凤林"拼音编辑距离=1，必命中，不依赖模型）
                    names = [c.get("name", "") for c in _ct.list_contacts()]
                    mentioned = _ct.fuzzy_scan_text(text or "", names)
                    todo_hits = []
                    for name in mentioned:
                        c = next((x for x in _ct.list_contacts()
                                  if x.get("name") == name), None)
                        if c:
                            todo_hits.append({"contact": c, "kind": "todo",
                                              "detail": text})
                    hits = todo_hits
                for h in hits:
                    c = h["contact"]
                    if h["kind"] == "info":
                        _ct.add_info(c["id"], h["detail"])
                        if h.get("field") and h.get("value"):
                            _ct.update_contact(c["id"], {h["field"]: h["value"]})
                        store.soft_delete(nid)
                        moved = True
                        native_toast("📇 已存入联系人",
                                     "%s · %s" % (c.get("name", ""), h["detail"]),
                                     launch=_panel_url())
                        log.info("contact info %s -> %s", c.get("name"), h["detail"])
                    elif _ct.is_todo_note(text or "", res.get("category", "")):
                        # 提醒时间：明确时间(模型抽取) > 场景关键词默认表 > 不定
                        remind = res.get("remind_at") or _ct.suggest_remind_time(text)
                        _ct.add_todo(c["id"], text[:80], remind_at=remind)
                        tip = ("，已定 %s 提醒" % remind[11:16]) if remind else ""
                        native_toast("📇 待办已记到「%s」名下" % c.get("name", ""),
                                     text[:60] + tip, launch=_panel_url())
                        log.info("contact todo %s <- %s (remind_at=%s)",
                                 c.get("name"), nid[:8], remind)
            except Exception as e:
                log.info("contact capture error: %s", e)
            if moved:
                return
            tag = res.get("category")
            if tag:
                store.add_tag(nid, tag)
                log.info("classified %s -> %s", nid[:8], tag)
            # 课堂笔记自动归课（P3）：创建时间落进某课时段 ±15 分钟 → 打课程名标签
            try:
                import courses as _co
                n = store.get_note(nid)
                if n:
                    for ctag in _co.auto_tag_courses(n.get("created_at")):
                        store.add_tag(nid, ctag)
                        log.info("course tag %s -> %s", nid[:8], ctag)
            except Exception as e:
                log.info("course tag error: %s", e)
            ra = res.get("remind_at")
            if ra:
                store.set_reminder(nid, ra)
                dt = datetime.fromisoformat(ra)
                label = dt.strftime("%m-%d %H:%M")
                url = _panel_url(nid)
                native_toast(
                    "⏰ 已自动设提醒",
                    f"{label} · {(text or '')[:40]}",
                    launch=url,
                    actions=[("📋 打开面板", url)],
                )
                log.info("auto reminder %s -> %s", nid[:8], ra)
        except Exception as e:
            log.info("process error: %s", e)
    threading.Thread(target=work, daemon=True).start()


# 旧名兼容（main.do_capture / server.create 调用点不变）
classify_async = process_async
