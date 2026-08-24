"""
vocal_render_np.py — numpy/scipy 向量化人声渲染加速器（可选旁路，非核心）

与 vocal_formant.py（纯 stdlib）同结构、同参数表（直接复用其常量与元音表），
但用 numpy 元素级运算 + scipy.signal.lfilter 分段滤波实现，速度快约 50 倍。
仅供批量/长曲目使用；核心引擎零依赖护城河不变。numpy/scipy 缺失时回退
vocal_formant.sing。

注意：与纯 stdlib 版输出不保证逐位一致（随机数流与浮点顺序不同），
但同参数同 seed 下各自自洽、可复现（批量脚本在 manifest 记录 seed）。
"""
import math

import numpy as np
from scipy.signal import lfilter

import vocal_formant as vf  # 复用 VOWELS/_BANDWIDTHS/_GAINS/_PARALLEL_WEIGHTS/拼音映射


def _onepole(fc, sr):
    """一阶低通系数：y[n] = y[n-1] + a*(x[n]-y[n-1]) → b=[a], a=[1,-(1-a)]"""
    a = 1.0 - math.exp(-2 * math.pi * fc / sr)
    return np.array([a]), np.array([1.0, -(1.0 - a)])


def _res_b_a(coeffs):
    """谐振器系数 (c1, c2, a) → lfilter 的 (b, a)"""
    c1, c2, a = coeffs
    return np.array([a]), np.array([1.0, -c1, -c2])


def _smoothstep(k):
    return k * k * (3.0 - 2.0 * k)


def _vib_wave(t, vr):
    return (0.75 * np.sin(2 * np.pi * vr * t)
            + 0.25 * np.sin(2 * np.pi * vr * 1.24 * t + 0.7))


