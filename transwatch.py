# -*- coding: utf-8 -*-
"""录音待转写监视器（手机 → 电脑闭环，SYNC_FORMAT 第五节，规格=协作板 App 会话条目）。

每 ~10 秒扫 notes 目录：device=phone、transcribed=false、有 audio、正文还是「语音待转写」占位
→ 等音频文件大小连续两轮不变（Syncthing 同步完了）→ SenseVoice 转写
→ 原地写回 text + transcribed=true + updated_at（音频永不删）→ 重新走智能捕获。
失败跳过、下轮重试；连续失败 5 次冷却半小时，绝不无限烧 CPU。
"""
import os
import glob
import json
import time
import logging
import datetime

log = logging.getLogger("transwatch")

PLACEHOLDER_MARK = "语音待转写"     # App 端占位文本「（语音待转写）」的关键部分
OCR_PLACEHOLDER_MARK = "作业照片待识别"   # vc102 App 端占位「（作业照片待识别）」
OCR_EMPTY_TEXT = "（没识别出文字）"
_EMPTY_TEXT = "（未识别到人声）"
_MAX_ATTEMPTS = 5
_FAIL_COOLDOWN = 1800               # 连续失败 N 次后冷却秒数
_FAIL_BACKOFF = 60                  # 普通失败后的重试间隔秒数

_last_sizes = {}                    # wav 路径 -> 上一轮大小（判断同步是否完成）
_ocr_sizes = {}                     # 图片路径 -> 上一轮大小（vc102 拍作业 OCR）
_attempts = {}                      # note id -> [连续失败次数, 冷却截止时间戳]
_ocr_attempts = {}                  # note id(ocr) -> 同上


def _now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def find_pending(notes_dir):
    """待转写笔记 [(文件路径, note dict)]。条件见模块头注释。"""
    out = []
    for fp in glob.glob(os.path.join(notes_dir, "*.json")):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                n = json.load(f)
        except Exception:
            continue
        if not isinstance(n, dict) or n.get("deleted"):
            continue
        if n.get("transcribed") is not False:      # 只有明确 false 才是待转写
            continue
        if n.get("device") != "phone":             # 手机录音专用通道
            continue
        if PLACEHOLDER_MARK not in (n.get("text") or ""):
            continue                                # 用户已自己改过正文 → 不覆盖
        if not n.get("audio"):
            continue
        out.append((fp, n))
    return out


def process_one(fp, note, notes_dir, notify=None):
    """转写一条并原地写回。失败抛异常（由循环计数）。返回转写文本。
    notify(text, note_id)：转写完成后的可见反馈回调（main 传原生通知）。"""
    import stt
    wav = os.path.join(notes_dir, str(note["audio"]).replace("/", os.sep))
    if not os.path.exists(wav):
        raise FileNotFoundError(wav)
    text, raw = stt.transcribe(wav, return_raw=True)
    text = (text or "").strip() or _EMPTY_TEXT
    with open(fp, "r", encoding="utf-8") as f:
        n = json.load(f)
    n["text"] = text
    n["transcribed"] = True
    n["updated_at"] = _now_iso()
    if raw:
        n["raw_text"] = raw          # 原始识别留底（与 PC 语音笔记同约定）
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(n, f, ensure_ascii=False, indent=2)
    log.info("transcribed %s -> %s", str(n.get("id"))[:8], text[:40])
    if notify:
        try:
            notify(text, str(n.get("id")))
        except Exception:
            pass
    # 真正文落地后重新智能捕获（归类/联系人待办/提醒全套，失败静默）
    try:
        import classify
        classify.classify_async(n["id"], text)
    except Exception:
        pass
    return text


def find_ocr_pending(notes_dir):
    """待识别作业照片笔记 [(文件路径, note dict)]（vc102 拍作业 OCR 闭环）。
    条件：device=phone、正文含占位、有 images。"""
    out = []
    for fp in glob.glob(os.path.join(notes_dir, "*.json")):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                n = json.load(f)
        except Exception:
            continue
        if not isinstance(n, dict) or n.get("deleted"):
            continue
        if n.get("device") != "phone":
            continue
        if OCR_PLACEHOLDER_MARK not in (n.get("text") or ""):
            continue
        if not (n.get("images") or []):
            continue
        out.append((fp, n))
    return out


