"""
batch_vocals.py — 批量生成纯人声干声（元音吟唱 / 哼鸣，无伴奏、无混响）

用法:
  <venv-python> batch_vocals.py --count 50            # 生成 50 个（vocal_001 ... vocal_050）
  <venv-python> batch_vocals.py --start 20 --count 10 # 断点续跑（已存在自动跳过）
  --mode vowels|hum|mix（默认 mix：70% 吟唱 / 30% 哼鸣）
  --bpm-min 72 --bpm-max 132 --bars-min 4 --bars-max 8
  --pure  # 强制纯 stdlib 渲染（慢，仅当无 numpy/scipy 时）

命名规范（output/vocal_batch/ 下）:
  vocal_{序号:03d}_{mode}_b{bpm}_s{seed}.wav
  例: vocal_001_vowels_b96_s202608140001.wav
  + manifest.json —— 每首的完整参数/seed/时长/峰值/创建时间（保证可复现、可检索）
"""
import os
import sys
import json
import math
import time
import random
import struct
import wave
import argparse

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)  # 嵌入式 Python：sys.path[0] 是 python314.zip

from theory import SCALES, CHORD_PROGRESSIONS, build_scale_notes
from melody import generate_motif, motif_to_melody

try:
    import numpy as np
    import vocal_render_np as fast
    HAVE_NP = True
except Exception:
    HAVE_NP = False
import vocal_formant as vf

SR = 44100
OUT_DIR = os.path.join(_SCRIPT_DIR, "output", "vocal_batch")
MANIFEST_PATH = os.path.join(OUT_DIR, "manifest.json")
BASE_SEED = 202608140000

# 乐句元音组合候选（含单元音长音款），保证样本间听感差异
VOWEL_SETS = [
    ["ah", "o", "a", "u"],
    ["a", "e", "i", "o"],
    ["ah", "ah", "o", "a"],
    ["u", "o", "a", "ah"],
    ["a", "a", "i", "a"],
    ["ah", "e", "o", "u"],
    ["ah"], ["a"], ["o"], ["u"], ["i"],
]
SCALE_CHOICES = ["大调", "自然小调", "五声大调", "五声小调", "多利安"]
ROOTS = ["C", "D", "E", "F", "G", "A", "B"]


def sample_params(idx, mode):
    """每个样本独立 seed（可复现），参数在合法范围内随机。"""
    seed = BASE_SEED + idx
    r = random.Random(seed)
    m = "vowels" if r.random() < 0.7 else "hum" if mode == "mix" else mode
    if m == "hum":
        bpm = r.randint(70, 95)
    else:
        bpm = r.randint(72, 132)
    bars = r.randint(4, 8)
    return {
        "seed": seed, "mode": m, "bpm": bpm, "bars": bars,
        "scale": r.choice(SCALE_CHOICES), "root": r.choice(ROOTS),
        "octave": r.choice([4, 5]),
        "chord": r.choice(CHORD_PROGRESSIONS),
        "vowels": r.choice(VOWEL_SETS) if m == "vowels" else ["m"],
    }


def make_notes(p):
    """引擎 motif 旋律 + 每 2 小节换气（freq=0 静默）。"""
    random.seed(p["seed"])
    scale_notes = build_scale_notes(p["root"], p["octave"],
                                    SCALES[p["scale"]])
    beat = 60.0 / p["bpm"]
    motif = generate_motif(scale_notes, p["chord"], p["bpm"], motif_length=8)
    melody = motif_to_melody(motif, scale_notes, beat, p["bars"], 4)

    phrase_len = 2 * 4 * beat
    notes, syls = [], []
    t = 0.0
    prev_ph = 0
    for f, d in melody:
        ph = int(t // phrase_len)
        if ph > prev_ph:
            notes.append((0.0, 0.22))
            syls.append(p["vowels"][0])
        notes.append((f, d))
        syls.append(p["vowels"][ph % len(p["vowels"])])
        t += d
        prev_ph = ph
    return notes, syls


def render(notes, syls, p, use_fast):
    breath = 0.02 if p["mode"] == "hum" else 0.05
    aspirate = 0.4 if p["mode"] == "hum" else 0.8
    if use_fast:
        return fast.sing_np(notes, syls, sample_rate=SR, volume=0.9,
                            breath=breath, aspirate=aspirate,
                            seed=p["seed"])
    return vf.sing(notes, syls, sample_rate=SR, volume=0.9,
                   breath=breath, aspirate=aspirate,
                   seed=p["seed"] % (2 ** 32))


def normalize_peak(samples, target=0.89):
    if HAVE_NP and hasattr(samples, "abs"):
        peak = float(np.max(np.abs(samples))) or 1.0
        return samples * (target / peak)
    peak = max(abs(s) for s in samples) or 1.0
    return [s * target / peak for s in samples]


def write_wav(path, samples):
    if HAVE_NP and hasattr(samples, "astype"):
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
        data = pcm.tobytes()
    else:
        data = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767))
                        for s in samples)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(data)


def load_manifest():
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"generator": "batch_vocals.py", "files": []}


def save_manifest(man):
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser(description="批量生成纯人声干声")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=50)
    ap.add_argument("--mode", choices=["vowels", "hum", "mix"], default="mix")
    ap.add_argument("--pure", action="store_true",
                    help="强制纯 stdlib 渲染（慢）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在文件")
    args = ap.parse_args()

    use_fast = HAVE_NP and not args.pure
    print(f"[batch] 渲染引擎: {'numpy/scipy 加速' if use_fast else '纯 stdlib'}")
    os.makedirs(OUT_DIR, exist_ok=True)
    man = load_manifest()
    done_names = {r["file"] for r in man["files"]} if not args.force else set()

    t_all = time.time()
    made = skipped = 0
    for idx in range(args.start, args.start + args.count):
        p = sample_params(idx, args.mode)
        name = (f"vocal_{idx + 1:03d}_{p['mode']}_b{p['bpm']}_"
                f"s{p['seed']}.wav")
        path = os.path.join(OUT_DIR, name)
        if name in done_names or os.path.exists(path):
            skipped += 1
            continue
        t0 = time.time()
        notes, syls = make_notes(p)
        samples = normalize_peak(render(notes, syls, p, use_fast))
        write_wav(path, samples)
        dur = len(samples) / SR
        peak = (float(np.max(np.abs(samples))) if HAVE_NP
                else max(abs(s) for s in samples))
        man["files"].append({
            "file": name, "idx": idx, "mode": p["mode"], "bpm": p["bpm"],
            "bars": p["bars"], "scale": p["scale"], "root": p["root"],
            "octave": p["octave"], "chord": p["chord"],
            "vowels": p["vowels"], "seed": p["seed"],
            "dur_s": round(dur, 2), "peak": round(peak, 4),
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        save_manifest(man)
        made += 1
        print(f"[{made + skipped}/{args.count}] {name} "
              f"({dur:.1f}s, 渲染 {time.time() - t0:.1f}s)",
              flush=True)
    print(f"[batch] 完成：新增 {made}，跳过 {skipped}，"
          f"总耗时 {time.time() - t_all:.1f}s")
    print(f"[batch] 产物目录: {OUT_DIR}")
    print(f"[batch] 清单: {MANIFEST_PATH}")
    print("[batch] ALL_OK")


if __name__ == "__main__":
    main()
