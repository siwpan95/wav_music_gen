"""
vocal_formant.py — 人声共振峰合成模块（纯标准库，零外部依赖）

原理：Klatt 声源-滤波（Source-Filter）理论。
  声带声源（锯齿波近似声门脉冲 + 轻微呼吸噪声）
    → 声道谐振器（F1/F2/F3 并联二阶共振峰滤波，加权求和）
    → 元音音色。叠加颤音、滑音、元音间平滑过渡。

质量定位（诚实边界）：
  ★ 能：元音吟唱 / 哼鸣（vocalise）——「啊/哦/衣」式人声音色，可唱任意旋律，
        音色接近合唱团"啊"声或口哨式哼唱，完全本地、确定性、零版权风险。
  ✗ 不能：辅音与可懂歌词（那是神经歌声合成 SVS 的领域，见 VOICE_SYNTH_RESEARCH_2026.md）。

用法：
  import vocal_formant as vf
  samples = vf.sing([(440.0, 0.5), (523.25, 0.5)], ["a", "i"], sample_rate=44100)
"""

import math
import random

# ── 元音共振峰表：(F1, F2, F3) Hz —— 汉语主要元音近似值 ──
VOWELS = {
    "a":  (800, 1200, 2600),   # 啊
    "o":  (500,  850, 2400),   # 哦
    "e":  (550, 1800, 2500),   # 呃 / 鹅
    "i":  (300, 2300, 3000),   # 衣
    "u":  (350,  700, 2200),   # 乌
    "v":  (300, 2000, 2500),   # 吁 (ü)
    "ah": (750, 1100, 2450),   # 合唱"啊"（中性化，适合长音）
    "m":  (300, 1400, 2400),   # 闭口哼鸣
}

# 并联式共振峰的相对权重：补偿声门滚降，F2/F3 需更强才能形成清晰元音峰
_PARALLEL_WEIGHTS = (0.9, 1.2, 1.5)

# 响度补偿（并联结构下各元音峰值差异小，微调即可）
# 响度补偿（实测校准：各元音在 440Hz 下峰值对齐 ≈0.35 @vol 0.85）
_GAINS = {"a": 0.87, "o": 0.31, "e": 1.19, "i": 1.21, "u": 0.78,
          "v": 1.27, "ah": 1.29, "m": 1.51}

# 共振峰带宽 Hz（收紧带宽 → 元音更清晰；低峰窄、高峰宽）
_BANDWIDTHS = (60.0, 90.0, 140.0)

# ── 拼音韵母 → 韵腹元音（简化映射，吟唱够用）──
_FINAL_TO_VOWEL = {
    "a": "a", "ai": "a", "ao": "a", "an": "a", "ang": "a",
    "o": "o", "ou": "o", "ong": "o",
    "e": "e", "ei": "e", "en": "e", "eng": "e", "er": "e", "ê": "e",
    "i": "i", "ia": "a", "ie": "e", "iao": "a", "iu": "u",
    "ian": "e", "iang": "a", "in": "i", "ing": "i", "iong": "o",
    "u": "u", "ua": "a", "uo": "o", "uai": "a", "ui": "e",
    "uan": "a", "uang": "a", "un": "u", "ueng": "e",
    "v": "v", "ü": "v", "ve": "e", "vn": "v", "van": "a",
    # 整体认读音节 / 儿化
    "zh": "e", "ch": "e", "sh": "e", "r": "e",
    "z": "i", "c": "i", "s": "i", "n": "e", "ng": "e",
}


def pinyin_to_vowel(pinyin: str) -> str:
    """拼音音节 → 韵腹元音。容忍声调数字与大小写。"""
    s = pinyin.strip().lower().rstrip("0123456789")
    if s in VOWELS:
        return s
    for final in sorted(_FINAL_TO_VOWEL, key=len, reverse=True):
        if s.endswith(final):
            return _FINAL_TO_VOWEL[final]
    return "a"


def _res_coeffs(formants, bandwidths, sample_rate):
    """预计算谐振器系数（并联式共振峰，Klatt parallel）。
    每个谐振器：
        y[n] = a * x[n] + c1 * y[n-1] + c2 * y[n-2]
        R = exp(-pi*bw/sr), theta = 2pi*f/sr
        c1 = 2R cos(theta), c2 = -R^2, a = 1 - R   （峰值增益 ≈ 1）
    返回 [(c1, c2, a), ...] × 3 个共振峰。"""
    coeffs = []
    for f, bw in zip(formants, bandwidths):
        r = math.exp(-math.pi * bw / sample_rate)
        theta = 2 * math.pi * f / sample_rate
        coeffs.append((2 * r * math.cos(theta), -(r * r), 1 - r))
    return coeffs


def _blend_coeffs(c1_list, c2_list, k):
    """两组系数间线性插值（元音过渡用）。"""
    out = []
    for (c1a, c2a, aa), (c1b, c2b, ab) in zip(c1_list, c2_list):
        out.append((c1a + (c1b - c1a) * k, c2a + (c2b - c2a) * k,
                    aa + (ab - aa) * k))
    return out


