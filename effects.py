"""
DSP 效果器模块：混响、合唱、延迟、低通滤波、动态压缩
纯 Python 标准库，零外部依赖
"""

import math


def apply_reverb(samples: list, sample_rate: int,
                 delay_ms: float = 80, decay: float = 0.3,
                 mix: float = 0.25) -> list:
    """简单反馈延迟混响"""
    delay_samples = int(delay_ms * sample_rate / 1000)
    out = list(samples)
    for i in range(delay_samples, len(out)):
        out[i] += out[i - delay_samples] * decay * mix
    return out


def apply_chorus(samples: list, sample_rate: int,
                 rate: float = 0.6, depth: float = 0.003,
                 mix: float = 0.3) -> list:
    """合唱效果器 — LFO 调制短延迟"""
    max_delay = int(depth * sample_rate) + 1
    out = list(samples)
    for i in range(len(out)):
        lfo = math.sin(2 * math.pi * rate * i / sample_rate)
        delay = int(max_delay * (1.0 + lfo * 0.5))
        delay = max(1, min(delay, max_delay))
        if i >= delay:
            out[i] = out[i] * (1 - mix) + out[i - delay] * mix
    return out


def apply_delay(samples: list, sample_rate: int,
                delay_time: float = 0.3, feedback: float = 0.4,
                mix: float = 0.3) -> list:
    """延迟效果器 — 带反馈的多拍回声"""
    delay_samples = int(delay_time * sample_rate)
    if delay_samples <= 0:
        return samples
    out = list(samples)
    for i in range(delay_samples, len(out)):
        out[i] += out[i - delay_samples] * feedback * mix
    return out


def low_pass_filter(samples: list, cutoff_ratio: float = 0.3) -> list:
    """一阶 IIR 低通滤波"""
    alpha = 1.0 - math.exp(-2 * math.pi * cutoff_ratio)
    out = []
    prev = 0.0
    for s in samples:
        prev = prev + alpha * (s - prev)
        out.append(prev)
    return out


def dynamic_compression(samples: list, threshold: float = 0.5,
                       ratio: float = 4.0, attack: float = 0.01,
                       release: float = 0.05,
                       sample_rate: int = 44100) -> list:
    """动态范围压缩器"""
    attack_samples = int(attack * sample_rate)
    release_samples = int(release * sample_rate)

    out = []
    gain_reduction = 0.0
    target_reduction = 0.0

    for s in samples:
        abs_s = abs(s)

        if abs_s > threshold:
            over = abs_s - threshold
            target_reduction = over * (1 - 1 / ratio)
        else:
            target_reduction = 0.0

        if target_reduction > gain_reduction:
            step = target_reduction / max(attack_samples, 1)
            gain_reduction = min(gain_reduction + step, target_reduction)
        else:
            step = gain_reduction / max(release_samples, 1)
            gain_reduction = max(gain_reduction - step, target_reduction)

        if gain_reduction > 0:
            out.append(s * (1.0 - gain_reduction))
        else:
            out.append(s)

    return out
