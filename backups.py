# -*- coding: utf-8 -*-
"""数据自动备份：每天把 notes 目录（含 contacts/audio/images 子目录）打包 zip，
滚动保留最近 N 份，落在 data/backups/。同步冲突或误删时有后悔药。"""
import os
import glob
import time
import zipfile
import logging

log = logging.getLogger("backups")


def _cleanup(backup_dir, tag, keep):
    """只留最近 keep 份。"""
    if not keep:
        return
    zips = sorted(glob.glob(os.path.join(backup_dir, "%s_*.zip" % tag)))
    for old in zips[:-keep]:
        try:
            os.remove(old)
        except OSError:
            pass


def make_backup(notes_dir, backup_dir, keep=14, tag="notes"):
    """给 notes_dir 打一个当日 zip（已存在则跳过）。返回 zip 路径或 None。"""
    os.makedirs(backup_dir, exist_ok=True)
    _cleanup(backup_dir, tag, keep)   # 无论今天打没打包，滚动保留都先维护一遍
    today = time.strftime("%Y-%m-%d")
    zp = os.path.join(backup_dir, "%s_%s.zip" % (tag, today))
    if os.path.exists(zp):
        return None
    tmp = zp + ".tmp"
    count = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for fp in glob.glob(os.path.join(notes_dir, "**", "*"), recursive=True):
            if os.path.isfile(fp):
                z.write(fp, os.path.relpath(fp, notes_dir))
                count += 1
    os.replace(tmp, zp)   # 原子落盘：写一半的文件不会顶掉旧备份
    log.info("daily backup written: %s (%d files)", zp, count)
    return zp


def daily_backup_loop(notes_dir_fn, backup_dir, keep=14, interval=1800):
    """常驻循环：每半小时看一眼，当天还没有备份就补一个。notes_dir_fn 是取目录的函数。"""
    while True:
        try:
            make_backup(notes_dir_fn(), backup_dir, keep=keep)
        except Exception as e:
            log.warning("backup error: %s", e)
        time.sleep(interval)
