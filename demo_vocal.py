"""
demo_vocal.py — 人声合成演示（干声优先）

产出（G:\\tools\\wav_music_gen\\output\\）：
  1. vocal_dry.wav       —— ★ 纯人声干声：元音吟唱（无伴奏、无混响），乐句间换气
  2. vocal_dry_hum.wav   —— ★ 纯人声干声：闭口哼鸣（全 "m"，更闷更"人"）
  3. vocal_demo.wav      —— 参考：升级音色后的混音版（伴奏+人声）

依赖：仅 Python 标准库（配合 autowav/vocal_formant 模块）。
运行：F:\\Python314\\python.exe demo_vocal.py
"""
import os
import sys
import math
import random

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)  # 嵌入式 Python：sys.path[0] 是 python314.zip

from autowav import mix_tracks, samples_to_wav, render_chord_track, OUTPUT_DIR
from theory import SCALES, build_scale_notes
from melody import (generate_motif, motif_to_melody,
                    generate_chord_blocks, generate_bass, generate_drum_beat)
from synthesis import render_note
import vocal_formant as vf

SR = 44100


def stats(name, samples):
    peak = max(abs(s) for s in samples) or 0.0
    rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
    # 6kHz 以上高频能量占比：占比越低 → 越接近人声频谱（无齿音/电子声）
    a = 1 - math.exp(-2 * math.pi * 6000.0 / SR)
    lp = 0.0
    he = 0.0
    tot = 0.0
    for x in samples:
        lp += a * (x - lp)
        hp = x - lp
        he += hp * hp
        tot += x * x
    hf6k = (he / tot) ** 0.5 if tot > 0 else 0.0
    print(f"[{name}] {len(samples) / SR:.2f}s peak={peak:.3f} "
          f"rms={rms:.4f} hf6k_ratio={hf6k:.4f}")


def normalize_peak(samples, target=0.89):
    peak = max(abs(s) for s in samples) or 1.0
    return [s * target / peak for s in samples]


def make_melody_with_breaths(bpm, bars):
    """引擎 motif 旋律 + 每 2 小节乐句边界插入换气（freq=0 静默）。"""
    chord_prog = [1, 6, 4, 5]
    scale_notes = build_scale_notes("C", 4, SCALES["大调"])
    beat = 60.0 / bpm
    motif = generate_motif(scale_notes, chord_prog, bpm, motif_length=8)
    melody = motif_to_melody(motif, scale_notes, beat, bars, 4)

    phrase_len = 2 * 4 * beat          # 每 2 小节 = 8 拍
    phrase_vowels = ["ah", "o", "a", "u"]
    notes, syls = [], []
    t = 0.0
    prev_ph = 0
    for f, d in melody:
        ph = int(t // phrase_len)
        if ph > prev_ph:
            notes.append((0.0, 0.22))  # 换气静默
            syls.append("ah")
        notes.append((f, d))
        syls.append(phrase_vowels[ph % len(phrase_vowels)])
        t += d
        prev_ph = ph
    return notes, syls, scale_notes, chord_prog


def build_dry_vowels(notes, syls):
    vocal = vf.sing(notes, syls, sample_rate=SR, volume=0.9,
                    breath=0.05, aspirate=0.8, seed=7)
    vocal = normalize_peak(vocal)
    out = os.path.join(OUTPUT_DIR, "vocal_dry.wav")
    samples_to_wav(vocal, SR, out)
    stats("dry_vowels", vocal)


def build_dry_hum(notes):
    syls = ["m"] * len(notes)
    hum = vf.sing(notes, syls, sample_rate=SR, volume=0.9,
                  breath=0.02, aspirate=0.4, seed=9)
    hum = normalize_peak(hum)
    out = os.path.join(OUTPUT_DIR, "vocal_dry_hum.wav")
    samples_to_wav(hum, SR, out)
    stats("dry_hum", hum)


def build_mixed(notes, syls, scale_notes, chord_prog, bpm, bars):
    """参考混音版：伴奏 + 人声（音色已升级）。"""
    chord_seq = generate_chord_blocks(scale_notes, chord_prog, bars, bpm,
                                      voicing="open")
    chord_track = render_chord_track(chord_seq, SR, timbre="钢琴", volume=0.16)
    bass_seq = generate_bass(scale_notes, chord_prog, bars, bpm, 4)
    bass_track = []
    for f, d in bass_seq:
        bass_track.extend(render_note(f / 2, d, SR, "正弦波", volume=0.28))
    drum_track = generate_drum_beat(bars, bpm, 4, complexity=0.25)

    vocal = vf.sing(notes, syls, sample_rate=SR, volume=0.85,
                    breath=0.05, aspirate=0.8, seed=7)
    mixed = mix_tracks([vocal, chord_track, bass_track,
                        [s * 0.35 for s in drum_track]], SR)
    out = os.path.join(OUTPUT_DIR, "vocal_demo.wav")
    samples_to_wav(mixed, SR, out)
    stats("mixed_demo", mixed)


if __name__ == "__main__":
    print("=== AutoWav 人声合成演示（干声优先）===")
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    random.seed(20260814)          # 确定性：同种子必复现
    bpm, bars = 96, 8
    notes, syls, scale_notes, chord_prog = make_melody_with_breaths(bpm, bars)
    voiced = [(f, d) for f, d in notes if f > 0]
    print(f"[demo] 旋律 {len(voiced)} 音，换气 {len(notes) - len(voiced)} 处，"
          f"乐句元音 {['ah','o','a','u']}")
    if mode in ("all", "dry_vowels"):
        build_dry_vowels(notes, syls)
    if mode in ("all", "dry_hum"):
        build_dry_hum(notes)
    if mode in ("all", "mixed"):
        build_mixed(notes, syls, scale_notes, chord_prog, bpm, bars)
    print(f"[done] ALL_OK mode={mode}")
