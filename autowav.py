"""
随机音乐生成器 — 主编排模块（旋律主题 / 对位 / 和弦织体 / 曲式）
纯 Python 标准库实现，零外部依赖
模块结构: theory / synthesis / melody / effects / form / autowav (编排)
"""

import os
import sys

# 路径引导：嵌入式 Python（如本机 /Python314）运行脚本时不会自动把
# 脚本所在目录加入 sys.path[0]，需手动加入，确保同目录的本地模块可被导入。
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import wave
import struct
import math
import random
import gzip
import json
import re
from datetime import datetime

# 零依赖扩展模块（均仅使用标准库）
from midi_io import (
    write_midi, read_midi, freq_to_midi, midi_to_melody_idx,
)
from score import compute_features, score_track, rank_results
# 后端抽象层 + 可选神经后端（acestep 注册到此；缺失依赖时优雅降级）
from backend import get_backend, available_backends
import backends_acestep  # 触发 ACEStepBackend 注册（仅类定义，不加载重依赖）

# ── 导入子模块 ──
from theory import (
    NOTE_NAMES, SCALES, CHORD_PROGRESSIONS,
    note_freq, build_scale_notes, compute_tension_curve,
)
from synthesis import (
    TIMBRES, render_note, render_samples,
)
from melody import (
    generate_melody, generate_bass,
    generate_arpeggio, generate_drum_beat,
    generate_motif, vary_motif, motif_to_melody,
    generate_counterpoint, generate_chord_blocks,
)
from effects import (
    apply_reverb, apply_chorus, apply_delay,
    low_pass_filter, dynamic_compression,
)
from form import build_form_structure

# 向后兼容：重新导出常用符号
__all__ = [
    "NOTE_NAMES", "SCALES", "CHORD_PROGRESSIONS", "TIMBRES",
    "generate_music", "generate_music_by_duration",
    "compress_wav_file", "save_gzip_wav",
    "interactive_mode", "batch_mode",
]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")


# ── 音频混合 ──

def mix_tracks(tracks: list, sample_rate: int) -> list:
    """多轨混合，自动对齐长度，归一化"""
    max_len = max(len(t) for t in tracks) if tracks else 0
    mixed = [0.0] * max_len
    for track in tracks:
        for i, s in enumerate(track):
            mixed[i] += s

    peak = max(abs(s) for s in mixed) or 1.0
    if peak > 0.9:
        factor = 0.9 / peak
        mixed = [s * factor for s in mixed]
    return mixed


