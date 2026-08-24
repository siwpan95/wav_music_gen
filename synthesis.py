"""
波形合成模块：基础波形、Karplus-Strong、FM合成、ADSR包络、音符渲染
纯 Python 标准库，零外部依赖
"""

import math
import random

# ── 基础波形 ──

def sine_wave(freq: float, t: float) -> float:
    return math.sin(2 * math.pi * freq * t)


def square_wave(freq: float, t: float, duty: float = 0.5) -> float:
    """方波（带占空比）"""
    phase = (freq * t) % 1.0
    return 1.0 if phase < duty else -1.0


def sawtooth_wave(freq: float, t: float) -> float:
    """锯齿波"""
    return 2.0 * ((freq * t) % 1.0) - 1.0


def triangle_wave(freq: float, t: float) -> float:
    """三角波"""
    p = (freq * t) % 1.0
    return 4.0 * p - 1.0 if p < 0.5 else 3.0 - 4.0 * p


def organ_wave(freq: float, t: float) -> float:
    """管风琴音色（4次谐波叠加）"""
    return (
        sine_wave(freq, t) * 0.5
        + sine_wave(freq * 2, t) * 0.3
        + sine_wave(freq * 3, t) * 0.15
        + sine_wave(freq * 4, t) * 0.05
    )


def piano_wave(freq: float, t: float, duration: float) -> float:
    """模拟钢琴：谐波 + 指数衰减包络"""
    harmonics = (
        sine_wave(freq, t) * 1.0
        + sine_wave(freq * 2, t) * 0.5
        + sine_wave(freq * 3, t) * 0.25
        + sine_wave(freq * 4, t) * 0.1
        + sine_wave(freq * 5, t) * 0.05
    )
    decay = math.exp(-t * 4.0 / max(duration, 0.01))
    return harmonics * decay


# ── Karplus-Strong 物理建模拨弦 ──

def karplus_strong_note(freq: float, duration: float, sample_rate: int,
                        volume: float = 0.8, decay: float = 0.996) -> list:
    """Karplus-Strong 拨弦合成，返回完整样本列表"""
    n = max(int(sample_rate / freq), 2)
    buf = [random.uniform(-1, 1) for _ in range(n)]
    n_samples = int(duration * sample_rate)
    result = [0.0] * n_samples
    for i in range(n_samples):
        result[i] = buf[0]
        avg = (buf[0] + buf[1]) / 2.0
        buf.pop(0)
        buf.append(avg * decay)
    return [s * volume for s in result]


# ── FM 频率调制合成 ──

def fm_wave(freq: float, t: float, mod_ratio: float = 2.0,
            mod_index: float = 3.0, mod_fb: float = 0.0) -> float:
    """FM 双算子合成"""
    mod_phase = 2 * math.pi * freq * mod_ratio * t
    mod = math.sin(mod_phase + mod_fb * math.sin(mod_phase))
    return math.sin(2 * math.pi * freq * t + mod_index * mod)


# ── 音色列表 ──

TIMBRES = ["钢琴", "管风琴", "正弦波", "方波", "三角波", "锯齿波",
           "吉他", "竖琴", "贝斯",          # Karplus-Strong
           "电钢琴", "铃声", "铜管"]        # FM 合成


# ── ADSR 包络 ──

def adsr_envelope(note_t: float, duration: float,
                  attack=0.02, decay=0.05, sustain=0.7, release=0.08) -> float:
    """标准 ADSR 包络，自动适应极短音符"""
    if duration <= 0:
        return 0.0
    effective_attack = min(attack, duration * 0.3)
    effective_decay = min(decay, duration * 0.2)
    effective_release = min(release, duration * 0.4)

    if note_t < effective_attack:
        return note_t / max(effective_attack, 0.001)
    elif note_t < effective_attack + effective_decay:
        return 1.0 - (1.0 - sustain) * (note_t - effective_attack) / max(effective_decay, 0.001)
    elif note_t < duration - effective_release:
        return sustain
    elif note_t < duration:
        return sustain * (1.0 - (note_t - (duration - effective_release)) / max(effective_release, 0.001))
    return 0.0


# ── 音符渲染 ──

def render_note(freq: float, duration: float, sample_rate: int,
                timbre: str, volume: float = 0.8,
                tension: float = 0.5) -> list:
    """渲染单个音符为样本列表
    tension: 0-1 张力值，影响音量和音色参数"""
    if freq <= 0:
        return [0.0] * int(duration * sample_rate)
    # Karplus-Strong 系列需要整体生成
    if timbre == "吉他":
        return karplus_strong_note(freq, duration, sample_rate,
                                   volume * (0.7 + tension * 0.3), decay=0.996)
    if timbre == "竖琴":
        return karplus_strong_note(freq, duration, sample_rate,
                                   volume * 0.65, decay=0.992)
    if timbre == "贝斯":
        return karplus_strong_note(freq, duration, sample_rate,
                                   volume * 0.8, decay=0.994)

    n_samples = int(duration * sample_rate)
    samples = []

    # FM 参数表
    fm_params = {
        "电钢琴": (1.0, 1.0 + tension * 4.0, volume * 0.7),
        "铃声":   (3.5, 2.0 + tension * 3.0, volume * 0.5),
        "铜管":   (1.0, 0.5 + tension * 5.0, volume * 0.65),
    }
    mod_ratio, mod_index, fm_vol = fm_params.get(timbre, (0, 0, 0))

    for i in range(n_samples):
        note_t = i / sample_rate

        if freq <= 0:
            samples.append(0.0)
            continue

        if timbre == "钢琴":
            raw = piano_wave(freq, note_t, duration)
        elif timbre == "管风琴":
            raw = organ_wave(freq, note_t)
        elif timbre == "方波":
            raw = square_wave(freq, note_t, duty=random.uniform(0.4, 0.6))
        elif timbre == "三角波":
            raw = triangle_wave(freq, note_t)
        elif timbre == "锯齿波":
            raw = sawtooth_wave(freq, note_t)
        elif timbre in fm_params:
            raw = fm_wave(freq, note_t, mod_ratio=mod_ratio, mod_index=mod_index)
        else:
            raw = sine_wave(freq, note_t)

        env = adsr_envelope(note_t, duration)
        vol = fm_vol if fm_vol else volume
        samples.append(raw * env * vol)

    return samples


def render_samples(samples_list: list, sample_rate: int,
                   timbre: str = "正弦波", volume: float = 0.5) -> list:
    """将 [(频率, 时长)] 序列渲染为 sample 列表"""
    result = []
    for freq, dur in samples_list:
        dur = min(dur, 5.0)
        n = int(dur * sample_rate)
        for i in range(n):
            t = i / sample_rate
            if freq <= 0:
                result.append(0.0)
                continue
            if timbre == "钢琴":
                result.append(piano_wave(freq, t, dur) * volume)
            elif timbre == "管风琴":
                result.append(organ_wave(freq, t) * volume)
            elif timbre == "方波":
                result.append(square_wave(freq, t) * volume)
            elif timbre == "锯齿波":
                result.append(sawtooth_wave(freq, t) * volume)
            elif timbre == "三角波":
                result.append(triangle_wave(freq, t) * volume)
            else:
                result.append(sine_wave(freq, t) * volume)
    return result
