"""
随机音乐生成器 — Tkinter 图形界面（增强版）
零外部依赖，仅使用 Python 标准库（tkinter + 标准库）
新增：对位、和弦织体、曲式结构、Motif 复用
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

# 确保能 import 同目录下的模块
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from synthesis import TIMBRES
from theory import SCALES
import autowav  # generate_music


# ──────────────────────────────────────────
# 音色/调式列表
# ──────────────────────────────────────────
TIMBRE_LIST = TIMBRES
SCALE_LIST  = list(SCALES.keys())

_FORM_LIST = ["自由", "ABA", "AABA", "ABAC"]


class MusicGenGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🎵 随机音乐生成器 — AutoWav GUI")
        self.geometry("640x920")
        self.resizable(False, False)
        self.configure(bg="#1e1e2e")

        self.output_path = None
        self._build_widgets()

    # ──────────────────────────────────────
    # UI 布局
    # ──────────────────────────────────────
    def _build_widgets(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TLabel",      background="#1e1e2e", foreground="#cdd6f4", font=("微软雅黑", 10))
        style.configure("TButton",      font=("微软雅黑", 10, "bold"), padding=6)
        style.configure("Accent.TButton",
                       background="#89b4fa", foreground="#1e1e2e",
                       font=("微软雅黑", 11, "bold"), padding=8)
        style.map("Accent.TButton", background=[("active", "#74c7ec")])
        style.configure("TLabelFrame",  background="#1e1e2e", foreground="#89b4fa",
                       font=("微软雅黑", 10, "bold"))
        style.configure("TLabelFrame.Label", background="#1e1e2e", foreground="#89b4fa")
        style.configure("TScale",       background="#1e1e2e")
        style.configure("Horizontal.TScale", background="#1e1e2e")

        # ── 标题 ──
        tk.Label(self, text="🎹 随机音乐生成器  (增强版)",
                 font=("微软雅黑", 16, "bold"),
                 bg="#1e1e2e", fg="#89b4fa").pack(pady=(14, 4))
        tk.Label(self, text="纯 Python 标准库 · 零外部依赖  |  对位/和弦/曲式/Motif",
                 font=("微软雅黑", 9),
                 bg="#1e1e2e", fg="#6c7086").pack(pady=(0, 10))

        # ── 主容器 ──
        main = tk.Frame(self, bg="#1e1e2e")
        main.pack(padx=20, fill="both", expand=True)

        # ── 左列：参数 ──
        left = tk.Frame(main, bg="#1e1e2e")
        left.pack(side="left", fill="y", padx=(0, 15))

        self._add_slider(left, "BPM 速度", "bpm_var", 60, 220, 120)
        self._add_slider(left, "小节数",   "bars_var", 4, 64, 16)

        self._add_combo(left, "调式", "scale_var", SCALE_LIST, 0)
        self._add_combo(left, "音色", "timbre_var", TIMBRE_LIST, 0)
        self._add_combo(left, "曲式", "form_var", _FORM_LIST, 0)

        # ── 音效选项 ──
        opt_frame = tk.LabelFrame(
            left, text="音效选项", font=("微软雅黑", 10, "bold"),
            bg="#1e1e2e", fg="#89b4fa", labelanchor="w",
            relief="groove", bd=1, padx=10, pady=8)
        opt_frame.pack(fill="x", pady=(8, 0))

        self.bass_var      = tk.BooleanVar(value=True)
        self.reverb_var    = tk.BooleanVar(value=True)
        self.chorus_var    = tk.BooleanVar(value=False)
        self.delay_var     = tk.BooleanVar(value=False)
        self.compression_var = tk.BooleanVar(value=False)
        self.arpeggio_var  = tk.BooleanVar(value=False)
        self.drum_var      = tk.BooleanVar(value=False)
        self.counterpoint_var = tk.BooleanVar(value=False)
        self.chords_var       = tk.BooleanVar(value=False)

        ttk.Checkbutton(opt_frame, text="低音声部 (Bass)",           variable=self.bass_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(opt_frame, text="多声部对位 (Counterpoint)", variable=self.counterpoint_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(opt_frame, text="柱式和弦 (Chords)",         variable=self.chords_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(opt_frame, text="混响效果 (Reverb)",      variable=self.reverb_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(opt_frame, text="合唱效果 (Chorus)",      variable=self.chorus_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(opt_frame, text="延迟效果 (Delay)",       variable=self.delay_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(opt_frame, text="动态压缩 (Compression)", variable=self.compression_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(opt_frame, text="琶音轨 (Arpeggio)",     variable=self.arpeggio_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(opt_frame, text="鼓点节奏 (Drum Beat)",  variable=self.drum_var,
                        command=self._on_drum_toggle).pack(anchor="w", pady=2)

        # ── 鼓点复杂度滑块（仅在勾选鼓点时可用）──
        drum_opt_frame = tk.Frame(left, bg="#1e1e2e")
        drum_opt_frame.pack(fill="x", pady=(4, 0))

        self.drum_complexity_var = tk.DoubleVar(value=0.3)
        tk.Label(drum_opt_frame, text="鼓点复杂度：0.3", font=("微软雅黑", 9),
                 bg="#1e1e2e", fg="#cdd6f4", anchor="w").pack(fill="x")
        self.drum_scale = ttk.Scale(
            drum_opt_frame, from_=0.0, to=1.0, value=0.3,
            orient="horizontal", length=260,
            command=self._on_drum_scale)
        self.drum_scale.pack(fill="x")
        self.drum_scale.configure(state="disabled")  # 默认禁用

        # ── 右列：日志 + 按钮 ──
        right = tk.Frame(main, bg="#1e1e2e")
        right.pack(side="right", fill="both", expand=True)

        tk.Label(right, text="📋 生成日志", font=("微软雅黑", 10, "bold"),
                 bg="#1e1e2e", fg="#a6e3a1").pack(anchor="w", pady=(0, 4))

        self.log = scrolledtext.ScrolledText(
            right, width=54, height=30,
            bg="#11111b", fg="#cdd6f4",
            insertbackground="#cdd6f4",
            font=("Consolas", 9),
            relief="sunken", bd=2,
            state="disabled")
        self.log.pack(fill="both", expand=True)

        # ── 按钮区 ──
        btn_frame = tk.Frame(right, bg="#1e1e2e")
        btn_frame.pack(fill="x", pady=(10, 0))

        self.gen_btn = ttk.Button(
            btn_frame, text="🎲 生成音乐", style="Accent.TButton",
            command=self._on_generate)
        self.gen_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.play_btn = ttk.Button(
            btn_frame, text="▶ 播放", command=self._on_play,
            state="disabled")
        self.play_btn.pack(side="left", padx=(0, 6))

        self.save_btn = ttk.Button(
            btn_frame, text="💾 另存为", command=self._on_save,
            state="disabled")
        self.save_btn.pack(side="left")

        # ── 底部状态栏 ──
        self.status_var = tk.StringVar(value="就绪 — 点击「生成音乐」开始")
        tk.Label(self, textvariable=self.status_var,
                 anchor="w", font=("微软雅黑", 9),
                 bg="#181825", fg="#6c7086",
                 relief="sunken", bd=1, padx=10, pady=5).pack(side="bottom", fill="x")

    # ──────────────────────────────────────
    # 鼓点复选框切换：启用/禁用复杂度滑块
    # ──────────────────────────────────────
    def _on_drum_toggle(self):
        if self.drum_var.get():
            self.drum_scale.configure(state="normal")
        else:
            self.drum_scale.configure(state="disabled")

    def _on_drum_scale(self, val):
        v = round(float(val), 2)
        self.drum_complexity_var.set(v)
        # 更新标签文字（找到 drum_opt_frame 内的 Label）
        for child in self.drum_scale.master.winfo_children():
            if isinstance(child, tk.Label):
                child.config(text=f"鼓点复杂度：{v:.2f}")
                break

    # ──────────────────────────────────────
    # 辅助：添加滑块
    # ──────────────────────────────────────
    def _add_slider(self, parent, label, var_name, min_v, max_v, default_v):
        frame = tk.Frame(parent, bg="#1e1e2e")
        frame.pack(fill="x", pady=(4, 2))
        var = tk.IntVar(value=default_v)
        setattr(self, var_name, var)

        lbl = tk.Label(frame, text=f"{label}：{default_v}",
                       font=("微软雅黑", 9),
                       bg="#1e1e2e", fg="#cdd6f4", anchor="w")
        lbl.pack(fill="x")

        def _on_scale(val):
            v = int(float(val))
            var.set(v)
            lbl.config(text=f"{label}：{v}")

        ttk.Scale(frame, from_=min_v, to=max_v, value=default_v,
                   orient="horizontal", length=260,
                   command=_on_scale).pack(fill="x")

    # ──────────────────────────────────────
    # 辅助：添加下拉框
    # ──────────────────────────────────────
    def _add_combo(self, parent, label, var_name, values, default_idx):
        frame = tk.Frame(parent, bg="#1e1e2e")
        frame.pack(fill="x", pady=(4, 2))
        var = tk.StringVar(value=values[default_idx])
        setattr(self, var_name, var)

        tk.Label(frame, text=label, font=("微软雅黑", 9),
                 bg="#1e1e2e", fg="#cdd6f4", anchor="w").pack(fill="x")

        ttk.Combobox(frame, textvariable=var, values=values,
                       state="readonly", width=30,
                       font=("微软雅黑", 9)).pack(fill="x", pady=(2, 0))

    # ──────────────────────────────────────
    # 日志输出（线程安全）
    # ──────────────────────────────────────
    def _log(self, msg, end="\n"):
        self.log.config(state="normal")
        self.log.insert("end", msg + end)
        self.log.see("end")
        self.log.config(state="disabled")
        self.update_idletasks()

    # ──────────────────────────────────────
    # 生成按钮回调（后台线程）
    # ──────────────────────────────────────
    def _on_generate(self):
        self.gen_btn.config(state="disabled")
        self.play_btn.config(state="disabled")
        self.save_btn.config(state="disabled")
        self.status_var.set("生成中…")
        self.output_path = None
        threading.Thread(target=self._generate_worker, daemon=True).start()

    def _generate_worker(self):
        import io
        old_stdout = sys.stdout
        gui = self  # 保存 GUI 引用

        class _Logger:
            def write(self, s):
                if s.strip():
                    gui.after(0, lambda s=s: gui._log(s.rstrip()))
                log_buf.write(s)
            def flush(self):
                pass

        log_buf = io.StringIO()
        sys.stdout = _Logger()

        try:
            form_val = self.form_var.get()
            params = {
                "bpm":              self.bpm_var.get(),
                "scale_name":       self.scale_var.get(),
                "timbre":           self.timbre_var.get(),
                "n_bars":           self.bars_var.get(),
                "add_bass":         self.bass_var.get(),
                "add_reverb":       self.reverb_var.get(),
                "add_chorus":       self.chorus_var.get(),
                "add_delay":        self.delay_var.get(),
                "apply_compression": self.compression_var.get(),
                "add_arpeggio":     self.arpeggio_var.get(),
                "add_drum":         self.drum_var.get(),
                "drum_complexity":  self.drum_complexity_var.get(),
                "add_counterpoint": self.counterpoint_var.get(),
                "add_chords":       self.chords_var.get(),
                "musical_form":     form_val.lower() if form_val != "自由" else None,
                "sample_rate":       44100,
            }

            self._log("=" * 50)
            for k, v in [("BPM", params["bpm"]), ("调式", params["scale_name"]),
                         ("音色", params["timbre"]), ("小节数", params["n_bars"]),
                         ("曲式", form_val),
                         ("低音声部", params["add_bass"]), ("对位", params["add_counterpoint"]),
                         ("柱式和弦", params["add_chords"]),
                         ("混响", params["add_reverb"]),
                         ("合唱", params["add_chorus"]), ("延迟", params["add_delay"]),
                         ("动态压缩", params["apply_compression"]),
                         ("琶音轨", params["add_arpeggio"]),
                         ("鼓点轨", params["add_drum"]),
                         ("鼓点复杂度", params["drum_complexity"])]:
                self._log(f"  {k}：{v}")
            self._log("=" * 50)

            path, _ = autowav.generate_music(**params)
            self.output_path = path

            import wave as _w
            with _w.open(path, "r") as wf:
                n_frames = wf.getnframes()
                sr = wf.getframerate()
                duration_sec = n_frames / sr

            self._log(f"\n✅ 生成完成！")
            self._log(f"   文件：{path}")
            self._log(f"   时长：{duration_sec:.1f} 秒")

            self.after(0, lambda: self.status_var.set(
                f"完成 — {os.path.basename(path)}  ({duration_sec:.1f}s)"))
            self.after(0, lambda: self.play_btn.config(state="normal"))
            self.after(0, lambda: self.save_btn.config(state="normal"))

        except Exception as e:
            import traceback
            self._log(f"\n❌ 错误：{e}")
            self._log(traceback.format_exc())
            self.after(0, lambda e=e: self.status_var.set(f"生成失败：{e}"))
        finally:
            sys.stdout = old_stdout
            self.after(0, lambda: self.gen_btn.config(state="normal"))

    # ──────────────────────────────────────
    # 播放按钮
    # ──────────────────────────────────────
    def _on_play(self):
        if not self.output_path or not os.path.exists(self.output_path):
            messagebox.showwarning("提示", "请先生成音乐文件！")
            return
        try:
            os.startfile(self.output_path)
            self.status_var.set(f"正在播放：{os.path.basename(self.output_path)}")
        except Exception as e:
            messagebox.showerror("播放失败", str(e))

    # ──────────────────────────────────────
    # 另存为按钮
    # ──────────────────────────────────────
    def _on_save(self):
        if not self.output_path or not os.path.exists(self.output_path):
            messagebox.showwarning("提示", "请先生成音乐文件！")
            return
        dst = filedialog.asksaveasfilename(
            title="另存为…",
            defaultextension=".wav",
            filetypes=[("WAV 文件", "*.wav"), ("所有文件", "*.*")])
        if dst:
            import shutil
            shutil.copy2(self.output_path, dst)
            self.status_var.set(f"已保存到：{dst}")
            messagebox.showinfo("保存成功", f"文件已保存到：\n{dst}")


if __name__ == "__main__":
    app = MusicGenGUI()
    app.mainloop()