def samples_to_wav(samples: list, sample_rate: int, filepath: str,
                   n_channels: int = 1, bit_depth: int = 16):
    """将浮点样本序列写入 WAV 文件"""
    max_val = (2 ** (bit_depth - 1)) - 1
    fmt = "<h" if bit_depth == 16 else "<i"

    with wave.open(filepath, "w") as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(bit_depth // 8)
        wf.setframerate(sample_rate)

        for s in samples:
            clamped = max(-1.0, min(1.0, s))
            wf.writeframes(struct.pack(fmt, int(clamped * max_val)))

    print(f"  ✓ WAV 文件已保存: {filepath}")


# ── 和弦轨渲染 ──

def render_chord_track(chord_seq: list, sample_rate: int,
                       timbre: str = "钢琴", volume: float = 0.3) -> list:
    """将柱式和弦序列渲染为音频 samples。
    chord_seq: [(freqs_list, dur_sec), ...] — 每个元素是一组同时发声的频率。
    按声部独立渲染后混合。"""
    if not chord_seq:
        return []
    max_voices = max(len(c[0]) for c in chord_seq)
    voice_tracks = [[] for _ in range(max_voices)]

    for c in chord_seq:
        freqs, dur = c[0], c[1]
        for v in range(max_voices):
            freq = freqs[v] if v < len(freqs) else 0
            voice_tracks[v].extend(
                render_note(freq, dur, sample_rate, timbre,
                           volume=volume / max(1, max_voices))
            )

    return mix_tracks(voice_tracks, sample_rate)


# ── 文件工具 ──

def compress_wav_file(input_path: str, output_path: str = None) -> str:
    """读取 WAV 文件，应用动态压缩后保存"""
    if output_path is None:
        base, ext = os.path.splitext(input_path)
        output_path = base + "_compressed.wav"

    with wave.open(input_path, 'r') as wf:
        params = wf.getparams()
        n_frames = wf.getnframes()
        raw_data = wf.readframes(n_frames)

    n_channels = params.nchannels
    sampwidth = params.sampwidth
    sample_rate = params.framerate

    if sampwidth == 2:
        fmt = f"<{n_frames * n_channels}h"
        samples = struct.unpack(fmt, raw_data)
        samples = [s / 32768.0 for s in samples]
    else:
        raise ValueError(f"不支持的位深度: {sampwidth * 8} bit")

    compressed = dynamic_compression(samples, sample_rate=sample_rate)

    with wave.open(output_path, 'w') as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        for s in compressed:
            clamped = max(-1.0, min(1.0, s))
            wf.writeframes(struct.pack("<h", int(clamped * 32767)))

    return output_path


def save_gzip_wav(filepath: str) -> str:
    """将 WAV 文件用 GZIP 压缩保存"""
    gz_path = filepath + ".gz"

    with open(filepath, 'rb') as f_in:
        with gzip.open(gz_path, 'wb') as f_out:
            f_out.writelines(f_in)

    original_size = os.path.getsize(filepath)
    compressed_size = os.path.getsize(gz_path)
    ratio = (1 - compressed_size / original_size) * 100

    print(f"  ✓ GZIP 压缩文件已保存: {gz_path}")
    print(f"  原始大小: {original_size/1024:.1f} KB → 压缩后: {compressed_size/1024:.1f} KB (减少 {ratio:.1f}%)")
    return gz_path


# ── 主生成流程 ──

def generate_music(output_path: str = None,
                   bpm: int = None,
                   scale_name: str = None,
                   root_note: str = None,
                   root_octave: int = None,
                   timbre: str = None,
                   n_bars: int = None,
                   add_bass: bool = None,
                   add_reverb: bool = None,
                   add_chorus: bool = None,
                   add_delay: bool = None,
                   apply_compression: bool = None,
                   compression_ratio: float = 4.0,
                   compression_threshold: float = 0.5,
                   add_arpeggio: bool = None,
                   add_drum: bool = None,
                   drum_complexity: float = 0.3,
                   add_counterpoint: bool = None,
                   add_chords: bool = None,
                   musical_form: str = None,
                   sample_rate: int = 44100,
                   # ── 新增：MIDI 桥 / 评分 / 旋律种子（均零依赖、可选）──
                   export_midi: bool = False,
                   midi_path: str = None,
                   import_midi_path: str = None,
                   return_score: bool = False,
                   melody_seed: list = None,
                   # ── 新增：全局和弦进行 / 主题动机（跨段收束，零依赖）──
                   chord_progression: list = None,
                   motif_seed = None):
    """
    随机生成一段音乐并保存为 WAV 文件。返回 (文件路径, 参数字典)。

    新增参数:
        add_counterpoint — 多声部对位
        add_chords       — 柱式和弦织体
        musical_form     — 曲式结构: "aba" | "aaba" | "abac" | None
    """
    bpm         = bpm        or random.randint(70, 160)
    scale_name  = scale_name or random.choice(list(SCALES.keys()))
    root_note   = root_note  or random.choice(["C", "D", "E", "F", "G", "A", "B"])
    root_octave = root_octave if root_octave is not None else random.choice([4, 5])
    timbre      = timbre     or random.choice(TIMBRES)
    n_bars      = n_bars     or random.randint(8, 48)
    add_bass    = add_bass   if add_bass is not None else random.choice([True, False])
    add_reverb  = add_reverb if add_reverb is not None else random.choice([True, False])
    add_chorus  = add_chorus if add_chorus is not None else False
    add_delay   = add_delay  if add_delay is not None else False
    apply_compression = apply_compression if apply_compression is not None else random.choice([True, False])
    add_arpeggio = add_arpeggio if add_arpeggio is not None else random.choice([True, False])
    add_drum    = add_drum    if add_drum is not None else random.choice([True, False])
    add_counterpoint = add_counterpoint if add_counterpoint is not None else random.choice([True, False])
    add_chords  = add_chords  if add_chords is not None else random.choice([True, False])
    musical_form = musical_form or (random.choice(["aba", None, None]) if n_bars >= 16 else None)

    # ── 全局和弦进行：用户自定义覆盖随机选择，成为全曲和声骨架 ──
    _user_chord = _parse_chord_progression(chord_progression)
    chord_prog  = _user_chord if _user_chord else random.choice(CHORD_PROGRESSIONS)
    time_sig    = 4
    scale_intervals = SCALES[scale_name]
    scale_notes    = build_scale_notes(root_note, root_octave, scale_intervals)
    scale_len = len(scale_notes) // 2 if len(scale_notes) >= 2 else len(scale_notes)
    # ── 全局主题动机解析（跨段复现；None 表示不启用）──
    motif = _resolve_motif(motif_seed, scale_notes, chord_prog, bpm, scale_len)

    # ── 曲式结构 ──
    if musical_form:
        form = build_form_structure(musical_form, n_bars, chord_prog, scale_intervals)
    else:
        form = {
            "form_name": None,
            "sections": [{
                "label": "-", "bar_start": 0, "bar_end": n_bars,
                "n_bars": n_bars, "chord_prog": chord_prog,
                "tension_curve": compute_tension_curve(n_bars),
            }],
            "motif_sections": [],
        }

    params = {
        "bpm":        bpm,
        "调式":       scale_name,
        "主音":       f"{root_note}{root_octave}",
        "音色":       timbre,
        "小节数":     n_bars,
        "曲式":       musical_form or "自由",
        "低音声部":   add_bass,
        "对位声部":   add_counterpoint,
        "柱式和弦":   add_chords,
        "混响":       add_reverb,
        "合唱":       add_chorus,
        "延迟":       add_delay,
        "动态压缩":   apply_compression,
        "琶音轨":     add_arpeggio,
        "鼓点轨":     add_drum,
        "和弦进行":   chord_prog,
        "自定义和弦": bool(_user_chord),
        "主题动机":   (f"{len(motif)}音 跨段复现" if motif else "无（随机/曲式）"),
    }

    print("\n🎵 随机音乐生成器")
    print("=" * 40)
    if musical_form:
        print(f"  曲式结构: {form.get('description', musical_form)}")
    for k, v in params.items():
        print(f"  {k}: {v}")
    print("=" * 40)

    # ══════════════════════════════════════════════════
    #  逐段生成：支持 motif 复用 & 曲式隔离
    # ══════════════════════════════════════════════════
    tracks = []
    melody_track: list = []
    # MIDI 导出用的符号音符表（按需填充，未启用声部保持空列表）
    melody_notes = []
    counter_notes = []
    bass_notes = []
    arp_notes = []
    chord_notes = []
    note_beat_dur = 60.0 / bpm
    bar_dur_sec = time_sig * note_beat_dur
    melody_index_seq: list = []  # [(freq_idx, dur_beats), ...] 用于对位

    # ── 旋律种子（来自导入的 MIDI 或外部指定）──
    if import_midi_path:
        print(f"  从 MIDI 导入旋律种子: {import_midi_path}")
        _midi_tracks = read_midi(import_midi_path)
        _notes = _midi_tracks[0]["notes"] if _midi_tracks else []
        melody_seed = midi_to_melody_idx(_notes, scale_notes, bpm)

    if melody_seed:
        # 外置 / MIDI 种子：直接循环展开（最高优先级，覆盖 motif）
        melody_track, melody_index_seq = _melody_from_seed(
            melody_seed, scale_notes, note_beat_dur, n_bars, time_sig)
        print(f"  使用旋律种子（{len(melody_seed)} 音）生成旋律…")

    elif motif is not None:
        # ── 全局主题动机：每段一个变奏，贯穿全曲形成可辨识的"动机" ──
        _var_cycle = ["none", "transpose_up", "transpose_down",
                      "augment", "diminish", "invert", "shifted", "retrograde"]
        print(f"  生成全局主题动机（{len(motif)} 音），逐段变奏复现…")
        _si = 0
        for sec in form["sections"]:
            sec_bars = sec["n_bars"]
            var = _var_cycle[_si % len(_var_cycle)]
            varied = vary_motif(motif, scale_notes, var, scale_len)
            sec_melody = motif_to_melody(varied, scale_notes, note_beat_dur,
                                         sec_bars, time_sig)
            sec_idx_seq = [(idx, dur_beats) for idx, dur_beats in varied]
            melody_track.extend(sec_melody)
            melody_index_seq.extend(sec_idx_seq)
            print(f"  段落 {sec['label']} ({sec_bars} 小节) → 动机变奏 {var}")
            _si += 1

    else:
        # ── 现有逻辑：曲式的 motif 段用 motif（随机生成一次），其余马尔可夫 ──
        _motif = None
        for sec in form["sections"]:
            label = sec["label"]
            sec_bars = sec["n_bars"]
            sec_chord = sec["chord_prog"]
            sec_tension = sec["tension_curve"]

            print(f"  段落 {label} ({sec_bars} 小节)…")

            if label in form.get("motif_sections", []):
                if _motif is None:
                    # 首次生成主题 motif
                    _motif = generate_motif(scale_notes, sec_chord, bpm,
                                           motif_length=min(8, max(4, sec_bars * 2)))
                    print(f"    → 生成主题 motif ({len(_motif)} 音)")
                    sec_melody = motif_to_melody(_motif, scale_notes, note_beat_dur,
                                                 sec_bars, time_sig)
                    sec_idx_seq = [(idx, dur_beats) for idx, dur_beats in _motif]
                else:
                    # 复用/变奏 motif
                    var_type = random.choice([
                        "none", "transpose_up", "transpose_down",
                        "augment", "diminish", "invert", "shifted",
                    ])
                    varied = vary_motif(_motif, scale_notes, var_type, scale_len)
                    print(f"    → 变奏 motif ({var_type})")
                    sec_melody = motif_to_melody(varied, scale_notes, note_beat_dur,
                                                 sec_bars, time_sig)
                    sec_idx_seq = [(idx, dur_beats) for idx, dur_beats in varied]
            else:
                # 非 motif 段用马尔可夫链自由生成
                sec_melody = generate_melody(scale_notes, sec_bars, bpm, time_sig,
                                             chord_prog=sec_chord,
                                             tension_curve=sec_tension)
                # 从 sec_melody 反推索引（用频率匹配）
                sec_idx_seq = _melody_to_indices(sec_melody, scale_notes)

            melody_track.extend(sec_melody)
            melody_index_seq.extend(sec_idx_seq)

    # ── 渲染旋律轨 ──
    print("  渲染旋律…")
    melody_audio = []
    melody_notes = []  # 用于 MIDI 导出: [(midi, start_sec, dur_sec, vel), ...]
    elapsed_time = 0.0
    for freq, dur in melody_track:
        bar_now = min(int(elapsed_time / max(bar_dur_sec, 0.01)), n_bars - 1)
        t_now = 0.5  # 默认张力（跨段简化）
        melody_audio.extend(render_note(freq, dur, sample_rate, timbre, volume=0.75, tension=t_now))
        m = freq_to_midi(freq)
        if m is not None:
            melody_notes.append((m, elapsed_time, dur, 90))
        elapsed_time += dur
    tracks.append(melody_audio)

    # ── 多声部对位 ──
    if add_counterpoint and melody_index_seq:
        print("  生成对位旋律…")
        counter_seq = generate_counterpoint(
            melody_index_seq, scale_notes,
            form["sections"][0]["chord_prog"], n_bars, bpm, time_sig,
        )
        counter_track = []
        counter_notes = []
        _ct_start = 0.0
        for freq, dur in counter_seq:
            # 对位用不同音色（柔和一些）
            ct_timbre = "正弦波" if timbre in ("钢琴", "吉他", "竖琴") else "钢琴"
            counter_track.extend(render_note(freq, dur, sample_rate, ct_timbre, volume=0.4))
            m = freq_to_midi(freq)
            if m is not None:
                counter_notes.append((m, _ct_start, dur, 70))
            _ct_start += dur
        max_len = max(len(t) for t in tracks) if tracks else len(counter_track)
        pad = [0.0] * (max_len - len(counter_track))
        counter_track += pad
        tracks.append(counter_track[:max_len])

    # ── 柱式和弦织体 ──
    if add_chords:
        print("  生成柱式和弦…")
        voicing = random.choice(["close", "open", "drop2"])
        chord_seq = generate_chord_blocks(scale_notes, form["sections"][0]["chord_prog"],
                                          n_bars, bpm, time_sig, voicing=voicing)
        chord_audio = render_chord_track(chord_seq, sample_rate, timbre="钢琴", volume=0.25)
        tracks.append(chord_audio)
        # 收集和弦音符用于 MIDI（每声部独立音高，沿用 onset 精确定位）
        chord_notes = []
        for freqs, dur, onset in chord_seq:
            for f in freqs:
                m = freq_to_midi(f)
                if m is not None:
                    chord_notes.append((m, onset, dur, 60))

    # ── 低音 ──
    if add_bass:
        print("  生成低音…")
        bass_seq = generate_bass(scale_notes, form["sections"][0]["chord_prog"],
                                 n_bars, bpm, time_sig)
        bass_track = []
        bass_timbre = "正弦波" if timbre in ("方波", "锯齿波") else "正弦波"
        _bass_start = 0.0
        for freq, dur in bass_seq:
            bass_track.extend(render_note(freq / 2, dur, sample_rate, bass_timbre, volume=0.45))
            m = freq_to_midi(freq / 2)
            if m is not None:
                bass_notes.append((m, _bass_start, dur, 80))
            _bass_start += dur
        tracks.append(bass_track)

    # ── 琶音 ──
    if add_arpeggio:
        print("  生成琶音…")
        arp_seq = generate_arpeggio(scale_notes, form["sections"][0]["chord_prog"],
                                    n_bars, bpm, time_sig)
        arp_track = render_samples(arp_seq, sample_rate, timbre="钢琴", volume=0.35)
        tracks.append(arp_track)
        _arp_start = 0.0
        for freq, dur in arp_seq:
            m = freq_to_midi(freq)
            if m is not None:
                arp_notes.append((m, _arp_start, dur, 65))
            _arp_start += dur

    # ── 鼓点 ──
    if add_drum:
        print(f"  生成鼓点（复杂度 {drum_complexity:.1f}）…")
        drum_samples = generate_drum_beat(n_bars, bpm, time_sig, complexity=drum_complexity)
        max_len = max(len(t) for t in tracks) if tracks else len(drum_samples)
        drum_resized = drum_samples + [0.0] * (max_len - len(drum_samples))
        drum_resized = drum_resized[:max_len]
        if tracks:
            for i in range(min(len(tracks[0]), len(drum_resized))):
                tracks[0][i] += drum_resized[i] * 0.5

    # ── 混合 + 效果器 ──
    print("  混合音轨…")
    mixed = mix_tracks(tracks, sample_rate)

    if add_reverb:
        print("  应用混响…")
        mixed = apply_reverb(mixed, sample_rate,
                             delay_ms=random.uniform(60, 120),
                             decay=random.uniform(0.2, 0.45),
                             mix=0.3)

    if add_chorus:
        print("  应用合唱效果…")
        mixed = apply_chorus(mixed, sample_rate,
                            rate=random.uniform(0.4, 0.8),
                            depth=random.uniform(0.002, 0.004),
                            mix=random.uniform(0.2, 0.35))

    if add_delay:
        print("  应用延迟效果…")
        mixed = apply_delay(mixed, sample_rate,
                           delay_time=random.uniform(0.25, 0.45),
                           feedback=random.uniform(0.25, 0.45),
                           mix=random.uniform(0.2, 0.35))

    if timbre in ("方波", "锯齿波"):
        mixed = low_pass_filter(mixed, cutoff_ratio=0.25)

    if apply_compression:
        print(f"  应用动态压缩 (阈值={compression_threshold}, 比率={compression_ratio}:1)…")
        mixed = dynamic_compression(mixed,
                                   threshold=compression_threshold,
                                   ratio=compression_ratio,
                                   sample_rate=sample_rate)

    peak = max(abs(s) for s in mixed) or 1.0
    mixed = [s * 0.88 / peak for s in mixed]

    # ── 批量质量自动评分（零依赖启发式）──
    if return_score:
        features = compute_features(melody_index_seq, mixed, sample_rate)
        score_val = score_track(features)
        params["评分"] = score_val

    # 输出路径处理
    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(OUTPUT_DIR, f"music_{ts}.wav")
    elif not os.path.isabs(output_path):
        output_path = os.path.join(OUTPUT_DIR, output_path)

    # ── MIDI 导出（纯标准库，零依赖；置于输出路径确定之后）──
    if export_midi:
        _midi_tracks = []
        if melody_notes:
            _midi_tracks.append({"name": "旋律", "channel": 0, "notes": melody_notes})
        if counter_notes:
            _midi_tracks.append({"name": "对位", "channel": 1, "notes": counter_notes})
        if bass_notes:
            _midi_tracks.append({"name": "低音", "channel": 2, "notes": bass_notes})
        if chord_notes:
            _midi_tracks.append({"name": "和弦", "channel": 3, "notes": chord_notes})
        if arp_notes:
            _midi_tracks.append({"name": "琶音", "channel": 4, "notes": arp_notes})
        if _midi_tracks:
            if midi_path is None:
                midi_path = os.path.splitext(output_path)[0] + ".mid"
            elif not os.path.isabs(midi_path):
                midi_path = os.path.join(OUTPUT_DIR, midi_path)
            midi_dir = os.path.dirname(midi_path)
            if midi_dir and not os.path.exists(midi_dir):
                os.makedirs(midi_dir)
            write_midi(_midi_tracks, midi_path, bpm=bpm)

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"  创建目录: {output_dir}")

    samples_to_wav(mixed, sample_rate, output_path)
    print(f"\n🎼 完成！时长约 {len(mixed)/sample_rate:.1f} 秒")
    return output_path, params