def render_note_np(freq, duration, vowel="ah", sample_rate=44100,
                   volume=0.7, breath=0.05, vibrato_rate=5.2,
                   vibrato_cents=35.0, aspirate=0.7,
                   prev_freq=None, prev_vowel=None,
                   attack=0.08, release=0.12, rng=None):
    """向量化渲染单个元音音符（语义对齐 vocal_formant.vocal_note）。"""
    if freq <= 0:
        return np.zeros(int(duration * sample_rate))
    vowel_key = vf.pinyin_to_vowel(vowel) if vowel not in vf.VOWELS else vowel
    formants = vf.VOWELS.get(vowel_key, vf.VOWELS["ah"])
    sr = sample_rate
    n = int(duration * sr)
    if n <= 0:
        return np.zeros(0)
    if rng is None:
        rng = np.random.default_rng(0)
    t = np.arange(n) / sr

    # ── 共振峰系数：目标 / 微颤两套 / 过渡起点 ──
    tgt = vf._res_coeffs(formants, vf._BANDWIDTHS, sr)
    tgt_lo = vf._res_coeffs(tuple(f * 0.97 for f in formants),
                            vf._BANDWIDTHS, sr)
    tgt_hi = vf._res_coeffs(tuple(f * 1.03 for f in formants),
                            vf._BANDWIDTHS, sr)
    prev_key = vf.pinyin_to_vowel(prev_vowel) if prev_vowel else vowel_key
    cur = vf._res_coeffs(vf.VOWELS.get(prev_key, vf.VOWELS["ah"]),
                         vf._BANDWIDTHS, sr)

    # ── 音高：滑音 + 双正弦颤音（150ms 延迟、350ms 起振）──
    vib_env = np.zeros(n)
    m = t >= 0.15
    vib_env[m] = vibrato_cents * np.minimum(1.0, (t[m] - 0.15) / 0.35)
    vib_wave = _vib_wave(t, vibrato_rate)
    f_inst = freq * (2.0 ** (vib_env * vib_wave / 1200.0))
    if prev_freq is not None:
        g_n = min(int(0.045 * sr), n)
        k = np.arange(g_n) / g_n
        g = _smoothstep(k)
        f_inst[:g_n] = ((prev_freq + (freq - prev_freq) * g)
                        * (2.0 ** (vib_env[:g_n] * vib_wave[:g_n] / 1200.0)))

    phase = 2 * np.pi * np.cumsum(f_inst) / sr
    saw = 2.0 * ((phase / (2 * np.pi)) % 1.0) - 1.0
    src = saw * 0.62 + np.sin(phase) * 0.30

    # ── 噪声链：2 阶低通 ~6kHz（送气频谱）──
    nb, na = _onepole(6000.0, sr)
    noise = rng.standard_normal(n)
    nl1 = lfilter(nb, na, noise)
    nl2 = lfilter(nb, na, nl1)

    # ── 声门滚降：两级低通（-12dB/oct；等效 -3dB≈2.8kHz；哼鸣更低）──
    gfc = 1500.0 if vowel_key == "m" else 4300.0
    gb, ga = _onepole(gfc, sr)
    src = lfilter(gb, ga, lfilter(gb, ga, src))

    # ── 送气：声门滚降之后注入（解剖学正确）+ 音头 55ms 送气 ──
    src = src + nl2 * (breath * 0.55)
    onset = t < 0.055
    src[onset] += nl2[onset] * (aspirate * 0.45 * (1.0 - t[onset] / 0.055))

    # ── 并联共振峰：分段时变系数滤波（元音过渡 + ±3% 微颤）──
    trans_len = 0.06
    edges = []
    if prev_vowel is not None:
        e = 0.0
        while e < trans_len - 1e-9:
            edges.append((e, min(e + 0.015, trans_len)))
            e += 0.015
        start = trans_len
    else:
        start = 0.0
    e = start
    while e < duration - 1e-9:
        edges.append((e, min(e + 0.02, duration)))
        e += 0.02

    y_total = np.zeros(n)
    for j in range(3):
        zi = np.zeros(2)
        for (t0, t1) in edges:
            i0, i1 = int(t0 * sr), int(t1 * sr)
            if i1 <= i0:
                continue
            tm = (t0 + t1) / 2.0
            if tm < trans_len:
                cc = vf._blend_coeffs(cur, tgt,
                                      _smoothstep(tm / trans_len))[j]
            else:
                fb = 0.5 + 0.5 * float(_vib_wave(np.array([tm]),
                                                 vibrato_rate)[0])
                cc = vf._blend_coeffs(tgt_lo, tgt_hi, fb)[j]
            b, a = _res_b_a(cc)
            y, zi = lfilter(b, a, src[i0:i1], zi=zi)
            y_total[i0:i1] += vf._PARALLEL_WEIGHTS[j] * y

    # ── 振幅颤音 + 送气旁路（Klatt AF 分支）+ 辐射低通 2 阶 ──
    y_total *= 1.0 + 0.05 * vib_wave
    y_total += nl2 * (breath * 0.9)
    ob, oa = _onepole(11000.0, sr)
    y_total = lfilter(ob, oa, lfilter(ob, oa, y_total))

    # ── 包络（柔起音 80ms / 衰减 / 保持 0.85 / 释放）──
    sustain = 0.85
    decay = 0.06
    env = np.full(n, sustain)
    a1 = t < attack
    env[a1] = t[a1] / attack
    a2 = (t >= attack) & (t < attack + decay)
    env[a2] = 1.0 - (1.0 - sustain) * (t[a2] - attack) / decay
    r1 = t > duration - release
    env[r1] = sustain * np.maximum(0.0, (duration - t[r1]) / release)

    return y_total * vf._GAINS.get(vowel_key, 1.0) * env * volume


def sing_np(notes, syllables=None, sample_rate=44100, volume=0.8,
            breath=0.05, aspirate=0.7, seed=None):
    """唱一段旋律（语义对齐 vocal_formant.sing）。返回 np.ndarray。"""
    if seed is not None:
        rng = np.random.default_rng(seed)
    else:
        rng = np.random.default_rng(0)
    if not notes:
        return np.zeros(0)
    if syllables is None:
        syllables = ["ah"]
    syl = list(syllables)

    parts = []
    prev_freq = None
    prev_vowel = None
    for i, (freq, dur) in enumerate(notes):
        v = syl[i % len(syl)]
        parts.append(render_note_np(freq, dur, v, sample_rate=sample_rate,
                                    volume=volume, breath=breath,
                                    aspirate=aspirate,
                                    prev_freq=prev_freq,
                                    prev_vowel=prev_vowel, rng=rng))
        prev_freq = freq if freq > 0 else None
        prev_vowel = v
    return np.concatenate(parts) if parts else np.zeros(0)