def vocal_note(freq: float, duration: float, vowel: str = "ah",
               sample_rate: int = 44100, volume: float = 0.7,
               breath: float = 0.06, vibrato_rate: float = 5.2,
               vibrato_cents: float = 35.0, aspirate: float = 0.7,
               prev_freq: float = None, prev_vowel: str = None,
               attack: float = 0.08, release: float = 0.12) -> list:
    """渲染单个"元音音符"。返回 float 样本列表。

    freq: 音高 Hz；vowel: VOWELS 键或拼音；breath: 呼吸噪声比例 0-1；
    vibrato_cents: 颤音深度（音分，±）；aspirate: 起音送气强度 0-1（"h"式起音）；
    prev_freq/prev_vowel: 用于滑音与元音平滑过渡。
    """
    if freq <= 0:
        return [0.0] * int(duration * sample_rate)
    vowel_key = pinyin_to_vowel(vowel) if vowel not in VOWELS else vowel
    formants = VOWELS.get(vowel_key, VOWELS["ah"])
    n = int(duration * sample_rate)
    if n <= 0:
        return []

    tgt = _res_coeffs(formants, _BANDWIDTHS, sample_rate)
    # 共振峰微颤：±3% 两套系数，随颤音波形交叉渐变（声道随演唱微微形变）
    tgt_lo = _res_coeffs(tuple(f * 0.97 for f in formants),
                         _BANDWIDTHS, sample_rate)
    tgt_hi = _res_coeffs(tuple(f * 1.03 for f in formants),
                         _BANDWIDTHS, sample_rate)
    prev_key = pinyin_to_vowel(prev_vowel) if prev_vowel else vowel_key
    cur = _res_coeffs(VOWELS.get(prev_key, VOWELS["ah"]),
                      _BANDWIDTHS, sample_rate)

    trans_n = int(0.06 * sample_rate)          # 元音过渡 60ms
    glide_n = int(0.045 * sample_rate)         # 滑音 45ms
    vib_delay = 0.15                           # 颤音延迟起振
    vib_ramp = 0.35
    gain = _GAINS.get(vowel_key, 1.6)
    sustain = 0.85
    decay = 0.06

    # ── 声门滚降：两级低通级联 = -12dB/oct（近似真实声门频谱滚降）──
    # 注意：两级相同一阶级联后 -3dB 点下移为 fc×0.644，故取 4300 使等效≈2.8kHz
    # 哼鸣（m）：更低，只留鼻腔共鸣的低频"嗡嗡"感
    rolloff_fc = 1500.0 if vowel_key == "m" else 4300.0
    lp_a = 1.0 - math.exp(-2 * math.pi * rolloff_fc / sample_rate)

    # 送气噪声专用 2 阶低通（~6kHz）：真实送气频谱在 3-5kHz 有能量，提供"空气感"
    noise_a = 1.0 - math.exp(-2 * math.pi * 6000.0 / sample_rate)
    # 输出辐射低通 2 阶：等效 -3dB ≈ 7kHz，只砍 8k 以上合成残留、保留清晰度带
    out_a = 1.0 - math.exp(-2 * math.pi * 11000.0 / sample_rate)

    state = [[0.0, 0.0] for _ in range(3)]     # 每个谐振器 (y[n-1], y[n-2])
    phase = 0.0
    glot1 = 0.0                                # 声门低通第 1 级
    glot2 = 0.0                                # 声门低通第 2 级
    nl1 = 0.0                                  # 噪声低通第 1 级
    nl2 = 0.0                                  # 噪声低通第 2 级
    out_lp1 = 0.0                              # 输出辐射低通第 1 级
    out_lp2 = 0.0                              # 输出辐射低通第 2 级
    rnd = random.random
    out = [0.0] * n

    for i in range(n):
        t = i / sample_rate

        # ── 音高：滑音 + 颤音（双正弦叠加，模拟不规则的自然颤音）──
        base = freq
        if prev_freq is not None and i < glide_n:
            k = i / glide_n
            k = k * k * (3 - 2 * k)            # smoothstep
            base = prev_freq + (freq - prev_freq) * k
        vib_amp = vibrato_cents
        if t < vib_delay:
            vib_amp = 0.0
        elif t < vib_delay + vib_ramp:
            vib_amp *= (t - vib_delay) / vib_ramp
        vib_wave = (0.75 * math.sin(2 * math.pi * vibrato_rate * t)
                    + 0.25 * math.sin(2 * math.pi * vibrato_rate * 1.24 * t
                                      + 0.7))
        f_inst = base * (2.0 ** (vib_amp / 1200.0 * vib_wave))

        phase += 2 * math.pi * f_inst / sample_rate
        if phase > 4 * math.pi:
            phase -= 4 * math.pi

        # ── 声门声源：锯齿（声门脉冲近似）──
        saw = 2.0 * ((phase / (2 * math.pi)) % 1.0) - 1.0
        src = saw * 0.62 + math.sin(phase) * 0.30

        # 噪声链先备好（2 阶低通，模拟送气频谱）；在声门滚降之后注入
        noise = rnd() * 2 - 1
        nl1 += noise_a * (noise - nl1)
        nl2 += noise_a * (nl1 - nl2)

        # ── 声门滚降：两级一阶低通级联（-12dB/oct，去齿音、增人声感）──
        glot1 += lp_a * (src - glot1)
        glot2 += lp_a * (glot1 - glot2)
        src = glot2

        # 呼吸噪声（持续气声）+ 送气起音：注入点在声门滚降之后——
        # 解剖学正确：送气产生于声门上方，不经声带滚降，保留 4-6kHz 的"空气感"
        src += nl2 * breath * 0.55
        if t < 0.055:
            src += nl2 * aspirate * 0.45 * (1.0 - t / 0.055)

        # ── 共振峰系数（过渡期平滑插值；稳定期随颤音做 ±3% 微颤）──
        if i < trans_n:
            k = i / trans_n
            coeffs = _blend_coeffs(cur, tgt, k * k * (3 - 2 * k))
        else:
            fb = 0.5 + 0.5 * vib_wave
            coeffs = _blend_coeffs(tgt_lo, tgt_hi, fb)

        # ── 并联式共振峰滤波（三支路加权求和）──
        y_total = 0.0
        for j in range(3):
            c1, c2, a = coeffs[j]
            y = a * src + c1 * state[j][0] + c2 * state[j][1]
            state[j][1] = state[j][0]
            state[j][0] = y
            y_total += _PARALLEL_WEIGHTS[j] * y

        # ── 包络（柔起音如"h"式送气）──
        env = 1.0
        if t < attack:
            env = t / attack
        elif t < attack + decay:
            env = 1.0 - (1.0 - sustain) * (t - attack) / decay
        elif t > duration - release:
            env = sustain * max(0.0, (duration - t) / release)
        else:
            env = sustain

        # ── 振幅颤音（与音高颤音同源联动，±5%，自然演唱的微颤感）──
        y_total *= 1.0 + 0.05 * vib_wave

        # ── 送气旁路（Klatt parallel AF 分支）：少量噪声直通输出，
        #    绕过谐振器的 a=1-R 衰减，提供 4-8kHz 的自然"空气感" ──
        y_total += nl2 * breath * 0.9

        # ── 输出辐射低通 2 阶：砍掉 8kHz 以上合成残留 ──
        out_lp1 += out_a * (y_total - out_lp1)
        out_lp2 += out_a * (out_lp1 - out_lp2)

        out[i] = out_lp2 * gain * env * volume

    return out