def _melody_from_seed(seed: list, scale_notes: list,
                      beat_dur: float, n_bars: int,
                      time_sig: int = 4) -> tuple:
    """把旋律种子 [(音高索引, 时长拍), ...] 循环展开为完整旋律。
    返回 (melody_track, melody_index_seq):
      melody_track:    [(freq, dur_sec), ...]
      melody_index_seq:[(freq_idx, dur_beats), ...]  用于对位
    """
    target_sec = n_bars * time_sig * beat_dur
    melody = []
    idx_seq = []
    total = 0.0

    if not seed:
        return melody, idx_seq

    while total < target_sec:
        for idx, dur_beats in seed:
            dur = dur_beats * beat_dur
            if total + dur > target_sec:
                dur = max(0.0, target_sec - total)
            if dur <= 0:
                break
            melody.append((scale_notes[idx], dur))
            idx_seq.append((idx, dur_beats))
            total += dur
            if total >= target_sec:
                break
    return melody, idx_seq


def _melody_to_indices(melody: list, scale_notes: list) -> list:
    """将 [(freq, dur_sec), ...] 转为 [(freq_idx, dur_beats), ...]。
    用于从马尔可夫链输出提取索引序列给对位声部。"""
    result = []
    for freq, dur in melody:
        if freq <= 0:
            idx = 0
        else:
            # 找最接近的频率索引
            idx = min(range(len(scale_notes)),
                      key=lambda i: abs(scale_notes[i] - freq))
        result.append((idx, dur))
    return result


