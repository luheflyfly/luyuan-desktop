"""【系统 Python 3.14 运行 · 有 tkinter】「路远」唤醒词训练图形界面。

这是一个真正的窗口，不会像黑窗口那样一闪而过。
它通过子进程调用 venv 里的 train_worker.py（无黑窗），按钮控制录音。
启动方式：双击「训练路远唤醒词.bat」（内部用 wscript 隐藏方式打开本文件）。
"""
import os
import sys
import json
import subprocess
import threading

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

BASE = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(BASE, ".venv", "Scripts", "python.exe")
WORKER = os.path.join(BASE, "train_worker.py")
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


class TrainerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("路远 · 训练「路远」唤醒词")
        self.root.geometry("560x520")
        self.root.resizable(False, False)
        try:
            self.root.attributes("-topmost", True)
        except Exception:
            pass

        self.proc = None
        self.reader_thread = None
        self.continuous = False
        self.rec_sched = None
        self.running = False

        self._build()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------- UI ----------------
    def _build(self):
        pad = {"padx": 10, "pady": 5}
        ttk.Label(self.root, text="路远 · 训练「路远」语音唤醒词",
                  font=("Microsoft YaHei", 14, "bold")).pack(padx=10, pady=(12, 2))
        ttk.Label(self.root,
                  text="安静环境、离麦近一点，把『路远』说清楚。录完自动训练。",
                  font=("Microsoft YaHei", 9)).pack(padx=10)

        frm = ttk.Frame(self.root)
        frm.pack(fill="x", padx=10, pady=8)
        ttk.Label(frm, text="正样本(说路远)条数:").grid(row=0, column=0, sticky="w")
        self.e_pos = ttk.Entry(frm, width=8)
        self.e_pos.insert(0, "40")
        self.e_pos.grid(row=0, column=1, padx=6)
        ttk.Label(frm, text="负样本(其他/安静)条数:").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.e_neg = ttk.Entry(frm, width=8)
        self.e_neg.insert(0, "30")
        self.e_neg.grid(row=0, column=3, padx=6)
        self.b_start = ttk.Button(frm, text="开始训练", command=self.on_start)
        self.b_start.grid(row=0, column=4, padx=(14, 0))

        self.status = ttk.Label(self.root, text="准备就绪",
                                font=("Microsoft YaHei", 11, "bold"),
                                foreground="#1a73e8")
        self.status.pack(padx=10, pady=(4, 0), anchor="w")
        self.progress = ttk.Label(self.root, text="正样本 0/0   负样本 0/0")
        self.progress.pack(padx=10, anchor="w")

        bf = ttk.Frame(self.root)
        bf.pack(fill="x", padx=10, pady=6)
        self.b_rec = ttk.Button(bf, text="● 录制本条", command=self.on_rec,
                                state="disabled")
        self.b_rec.pack(side="left", padx=4)
        self.b_cont = ttk.Button(bf, text="连续录制：关", command=self.on_toggle_cont,
                                 state="disabled")
        self.b_cont.pack(side="left", padx=4)
        self.b_stop = ttk.Button(bf, text="停止", command=self.on_stop,
                                 state="disabled")
        self.b_stop.pack(side="left", padx=4)
        self.b_amb = ttk.Button(bf, text="🎙️ 录30秒环境声", command=self.on_ambient)
        self.b_amb.pack(side="left", padx=4)
        ttk.Button(bf, text="退出", command=self.on_close).pack(side="right", padx=4)

        self.log = scrolledtext.ScrolledText(self.root, height=14,
                                             font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=10, pady=(6, 10))
        self.log.insert("1.0", "日志：\n")

        self._set_inputs_enabled(True)

    def _set_inputs_enabled(self, on):
        st = "normal" if on else "disabled"
        self.e_pos.configure(state=st)
        self.e_neg.configure(state=st)
        self.b_start.configure(state=st)

    def append_log(self, msg):
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    # ---------------- actions ----------------
    def on_start(self):
        if not os.path.exists(VENV_PY):
            messagebox.showerror("环境错误", "找不到 venv Python：\n%s" % VENV_PY)
            return
        try:
            n_pos = max(1, int(self.e_pos.get() or 40))
            n_neg = max(1, int(self.e_neg.get() or 30))
        except ValueError:
            n_pos, n_neg = 40, 30
        self.e_pos.delete(0, "end"); self.e_pos.insert(0, str(n_pos))
        self.e_neg.delete(0, "end"); self.e_neg.insert(0, str(n_neg))

        self.append_log("启动训练进程…")
        try:
            self.proc = subprocess.Popen(
                [VENV_PY, WORKER],
                cwd=BASE,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
                text=True, bufsize=1, encoding="utf-8", errors="replace")
        except Exception as e:
            messagebox.showerror("启动失败", "无法启动训练进程：\n%s" % e)
            self.append_log("启动失败: %s" % e)
            return

        self.running = True
        self.reader_thread = threading.Thread(target=self.reader, daemon=True)
        self.reader_thread.start()

        self._set_inputs_enabled(False)
        self.b_rec.configure(state="normal")
        self.b_cont.configure(state="normal")
        self.b_stop.configure(state="normal")
        self.send("START %d %d" % (n_pos, n_neg))

    def on_rec(self):
        self.send("REC")

    def on_toggle_cont(self):
        self.continuous = not self.continuous
        self.b_cont.configure(text="连续录制：开" if self.continuous else "连续录制：关")
        if self.continuous:
            self.append_log("连续录制已开：每录完一条会自动录下一条，你只需反复说词。")
            # 如果当前在等样本，马上排一条
            if self.running:
                self._schedule_rec(1200)
        else:
            self.append_log("连续录制已关。")

    def on_stop(self):
        self.send("STOP")
        self.append_log("已发送停止指令。")

    def on_ambient(self):
        """不开始训练，只录 30 秒环境声当负样本（治误触发的关键料）。"""
        if self.proc and self.proc.poll() is None:
            self.append_log("训练进行中，稍后再录环境声。")
            return
        if not self._ensure_worker():
            return
        self.b_amb.configure(state="disabled")
        self.status.configure(text="正在录环境声，请保持房间日常响动…",
                              foreground="#e8710a")
        self.append_log("开始录制 30 秒环境声（风扇/日常底噪都行），请别说话。")
        self.send("AMBIENT 30")

    def _ensure_worker(self):
        """确保 worker 子进程在跑（供只录环境声用，不进入训练会话）。"""
        if self.proc and self.proc.poll() is None:
            return True
        if not os.path.exists(VENV_PY):
            messagebox.showerror("环境错误", "找不到 venv Python：\n%s" % VENV_PY)
            return False
        self.append_log("启动训练进程…")
        try:
            self.proc = subprocess.Popen(
                [VENV_PY, WORKER],
                cwd=BASE,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
                text=True, bufsize=1, encoding="utf-8", errors="replace")
        except Exception as e:
            messagebox.showerror("启动失败", "无法启动训练进程：\n%s" % e)
            self.append_log("启动失败: %s" % e)
            return False
        self.reader_thread = threading.Thread(target=self.reader, daemon=True)
        self.reader_thread.start()
        return True

    def on_close(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write("STOP\n"); self.proc.stdin.flush()
            except Exception:
                pass
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.root.destroy()

    def send(self, line):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write(line + "\n")
                self.proc.stdin.flush()
            except Exception as e:
                self.append_log("发送失败: %s" % e)

    def _schedule_rec(self, ms):
        if self.rec_sched:
            self.root.after_cancel(self.rec_sched)
        self.rec_sched = self.root.after(ms, self._do_scheduled_rec)

    def _do_scheduled_rec(self):
        self.rec_sched = None
        if self.continuous and self.running:
            self.send("REC")

    # ---------------- reader ----------------
    def reader(self):
        try:
            for raw in self.proc.stdout:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:
                    self.root.after(0, self.append_log, raw)
                    continue
                self.root.after(0, self.dispatch, obj)
        except Exception as e:
            self.root.after(0, self.append_log, "读取训练进程出错: %s" % e)
        self.root.after(0, self.on_worker_end)

    def dispatch(self, obj):
        ev = obj.get("event")
        if ev == "ready":
            self.append_log("训练进程就绪。")
        elif ev == "started":
            self.append_log("已开始：正样本 %d 条，负样本 %d 条。" %
                            (obj.get("n_pos", 0), obj.get("n_neg", 0)))
        elif ev == "need_sample":
            ph = obj.get("phase")
            idx = obj.get("index")
            total = obj.get("total")
            if ph == "pos":
                self.status.configure(text="第 %d/%d 条正样本：清晰说『路远』" % (idx, total),
                                      foreground="#1a73e8")
            else:
                self.status.configure(text="第 %d/%d 条负样本：说别的词，或安静坐着" % (idx, total),
                                      foreground="#e8710a")
            if self.continuous:
                self._schedule_rec(1400)
        elif ev == "sample":
            ph = obj.get("phase")
            idx = obj.get("index")
            total = obj.get("total")
            if ph == "pos":
                self.progress.configure(text="正样本 %d/%d   负样本 0/%d" %
                                         (idx, total, self._neg_total()))
            else:
                self.progress.configure(text="正样本 %d/%d   负样本 %d/%d" %
                                         (self._pos_total(), self._pos_total(),
                                          idx, total))
            self.append_log("已保存 %s 样本 %d/%d" % (ph, idx, total))
        elif ev == "log":
            self.append_log(obj.get("msg", ""))
        elif ev == "ambient_start":
            self.append_log("开始录环境声 %d 秒…" % obj.get("seconds", 30))
        elif ev == "ambient_progress":
            sec = obj.get("second", 0)
            total = obj.get("total", 30)
            self.status.configure(text="🎙️ 正在录环境声 %d/%d 秒…保持日常响动" %
                                  (sec, total), foreground="#e8710a")
        elif ev == "ambient_done":
            n = obj.get("slices", 0)
            self.status.configure(text="✅ 环境声已入库（%d 段负样本）" % n,
                                  foreground="#188038")
            self.append_log("环境声录制完成，切成 %d 段负样本。下次训练会自动用上。" % n)
            self.b_amb.configure(state="normal")
        elif ev == "training":
            self.status.configure(text="训练中…（几秒）", foreground="#1a73e8")
            self.append_log("特征提取 + 训练…")
            self.b_rec.configure(state="disabled")
            self.b_cont.configure(state="disabled")
        elif ev == "done":
            self.status.configure(text="✅ 完成！重启『启动路远.bat』即可语音唤醒",
                                  foreground="#188038")
            self.append_log("模型已保存：%s" % obj.get("model"))
            self.append_log("正样本得分 %.2f / 负样本得分 %.2f / 阈值 %.2f" %
                            (obj.get("pos_score", 0), obj.get("neg_score", 0),
                             obj.get("threshold", 0)))
            self.running = False
            self.b_rec.configure(state="disabled")
            self.b_cont.configure(state="disabled")
            self.b_stop.configure(state="disabled")
            messagebox.showinfo("训练完成",
                                "『路远』唤醒词模型已生成！\n\n请退出本窗口，"
                                "重启「启动路远.bat」，之后说『路远』即可唤醒。")
        elif ev == "error":
            msg = obj.get("msg", "未知错误")
            self.append_log("错误: " + msg)
            messagebox.showerror("出错", msg + "\n\n可查看 <project-root>\\train_wakeword.log")
            self.running = False
            self._set_inputs_enabled(True)
            self.b_rec.configure(state="disabled")
            self.b_cont.configure(state="disabled")
            self.b_stop.configure(state="disabled")
        elif ev == "stopped":
            self.append_log("已停止。")
            self.status.configure(text="已停止", foreground="#e8710a")
            self.running = False
            self._set_inputs_enabled(True)
            self.b_rec.configure(state="disabled")
            self.b_cont.configure(state="disabled")
            self.b_stop.configure(state="disabled")

    def on_worker_end(self):
        if self.proc and self.proc.poll() is not None and self.running:
            self.append_log("训练进程已退出。若异常结束，请看 train_wakeword.log。")
            self.running = False

    def _pos_total(self):
        try:
            return int(self.e_pos.get())
        except ValueError:
            return 0

    def _neg_total(self):
        try:
            return int(self.e_neg.get())
        except ValueError:
            return 0


def main():
    root = tk.Tk()
    TrainerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
