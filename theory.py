"""
音乐理论模块：音阶、和弦、音名、频率表、张力曲线
纯 Python 标准库，零外部依赖
"""

import random

# ── 音符名称 ──
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_freq(name: str, octave: int) -> float:
    """根据音名和八度返回频率 (A4 = 440 Hz)"""
    semitone = NOTE_NAMES.index(name)
    midi = (octave + 1) * 12 + semitone
    return 440.0 * (2 ** ((midi - 69) / 12))


# ── 音阶定义（相对主音的半音偏移）──
SCALES = {
    "大调":         [0, 2, 4, 5, 7, 9, 11],
    "自然小调":     [0, 2, 3, 5, 7, 8, 10],
    "和声小调":     [0, 2, 3, 5, 7, 8, 11],
    "旋律小调":     [0, 2, 3, 5, 7, 9, 11],
    "五声大调":     [0, 2, 4, 7, 9],
    "五声小调":     [0, 3, 5, 7, 10],
    "布鲁斯":       [0, 3, 5, 6, 7, 10],
    "多利安":       [0, 2, 3, 5, 7, 9, 10],
    "弗里吉亚":     [0, 1, 3, 5, 7, 8, 10],
    "利底亚":       [0, 2, 4, 6, 7, 9, 11],
    "混合利底亚":   [0, 2, 4, 5, 7, 9, 10],
    "全音阶":       [0, 2, 4, 6, 8, 10],
    "半减七":       [0, 2, 3, 5, 6, 8, 10],
    "比波普属七":   [0, 2, 4, 5, 7, 8, 9, 10, 11],
}

# ── 和弦进行（级数）──
CHORD_PROGRESSIONS = [
    [1, 5, 6, 4],                              # I-V-vi-IV
    [1, 4, 5, 1],                              # I-IV-V-I
    [1, 6, 4, 5],                              # I-vi-IV-V
    [1, 3, 4, 5],                              # I-iii-IV-V
    [6, 4, 1, 5],                              # vi-IV-I-V
    [1, 5, 6, 3, 4, 1, 4, 5],                 # 流行扩展
    [2, 5, 1, 6],                              # ii-V-I-vi
    [2, 5, 3, 6],                              # ii-V-iii-vi
    [1, 7, 3, 6],                              # I-vii-iii-vi
    [6, 2, 5, 1],                              # vi-ii-V-I
    [1, 4, 5, 4],                              # I-IV-V-IV
    [1, 6, 2, 4],                              # I-vi-ii-IV
    [8, 5, 6, 4],                              # bVI-bIII-bVI-IV
]


def build_scale_notes(root_name: str, root_octave: int,
                      scale_intervals: list) -> list:
    """构建音阶中所有音符的频率列表（跨两个八度）"""
    root_semitone = NOTE_NAMES.index(root_name) + (root_octave + 1) * 12
    notes = []
    for octave_offset in [0, 12]:
        for interval in scale_intervals:
            midi = root_semitone + interval + octave_offset
            freq = 440.0 * (2 ** ((midi - 69) / 12))
            notes.append(freq)
    return notes


def compute_tension_curve(n_bars: int) -> list:
    """
    生成叙事型张力曲线：开头低 → 渐升 → 高潮 → 回落 → 收尾
    返回每小节的张力值 [0-1]
    """
    curve = []
    for bar in range(n_bars):
        pos = bar / max(n_bars - 1, 1)
        if pos < 0.6:
            tension = (pos / 0.6) ** 1.5 * 0.9
        else:
            tension = (1 - (pos - 0.6) / 0.4) * 0.9
        tension += random.uniform(-0.06, 0.06)
        curve.append(max(0.1, min(1.0, tension)))
    return curve