# ═══════════════════════════════════════════════════════════════════
#  全局参数解析：和弦进行 / 主题动机（均零依赖）
# ═══════════════════════════════════════════════════════════════════

def _parse_chord_progression(spec) -> list:
    """把用户输入规范为 1 起算的音阶级数列表 [1..7]，或 None。
    支持:
      - list/tuple: [1, 5, 6, 4]
      - 数字串:      "1 5 6 4" / "1,5,6,4" / "1-5-6-4"
      - 罗马/和弦名: "I-V-vi-IV" / "i-iv-V-i"
    超出范围的值会被保留（由子生成器 modulo 处理），空输入返回 None。"""
    if spec is None:
        return None
    if isinstance(spec, (list, tuple)):
        out = [int(x) for x in spec]
        return out or None

    s = str(spec).strip()
    if not s:
        return None

    # 罗马/和弦名映射（大小写不敏感）
    roman = {
        "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7,
        "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7,
        "bVI": 8, "bIII": 3, "bVII": 7,
    }
    if "-" in s or any(r in s for r in ("I", "V", "i", "v")):
        toks = re.split(r"[\s\-]+", s)
        out = []
        for t in toks:
            t = t.strip()
            if t in roman:
                out.append(roman[t])
        if out:
            return out

    # 否则按阿拉伯数字解析
    nums = re.findall(r"-?\d+", s)
    out = [int(x) for x in nums]
    return out or None