def sing(notes: list, syllables=None, sample_rate: int = 44100,
         volume: float = 0.8, breath: float = 0.05, aspirate: float = 0.7,
         seed=None) -> list:
    """唱一段旋律。notes: [(freq_hz, dur_sec), ...]；
    syllables: 元音或拼音序列（不足时循环），None 时全部用 "ah"。
    freq<=0 的音符视为换气静默：不滑音、下一音符干净起音。
    相邻音符自动滑音 + 元音平滑过渡。返回 float 样本列表。"""
    if seed is not None:
        random.seed(seed)
    if not notes:
        return []
    if syllables is None:
        syllables = ["ah"]
    syl = list(syllables)

    track = []
    prev_freq = None
    prev_vowel = None
    for i, (freq, dur) in enumerate(notes):
        v = syl[i % len(syl)]
        track.extend(vocal_note(freq, dur, v, sample_rate=sample_rate,
                                volume=volume, breath=breath,
                                aspirate=aspirate,
                                prev_freq=prev_freq, prev_vowel=prev_vowel))
        if freq <= 0:
            prev_freq = None          # 换气：重置滑音，下一音干净起音
        else:
            prev_freq = freq
        prev_vowel = v
    return track


if __name__ == "__main__":
    # 自测：C 大调音阶吟唱「a e i o u」
    import os
    import sys
    import wave
    import struct

    _DIR = os.path.dirname(os.path.abspath(__file__))
    if _DIR not in sys.path:
        sys.path.insert(0, _DIR)

    SR = 44100
    scale = [261.63, 293.66, 329.63, 349.23, 392.00,
             440.00, 493.88, 523.25]
    notes = [(f, 0.55) for f in scale]
    syl = ["a", "e", "i", "o", "u", "a", "o", "u"]
    track = sing(notes, syl, sample_rate=SR)
    out_path = os.path.join(_DIR, "output", "vocal_selftest.wav")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with wave.open(out_path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        for s in track:
            v = max(-1.0, min(1.0, s))
            wf.writeframes(struct.pack("<h", int(v * 32767)))
    print(f"[vocal_formant] 自测完成: {out_path} "
          f"({len(track) / SR:.2f}s, {len(track)} samples)")