def ocr_one(fp, note, notes_dir, notify=None):
    """识别一条作业照片并原地写回：占位符替换为 OCR 文本，占位原文留 raw_text。
    失败抛异常（由循环计数冷却）。notify(text, note_id) 见 process_one。"""
    import wechat_ocr
    img_rel = str((note.get("images") or [""])[0]).replace("/", os.sep)
    img = os.path.join(notes_dir, img_rel)
    if not os.path.exists(img):
        raise FileNotFoundError(img)
    text = wechat_ocr.ocr_image_path(img) or OCR_EMPTY_TEXT
    with open(fp, "r", encoding="utf-8") as f:
        n = json.load(f)
    old = n.get("text") or ""
    n["raw_text"] = old                # 占位原文留底
    n["text"] = old.replace("（" + OCR_PLACEHOLDER_MARK + "）", text)
    n["ocr_done"] = True
    n["updated_at"] = _now_iso()
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(n, f, ensure_ascii=False, indent=2)
    log.info("ocr %s -> %s", str(n.get("id"))[:8], text[:40])
    if notify:
        try:
            notify("作业照片识别：" + text[:60], str(n.get("id")))
        except Exception:
            pass
    try:
        import classify
        classify.classify_async(n["id"], n["text"])
    except Exception:
        pass
    return text


def watch_loop(interval=10, notify=None):
    """常驻循环，main.py 起 daemon 线程跑。notify(text, note_id) 见 process_one。"""
    global _last_sizes
    import store
    while True:
        try:
            nd = store.notes_dir()
            for fp, n in find_pending(nd):
                nid = str(n.get("id"))
                wav = os.path.join(nd, str(n["audio"]).replace("/", os.sep))
                if not os.path.exists(wav):
                    continue                          # 音频还没同步到，等
                try:
                    size = os.path.getsize(wav)
                except OSError:
                    continue
                prev = _last_sizes.get(wav)
                _last_sizes[wav] = size
                if prev is None or prev != size:
                    continue                          # 大小还在变 = 还在同步
                if size < 100:
                    continue                          # 半截文件
                att = _attempts.get(nid, [0, 0])
                if time.time() < att[1]:
                    continue                          # 冷却中
                try:
                    process_one(fp, n, nd, notify=notify)
                    _attempts.pop(nid, None)
                except Exception as e:
                    att[0] += 1
                    att[1] = time.time() + (_FAIL_COOLDOWN if att[0] >= _MAX_ATTEMPTS
                                            else _FAIL_BACKOFF)
                    _attempts[nid] = att
                    log.warning("transcribe %s failed x%d: %s", nid[:8], att[0], e)
            # vc102：拍作业 OCR 闭环（同轮询；图片同样等同步稳定后再识别）
            for fp, n in find_ocr_pending(nd):
                nid = "ocr_" + str(n.get("id"))
                img_rel = str((n.get("images") or [""])[0]).replace("/", os.sep)
                img = os.path.join(nd, img_rel)
                if not os.path.exists(img):
                    continue
                try:
                    size = os.path.getsize(img)
                except OSError:
                    continue
                prev = _ocr_sizes.get(img)
                _ocr_sizes[img] = size
                if prev is None or prev != size:
                    continue                  # 大小还在变 = 还在同步
                if size < 1000:
                    continue                  # 半截/坏图
                att = _ocr_attempts.get(nid, [0, 0])
                if time.time() < att[1]:
                    continue                  # 冷却中
                try:
                    ocr_one(fp, n, nd, notify=notify)
                    _ocr_attempts.pop(nid, None)
                except Exception as e:
                    att[0] += 1
                    att[1] = time.time() + (_FAIL_COOLDOWN if att[0] >= _MAX_ATTEMPTS
                                            else _FAIL_BACKOFF)
                    _ocr_attempts[nid] = att
                    if att[0] == 3:
                        # vc103 深化：持续失败不再完全静默，第 3 次通知一次
                        try:
                            notify("作业照片识别连续失败，已暂停重试", str(n.get("id")))
                        except Exception:
                            pass
                    log.warning("ocr %s failed x%d: %s", nid[:8], att[0], e)
            # 已处理的 wav 从大小表清掉，防长期驻留
            alive = {os.path.join(nd, str(n.get("audio")).replace("/", os.sep))
                     for _, n in find_pending(nd)}
            _last_sizes = {k: v for k, v in _last_sizes.items() if k in alive}
        except Exception as e:
            log.warning("transwatch error: %s", e)
        time.sleep(interval)