def _parse_motif_seed(spec) -> list:
    """紧凑记法 -> [(音高索引, 时长拍), ...]（音高索引为音阶内 0 起算）。
    记法: 空格/逗号分隔的 token；每个 token '<degree>[:<dur>]'，
          degree = 音阶内 0 起算索引，dur = 拍数（默认 1.0）。
    例: '0 2 4 2:2 0' -> [(0,1),(2,1),(4,1),(2,2),(0,1)]
    空输入返回 None。越界索引会被子生成器在渲染时钳制。"""
    if not spec:
        return None
    s = str(spec).strip()
    tokens = re.split(r"[\s,]+", s)
    out = []
    for tok in tokens:
        if not tok:
            continue
        if ":" in tok:
            deg_s, dur_s = tok.split(":", 1)
            out.append((int(deg_s), float(dur_s)))
        else:
            out.append((int(tok), 1.0))
    return out if out else None


def _resolve_motif(motif_seed, scale_notes: list, chord_prog: list,
                   bpm: int, scale_len: int) -> list:
    """把 motif_seed 规范为统一的 [(音高索引, 时长拍), ...]，或 None。
      - None / False       -> None（不启用全局主题）
      - True               -> 引擎自动生成一次 motif（每次调用随机；跨段一致需调用方自行保存）
      - list/tuple（非空）  -> 显式动机，校验为 (idx, dur_beats)
      - str                -> 走 _parse_motif_seed 紧凑记法"""
    if motif_seed is None or motif_seed is False:
        return None
    if isinstance(motif_seed, (list, tuple)) and motif_seed:
        out = []
        for item in motif_seed:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                out.append((int(item[0]), float(item[1])))
            elif isinstance(item, (int, float)):
                out.append((int(item), 1.0))
        return out if out else None
    if isinstance(motif_seed, str):
        return _parse_motif_seed(motif_seed)
    if motif_seed is True:
        return generate_motif(scale_notes, chord_prog, bpm, motif_length=8)
    return None


