"""
曲式结构模块：ABA、奏鸣曲式等
纯 Python 标准库，零外部依赖
"""

import random


# ── 曲式模板 ──

FORM_TEMPLATES = {
    "aba": {
        "sections": ["A", "B", "A'"],
        "ratios": [0.40, 0.35, 0.25],
        "describe": "A(呈示) → B(对比) → A'(再现)",
    },
    "abac": {
        "sections": ["A", "B", "A'", "Coda"],
        "ratios": [0.35, 0.30, 0.25, 0.10],
        "describe": "A(呈示) → B(对比) → A'(再现) → Coda(尾声)",
    },
    "aaba": {
        "sections": ["A", "A'", "B", "A''"],
        "ratios": [0.25, 0.25, 0.25, 0.25],
        "describe": "A(主题) → A'(变奏) → B(桥段) → A''(再现)",
    },
}


def build_form_structure(form_name: str, n_bars: int, chord_prog: list,
                         scale_intervals: list) -> dict:
    """根据曲式模板，将总小节数分配到各段。
    返回 dict: {
        "form_name": ...,
        "sections": [
            {"label": "A", "bar_start": 0, "bar_end": 8, "n_bars": 8,
             "chord_prog": [...], "tension_curve": [...]},
            ...
        ],
        "motif_sections": ["A", "A'"],  # 哪些段复用主题
    }
    """
    template = FORM_TEMPLATES.get(form_name, FORM_TEMPLATES["aba"])
    section_labels = template["sections"]
    ratios = template["ratios"]

    # 按比例分配小节数
    bar_counts = []
    remaining = n_bars
    for i, ratio in enumerate(ratios):
        if i == len(ratios) - 1:
            count = remaining
        else:
            count = max(2, round(n_bars * ratio))
        bar_counts.append(count)
        remaining -= count
    # 确保总数正确
    bar_counts[-1] = max(2, bar_counts[-1] + remaining)

    # 确定哪些段复用 motif（A 和 A' 类）
    motif_sections = [lab for lab in section_labels if lab.startswith("A")]

    sections = []
    bar_offset = 0

    for i, label in enumerate(section_labels):
        sec_bars = bar_counts[i]

        # 每段有独立的和弦进行和张力曲线
        if label.startswith("A"):
            # A 段：主调进行，中低张力 → 渐升
            sec_chord = list(chord_prog)  # 保持原进行
            sec_tension = _section_tension(sec_bars, profile="rise")
        elif label == "B":
            # B 段：对比调式，较高张力
            sec_chord = _shift_chord_prog(chord_prog)
            sec_tension = _section_tension(sec_bars, profile="peak")
        elif label == "Coda":
            # 尾声：简单进行，张力渐降 → 收束
            sec_chord = chord_prog[:2]  # 只用前两个和弦反复
            sec_tension = _section_tension(sec_bars, profile="fall")
        else:
            sec_chord = list(chord_prog)
            sec_tension = _section_tension(sec_bars, profile="neutral")

        sections.append({
            "label": label,
            "bar_start": bar_offset,
            "bar_end": bar_offset + sec_bars,
            "n_bars": sec_bars,
            "chord_prog": sec_chord,
            "tension_curve": sec_tension,
        })
        bar_offset += sec_bars

    return {
        "form_name": form_name,
        "description": template["describe"],
        "sections": sections,
        "motif_sections": motif_sections,
    }


def _section_tension(n_bars: int, profile: str = "neutral") -> list:
    """为曲式中某一段生成张力曲线。"""
    curve = []
    for bar in range(n_bars):
        pos = bar / max(n_bars - 1, 1)

        if profile == "rise":
            # A 段：渐升
            t = pos ** 1.2 * 0.7 + 0.1
        elif profile == "peak":
            # B 段：中高张力，波峰
            t = 0.5 + 0.4 * (1 - abs(pos * 2 - 1) ** 0.5)
        elif profile == "fall":
            # Coda：渐降
            t = (1 - pos) ** 1.5 * 0.7 + 0.05
        else:
            t = 0.4 + random.uniform(-0.1, 0.1)

        t += random.uniform(-0.04, 0.04)
        curve.append(max(0.05, min(1.0, t)))

    return curve


def _shift_chord_prog(chord_prog: list) -> list:
    """生成对比段的替代和弦进行（循环移位或反转）。"""
    if random.random() < 0.5:
        # 循环移位
        shift = random.randint(1, len(chord_prog) - 1)
        return chord_prog[shift:] + chord_prog[:shift]
    else:
        # 反转
        return list(reversed(chord_prog))
