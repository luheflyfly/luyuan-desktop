# -*- coding: utf-8 -*-
"""路远 · 老笔记字段归一化（数据体检报告 2026-09-06 建议 #2）

做什么：给缺少契约字段的老笔记补上 device:"pc" / schema:1 / updated_at（=创建时间）。
- 只补缺失字段，已有的字段一个都不改
- 动手前自动把整个 notes 目录打包备份到 data/backups/manual_归一化前.zip
- 跑完弹窗告诉你改了几条
- 跑一次就够，重复跑不会再改任何东西

双击「一键整理笔记字段.bat」运行即可。
"""
import os
import sys
import glob
import json
import time
import zipfile
import ctypes

BASE = os.path.dirname(os.path.abspath(__file__))
NOTES = os.path.join(BASE, "data", "notes")
BACKUPS = os.path.join(BASE, "data", "backups")


def msg(text, title="路远 · 整理笔记字段"):
    ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)


def main():
    if not os.path.isdir(NOTES):
        msg("找不到笔记目录：\n" + NOTES)
        return 1

    # 1) 先备份（安全第一）
    os.makedirs(BACKUPS, exist_ok=True)
    zpath = os.path.join(BACKUPS, "manual_%s_归一化前.zip" % time.strftime("%Y%m%d_%H%M%S"))
    n_files = 0
    try:
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for fp in glob.glob(os.path.join(NOTES, "**", "*"), recursive=True):
                if os.path.isfile(fp):
                    z.write(fp, os.path.relpath(fp, NOTES))
                    n_files += 1
    except Exception as e:
        msg("备份失败，已停止，未改动任何笔记：\n" + str(e))
        return 1

    # 2) 只补缺失字段
    changed = 0
    skipped = 0
    for fp in sorted(glob.glob(os.path.join(NOTES, "*.json"))):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                n = json.load(f)
        except Exception:
            skipped += 1
            continue
        if not isinstance(n, dict) or not n.get("text"):
            skipped += 1          # 联系人等非笔记文件不碰
            continue
        dirty = False
        if "device" not in n:
            n["device"] = "pc"
            dirty = True
        if "schema" not in n:
            n["schema"] = 1
            dirty = True
        if "updated_at" not in n:
            n["updated_at"] = n.get("created_at") or ""
            dirty = True
        if dirty:
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(n, f, ensure_ascii=False, indent=2)
            changed += 1

    msg("整理完成！\n\n"
        "补全字段：%d 条\n"
        "跳过（无需处理）：%d 条\n"
        "动笔前备份：%s（%d 个文件）\n\n"
        "已有的字段一个都没动；以后新笔记会自动带全字段，这个脚本不用再跑。"
        % (changed, skipped, os.path.basename(zpath), n_files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