def generate_music_by_duration(output_path: str = None,
                               target_duration: float = 60.0,
                               bpm: int = None,
                               scale_name: str = None,
                               root_note: str = None,
                               root_octave: int = None,
                               timbre: str = None,
                               add_bass: bool = None,
                               add_reverb: bool = None,
                               apply_compression: bool = None,
                               compression_ratio: float = 4.0,
                               compression_threshold: float = 0.5,
                               add_counterpoint: bool = None,
                               add_chords: bool = None,
                               musical_form: str = None,
                               sample_rate: int = 44100,
                               gzip_compress: bool = False,
                               return_score: bool = False,
                               # ── 新增：MIDI 桥 / 旋律种子 / 全局和弦+主题（转发给 generate_music）──
                               export_midi: bool = False,
                               midi_path: str = None,
                               import_midi_path: str = None,
                               melody_seed: list = None,
                               chord_progression: list = None,
                               motif_seed = None):
    """按目标时长生成音乐"""
    bpm = bpm or random.randint(70, 160)
    beat_dur = 60.0 / bpm
    bars_needed = int(target_duration / (4 * beat_dur)) + 1

    path, params = generate_music(
        output_path=output_path, bpm=bpm,
        scale_name=scale_name, root_note=root_note,
        root_octave=root_octave, timbre=timbre,
        n_bars=bars_needed, add_bass=add_bass,
        add_reverb=add_reverb, apply_compression=apply_compression,
        compression_ratio=compression_ratio,
        compression_threshold=compression_threshold,
        add_counterpoint=add_counterpoint,
        add_chords=add_chords,
        musical_form=musical_form,
        sample_rate=sample_rate,
        return_score=return_score,
        export_midi=export_midi,
        midi_path=midi_path,
        import_midi_path=import_midi_path,
        melody_seed=melody_seed,
        chord_progression=chord_progression,
        motif_seed=motif_seed,
    )

    if gzip_compress:
        print("  应用 GZIP 压缩…")
        gz_path = save_gzip_wav(path)
        return gz_path, params

    return path, params


# ── CLI 模式 ──

def interactive_mode():
    print("\n" + "=" * 50)
    print("   🎹 随机音乐生成器 — 纯 Python 标准库版")
    print("=" * 50)
    print("按 Enter 随机生成，或输入参数自定义\n")

    def ask(prompt, default=None, choices=None):
        if choices:
            display = f"{prompt} [{'/'.join(choices)}] (默认随机): "
        elif default is not None:
            display = f"{prompt} (默认 {default}): "
        else:
            display = f"{prompt} (默认随机): "
        val = input(display).strip()
        if not val:
            return default
        if choices and val not in choices:
            print(f"  ! 无效输入，使用随机值")
            return default
        return val

    raw_bpm = ask("BPM 速度 (60-200)")
    bpm = int(raw_bpm) if raw_bpm and raw_bpm.isdigit() else None

    scale_list = list(SCALES.keys())
    print(f"  可选调式: {', '.join(scale_list)}")
    raw_scale = ask("调式")
    scale_name = raw_scale if raw_scale in scale_list else None

    print(f"  可选音色: {', '.join(TIMBRES)}")
    raw_timbre = ask("音色")
    timbre = raw_timbre if raw_timbre in TIMBRES else None

    raw_bars = ask("小节数 (4-64)", default="16")
    n_bars = int(raw_bars) if raw_bars and raw_bars.isdigit() else None

    raw_bass = ask("是否加低音轨 (y/n)", choices=["y", "n"])
    add_bass = True if raw_bass == "y" else (False if raw_bass == "n" else None)

    raw_reverb = ask("是否加混响 (y/n)", choices=["y", "n"])
    add_reverb = True if raw_reverb == "y" else (False if raw_reverb == "n" else None)

    raw_compression = ask("是否加动态压缩 (y/n)", choices=["y", "n"])
    apply_compression = True if raw_compression == "y" else (False if raw_compression == "n" else None)

    raw_gzip = ask("是否用 GZIP 压缩文件 (y/n)", choices=["y", "n"])
    gzip_compress = raw_gzip == "y"

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_out = os.path.join(OUTPUT_DIR, f"music_{ts}.wav")
    raw_out = ask(f"输出文件路径", default=default_out)
    output_path = raw_out if raw_out else default_out

    path, params = generate_music(
        output_path=output_path, bpm=bpm,
        scale_name=scale_name, timbre=timbre,
        n_bars=n_bars, add_bass=add_bass,
        add_reverb=add_reverb, apply_compression=apply_compression,
    )

    if gzip_compress:
        print("  应用 GZIP 压缩…")
        path = save_gzip_wav(path)

    print(f"\n  文件路径: {os.path.abspath(path)}")
    print("  用任意音频播放器打开即可欣赏！")


def batch_mode(count: int = 3, rank: bool = False, bars: int = None,
                chord_progression: list = None, motif_seed = None):
    """批量生成多首随机音乐。rank=True 时自动评分并排序，写 batch_report.json。

    bars: 指定每首小节数（None 时默认 4~16 小节，避免单首过长导致资源受限环境被中断）。
    chord_progression / motif_seed: 可选，批量内统一和声骨架与主题动机（使整批风格一致）。
    """
    print(f"\n🎲 批量生成 {count} 首随机音乐…" + ("（启用质量评分）" if rank else ""))
    results = []
    for i in range(1, count + 1):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = os.path.join(OUTPUT_DIR, f"music_{i:02d}_{ts}.wav")
        # 批量默认偏短，便于在受限环境快速跑完并产出报告
        n_bars = bars if bars else random.randint(4, 16)
        print(f"\n── 第 {i} 首 ──")
        path, params = generate_music(
            output_path=out, n_bars=n_bars, return_score=rank,
            chord_progression=chord_progression, motif_seed=motif_seed,
        )
        results.append({"path": path, "params": params,
                        "score": params.get("评分", None)})

    if rank:
        ranked = rank_results(results)
        print("\n📊 质量评分排名（高→低）:")
        print("-" * 60)
        for r in ranked:
            print(f"  #{r['rank']:>2}  评分 {r['score']:>5}  {os.path.basename(r['path'])}")
            print(f"        调式={r['params'].get('调式')} 音色={r['params'].get('音色')} "
                  f"BPM={r['params'].get('bpm')} 曲式={r['params'].get('曲式')}")
        report_path = os.path.join(OUTPUT_DIR, "batch_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(ranked, f, ensure_ascii=False, indent=2)
        print(f"\n  ✓ 批量报告已保存: {report_path}")


# ── 参数解析 ──

def parse_args():
    args = sys.argv[1:]
    result = {
        "mode": "interactive",
        "batch_count": 3,
        "duration": None,
        "compress": False,
        "output_dir": None,
        "bpm": None,
        "bars": None,
        "backend": "symbolic",
        "export_midi": False,
        "midi_out": None,
        "import_midi": None,
        "rank": False,
        "chord_progression": None,
        "motif_seed": None,
    }

    if "--help" in args or "-h" in args:
        result["mode"] = "help"
        return result

    if "--random" in args:
        result["mode"] = "random"
        for i, arg in enumerate(args):
            if arg == "--duration" and i + 1 < len(args):
                try:
                    result["duration"] = float(args[i + 1])
                except ValueError:
                    pass
            elif arg == "--compress":
                result["compress"] = True
            elif arg == "--output-dir" and i + 1 < len(args):
                result["output_dir"] = args[i + 1]
            elif arg == "--bpm" and i + 1 < len(args):
                try:
                    result["bpm"] = int(args[i + 1])
                except ValueError:
                    pass
            elif arg == "--bars" and i + 1 < len(args):
                try:
                    result["bars"] = int(args[i + 1])
                except ValueError:
                    pass
            elif arg == "--backend" and i + 1 < len(args):
                result["backend"] = args[i + 1]
            elif arg == "--export-midi":
                result["export_midi"] = True
            elif arg == "--midi-out" and i + 1 < len(args):
                result["midi_out"] = args[i + 1]
            elif arg == "--import-midi" and i + 1 < len(args):
                result["import_midi"] = args[i + 1]
            elif arg == "--chord-progression" and i + 1 < len(args):
                result["chord_progression"] = args[i + 1]
            elif arg == "--motif-seed" and i + 1 < len(args):
                result["motif_seed"] = args[i + 1]
            elif arg == "--motif":
                result["motif_seed"] = True

    elif "--batch" in args:
        result["mode"] = "batch"
        try:
            idx = args.index("--batch")
            result["batch_count"] = int(args[idx + 1])
        except (IndexError, ValueError):
            result["batch_count"] = 3
        for i, arg in enumerate(args):
            if arg == "--backend" and i + 1 < len(args):
                result["backend"] = args[i + 1]
            elif arg == "--rank":
                result["rank"] = True
            elif arg == "--export-midi":
                result["export_midi"] = True
            elif arg == "--bars" and i + 1 < len(args):
                try:
                    result["bars"] = int(args[i + 1])
                except ValueError:
                    pass
            elif arg == "--chord-progression" and i + 1 < len(args):
                result["chord_progression"] = args[i + 1]
            elif arg == "--motif-seed" and i + 1 < len(args):
                result["motif_seed"] = args[i + 1]
            elif arg == "--motif":
                result["motif_seed"] = True

    return result


# ── 入口 ──

if __name__ == "__main__":
    parsed = parse_args()

    if parsed["mode"] == "help":
        print("""
用法:
  python autowav.py                        # 交互式模式（推荐）
  python autowav.py --random               # 直接随机生成一首
  python autowav.py --random --duration N  # 生成约 N 秒的音乐
  python autowav.py --random --compress    # 生成并用 GZIP 压缩
  python autowav.py --random --bars N      # 指定小节数
  python autowav.py --random --export-midi # 同时导出标准 MIDI
  python autowav.py --random --import-midi x.mid  # 用导入的 MIDI 当旋律种子
  python autowav.py --random --chord-progression "1 5 6 4"   # 全局固定和弦进行(I-V-vi-IV)
  python autowav.py --random --motif-seed "0 2 4 2:2 0"      # 显式主题动机(音阶内0起算索引:拍)
  python autowav.py --random --motif            # 自动生成一次主题并跨段复现变奏
  python autowav.py --random --chord-progression "I-vi-IV-V" --motif  # 和声+主题双固定
  python autowav.py --backend acestep ...  # 可选神经后端（需显卡+依赖，否则降级）
  python autowav.py --batch N              # 批量生成 N 首
  python autowav.py --batch N --rank       # 批量生成并自动评分排序
  python autowav.py --batch N --rank --bars M   # 批量（每首 M 小节）并评分排序
  python autowav.py -h                     # 显示帮助

功能特性:
  - 输出到脚本目录下的 output 文件夹，以系统时间命名
  - 14 种调式、12 种音色（含 Karplus-Strong / FM 合成）
  - 5 种效果器（混响 / 合唱 / 延迟 / 压缩 / 低通滤波）
  - 张力曲线叙事结构、动态压缩、GZIP 压缩
  - 支持低音声部、琶音轨、鼓点节奏
  - 多声部对位、柱式和弦织体、曲式结构（ABA/AABA/ABAC）
  - 旋律主题 Motif 复用与变奏
  - 纯标准库、零外部依赖；可选神经后端为懒加载旁路

生成文件为 .wav / .wav.gz / .mid 格式。无需任何外部依赖。
        """)

    elif parsed["mode"] == "random":
        # 选择后端（默认 symbolic 即原引擎；其他后端缺失时优雅降级）
        try:
            backend = get_backend(parsed["backend"])
        except ValueError:
            print(f"✗ 未知后端 '{parsed['backend']}'。可用: {available_backends()}")
            sys.exit(1)

        # 组装生成 spec（与 generate_music 兼容），两条路径统一走 backend.generate
        spec = {}
        if parsed["bpm"]:
            spec["bpm"] = parsed["bpm"]
        if parsed["bars"]:
            spec["n_bars"] = parsed["bars"]
        if parsed["output_dir"]:
            os.makedirs(parsed["output_dir"], exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            spec["output_path"] = os.path.join(parsed["output_dir"], f"music_{ts}.wav")
        if parsed["export_midi"]:
            spec["export_midi"] = True
        if parsed["midi_out"]:
            spec["midi_path"] = parsed["midi_out"]
        if parsed["import_midi"]:
            spec["import_midi_path"] = parsed["import_midi"]
        if parsed["chord_progression"]:
            spec["chord_progression"] = parsed["chord_progression"]
        if parsed["motif_seed"] is not None:
            spec["motif_seed"] = parsed["motif_seed"]

        if parsed["duration"]:
            # 时长 → 小节数（交给后端按各自方式生成约 N 秒）
            bpm = parsed["bpm"] or random.randint(70, 160)
            beat_dur = 60.0 / bpm
            bars_needed = int(parsed["duration"] / (4 * beat_dur)) + 1
            spec["n_bars"] = bars_needed
            print(f"  目标时长: {parsed['duration']} 秒（约 {bars_needed} 小节）")

        try:
            path, params = backend.generate(spec)
        except (RuntimeError, NotImplementedError) as e:
            print(f"✗ 后端 '{parsed['backend']}' 不可用: {e}")
            sys.exit(1)

        if parsed["compress"]:
            print("  应用 GZIP 压缩…")
            path = save_gzip_wav(path)

        print(f"  文件路径: {os.path.abspath(path)}")

    elif parsed["mode"] == "batch":
        if parsed["backend"] != "symbolic":
            print(f"  注: 批量模式使用 symbolic 引擎（'{parsed['backend']}' 未实现/不可用）。")
        batch_mode(parsed["batch_count"], rank=parsed["rank"], bars=parsed.get("bars"),
                   chord_progression=parsed.get("chord_progression"),
                   motif_seed=parsed.get("motif_seed"))

    else:
        try:
            interactive_mode()
        except KeyboardInterrupt:
            print("\n\n  已取消。")
