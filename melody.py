"""
旋律生成模块：旋律（二阶马尔可夫链）、低音、琶音、鼓点节奏
纯 Python 标准库，零外部依赖
"""

import math
import random


# ═══════════════════════════════════════════════
#  二阶马尔可夫链 — 转移评分
# ═══════════════════════════════════════════════

def _markov_score(candidate_idx: int,
                  prev2_idx: int,
                  prev1_idx: int,
                  scale_notes: list,
                  chord_degree: int,
                  tension: float,
                  downbeat: bool = False) -> float:
    """对候选音符评分（二阶上下文 + 和弦约束 + 张力）。
    评分越高 → 越可能被选中。"""

    n = len(scale_notes)
    scale_len = n // 2  # 每八度音符数
    if scale_len < 1:
        scale_len = n

    score = 1.0

    # ── 1. 相对 prev1 的音程偏好 ──
    step = abs(candidate_idx - prev1_idx)
    if step == 0:
        score *= 2.0
    elif step == 1:
        score *= 5.0          # 级进最优
    elif step == 2:
        score *= 3.0          # 小三度小跳
    elif step <= 4:
        score *= 1.2          # 中等跳进
    elif step <= 7:
        score *= 0.5
    else:
        score *= 0.08         # 大跳严重惩罚

    # ── 2. 方向连续性（二阶上下文核心）──
    d1 = candidate_idx - prev1_idx       # 本次方向
    d2 = prev1_idx - prev2_idx           # 上次方向
    if d1 * d2 > 0 and d1 != 0:
        score *= 1.6         # 同向延续：惯性奖赏
    elif d1 * d2 < 0:
        score *= 0.45        # 折返惩罚（避免 up-down-up 锯齿）
    # d1==0 或 d2==0 → 不加不减

    # ── 3. 和弦音倾向 ──
    chord_root = (chord_degree - 1) % scale_len if chord_degree > 0 else 0
    chord_tones = {
        chord_root,
        (chord_root + 2) % scale_len,
        (chord_root + 4) % scale_len,
    }
    cand_mod = candidate_idx % scale_len
    is_chord_tone = cand_mod in chord_tones

    if is_chord_tone:
        score *= 3.5 if downbeat else 2.8
    else:
        # 非和弦音：差拍上低惩罚，强拍上高惩罚
        score *= 0.55 if downbeat else 0.7

    # ── 4. 三连同音惩罚 ──
    if prev2_idx == prev1_idx == candidate_idx:
        score *= 0.01

    # ── 5. 导音解决 ──
    leading_tone = (chord_root + scale_len - 1) % scale_len
    prev1_mod = prev1_idx % scale_len
    if prev1_mod == leading_tone:
        tonic_mod = chord_root
        if cand_mod == tonic_mod and abs(d1) <= 2:
            score *= 6.0       # 强烈鼓励解决到主音
        elif abs(d1) > 3:
            score *= 0.2       # 导音后大跳 → 重罚

    # ── 6. 张力驱动的音区偏好 ──
    mid = n // 2
    if tension > 0.65:
        factor = 1.0 + (tension - 0.65) * 3.0
        if candidate_idx > mid:
            score *= factor
        else:
            score *= max(0.5, 1.0 - (tension - 0.65) * 1.5)
    elif tension < 0.3:
        weight = 1.0 + (0.3 - tension) * 2.0
        if candidate_idx < mid:
            score *= weight

    # ── 7. 边界软限制 ──
    margin = 2
    if candidate_idx < margin or candidate_idx >= n - margin:
        score *= 0.3

    return max(score, 1e-5)


def _sample_markov(prev2_idx: int, prev1_idx: int,
                   scale_notes: list, chord_degree: int,
                   tension: float, downbeat: bool = False) -> int:
    """从二阶马尔可夫分布采样下一音符索引。"""
    n = len(scale_notes)
    weights = [
        _markov_score(i, prev2_idx, prev1_idx, scale_notes,
                      chord_degree, tension, downbeat)
        for i in range(n)
    ]
    total = sum(weights)
    probs = [w / total for w in weights]
    return random.choices(range(n), weights=probs, k=1)[0]


# ═══════════════════════════════════════════════
#  旋律生成（二阶马尔可夫链）
# ═══════════════════════════════════════════════

def generate_melody(scale_notes: list, n_bars: int, bpm: int,
                    time_sig: int = 4, chord_prog: list = None,
                    tension_curve: list = None) -> list:
    """
    生成旋律序列，返回 [(频率, 时长秒), ...]
    二阶马尔可夫链 P(note | prev2, prev1, chord, tension)
    """
    beat_dur = 60.0 / bpm
    n = len(scale_notes)
    scale_len = n // 2 if n >= 2 else n

    # 节奏模式
    rhythms = [
        [1, 1, 1, 1],
        [0.5, 0.5, 1, 1, 1],
        [2, 1, 1],
        [0.5, 0.5, 0.5, 0.5, 1, 1],
        [1.5, 0.5, 1, 1],
        [0.25, 0.25, 0.5, 1, 1, 1],
        [1, 0.5, 0.5, 1, 1],
        [0.5, 1, 0.5, 1, 1],
        [1, 1, 0.5, 0.5, 1],
    ]

    if chord_prog is None:
        chord_prog = [1]
    if tension_curve is None:
        tension_curve = [0.5] * n_bars

    # ── 初始化二阶马尔可夫状态 ──
    first_chord = chord_prog[0]
    chord_root_0 = (first_chord - 1) % scale_len
    chord_tones_0 = {
        chord_root_0,
        (chord_root_0 + 2) % scale_len,
        (chord_root_0 + 4) % scale_len,
    }
    # 选取中音区种子
    seed_base = scale_len + random.randint(0, scale_len // 3)
    candidates_0 = [i for i in range(max(1, seed_base - 2), min(n - 1, seed_base + 3))
                    if (i % scale_len) in chord_tones_0]
    if not candidates_0:
        seed_base = max(1, min(n - 2, scale_len))
        candidates_0 = [seed_base, seed_base + 1]

    prev2 = seed_base
    prev1 = random.choice(candidates_0)

    melody: list = []
    bar_idx = 0

    for _ in range(n_bars):
        tension = tension_curve[min(bar_idx, len(tension_curve) - 1)]
        chord_degree = chord_prog[bar_idx % len(chord_prog)]

        rhythm = random.choice(rhythms)
        total_beats = sum(rhythm)
        rhythm = [r * time_sig / total_beats for r in rhythm]

        for r_pos, dur_beats in enumerate(rhythm):
            dur_sec = dur_beats * beat_dur
            is_downbeat = (r_pos == 0)

            # 二阶马尔可夫采样
            new_idx = _sample_markov(
                prev2, prev1, scale_notes,
                chord_degree, tension,
                downbeat=is_downbeat,
            )

            # 推进状态
            prev2, prev1 = prev1, new_idx

            # 休止概率（句尾更高）
            rest_prob = 0.06 if r_pos < len(rhythm) - 1 else 0.15
            if random.random() < rest_prob:
                melody.append((0, dur_sec))
            else:
                melody.append((scale_notes[prev1], dur_sec))

        bar_idx += 1

    return melody


# ═══════════════════════════════════════════════
#  旋律主题（Motif）生成与变奏
# ═══════════════════════════════════════════════

def generate_motif(scale_notes: list, chord_prog: list, bpm: int,
                   motif_length: int = 8) -> list:
    """生成短乐思 motif，返回 [(freq_idx, dur_beats), ...]。
    dur_beats 以四分音符 = 1.0 为单位，不依赖 BPM。"""
    n = len(scale_notes)
    scale_len = n // 2 if n >= 2 else n
    beat_dur = 60.0 / bpm

    # 用一小节来生成 motif（4拍）
    motif = []
    total_beats = 0.0
    target_beats = 4.0  # 一小节

    first_chord = chord_prog[0] if chord_prog else 1
    chord_root = (first_chord - 1) % scale_len
    chord_tones = {chord_root, (chord_root + 2) % scale_len, (chord_root + 4) % scale_len}
    mid = n // 2
    cands = [i for i in range(max(1, mid - 3), min(n - 1, mid + 4))
             if (i % scale_len) in chord_tones]
    if not cands:
        cands = [mid, mid + 1]

    prev2 = mid
    prev1 = random.choice(cands)

    while total_beats < target_beats and len(motif) < motif_length:
        # 节奏选择偏向 motif 常用节奏
        dur_beats = random.choice([0.25, 0.5, 0.5, 0.5, 1.0, 1.0])
        dur_beats = min(dur_beats, target_beats - total_beats)
        if dur_beats <= 0:
            break

        new_idx = _sample_markov(prev2, prev1, scale_notes, first_chord, 0.4)
        prev2, prev1 = prev1, new_idx
        motif.append((prev1, dur_beats))
        total_beats += dur_beats

    return motif


_VARIATION_TYPES = [
    "transpose_up",    # 升高八度
    "transpose_down",  # 降低八度
    "augment",         # 节奏拉长 2×
    "diminish",        # 节奏缩短 0.5×
    "invert",          # 音程翻转
    "retrograde",      # 倒序播放
    "shifted",         # 同节奏换音
    "none",            # 原样复用
]


def vary_motif(motif: list, scale_notes: list,
               variation_type: str, scale_len: int) -> list:
    """对 motif 应用变奏，返回新的 [(freq_idx, dur_beats), ...]。
    scale_len = 每八度音阶音符数。"""
    if variation_type == "none" or not motif:
        return list(motif)

    if variation_type == "transpose_up":
        return [(min(idx + scale_len, len(scale_notes) - 1), d)
                for idx, d in motif]

    if variation_type == "transpose_down":
        return [(max(idx - scale_len, 0), d) for idx, d in motif]

    if variation_type == "augment":
        return [(idx, d * 2.0) for idx, d in motif]

    if variation_type == "diminish":
        return [(idx, max(d * 0.5, 0.125)) for idx, d in motif]

    if variation_type == "invert":
        # 以第一个音为轴翻转
        if len(motif) < 2:
            return list(motif)
        pivot = motif[0][0]
        result = [(pivot, motif[0][1])]
        for idx, d in motif[1:]:
            delta = idx - pivot
            new_idx = max(0, min(len(scale_notes) - 1, pivot - delta))
            result.append((new_idx, d))
        return result

    if variation_type == "retrograde":
        return list(reversed(motif))

    if variation_type == "shifted":
        # 保持节奏，随机微调音高
        result = []
        for idx, d in motif:
            delta = random.choice([-2, -1, 0, 1, 2])
            new_idx = max(0, min(len(scale_notes) - 1, idx + delta))
            result.append((new_idx, d))
        return result

    return list(motif)


def motif_to_melody(motif: list, scale_notes: list,
                    beat_dur: float, target_bars: int,
                    time_sig: int = 4) -> list:
    """将 motif [(freq_idx, dur_beats), ...] 展开为旋律 [(freq, dur_sec), ...]。
    若 motif 不够长则循环填充到 target_bars 小节。"""
    result = []
    total_sec = 0.0
    target_sec = target_bars * time_sig * beat_dur

    while total_sec < target_sec:
        for idx, dur_beats in motif:
            dur_sec = dur_beats * beat_dur
            if total_sec + dur_sec > target_sec:
                dur_sec = target_sec - total_sec
            if dur_sec <= 0:
                break
            result.append((scale_notes[idx], dur_sec))
            total_sec += dur_sec
            if total_sec >= target_sec:
                break

    return result


# ═══════════════════════════════════════════════
#  多声部对位（Counterpoint）
# ═══════════════════════════════════════════════

def generate_counterpoint(main_indices: list,  # [(freq_idx, dur_beats), ...]
                          scale_notes: list,
                          chord_prog: list,
                          n_bars: int,
                          bpm: int,
                          time_sig: int = 4) -> list:
    """生成对位旋律 [(freq_idx, dur_beats), ...]。
    main_indices: 主旋律的音高索引+时长列表。
    规则：反行倾向、避免平行五八度、节奏互补。"""
    n = len(scale_notes)
    scale_len = n // 2 if n >= 2 else n
    beat_dur = 60.0 / bpm

    if not main_indices:
        return []

    counter = []
    total_beats = 0.0
    target_beats = n_bars * time_sig

    # 初始化：与主旋律起始音构成三度/六度
    main_start_idx = main_indices[0][0] if main_indices else scale_len
    offset = random.choice([-2, -1, 2, 3])  # 三度或六度
    prev2_c = max(0, min(n - 1, main_start_idx + offset - 2))
    prev1_c = max(0, min(n - 1, main_start_idx + offset))

    main_pos = 0
    main_beats_elapsed = 0.0

    chord_idx = 0
    chord_dur_beats = time_sig  # 每个和弦持续一小节
    chord_beats_elapsed = 0.0

    while total_beats < target_beats and main_pos < len(main_indices):
        # 确定当前和弦
        chord_degree = chord_prog[chord_idx % len(chord_prog)]

        # 获取主旋律当前位置的音高
        main_idx, main_dur = main_indices[main_pos]

        # 对位节奏：与主旋律错开
        dur_beats = main_dur
        if random.random() < 0.4:
            # 对位用不同节奏
            dur_beats = random.choice([0.25, 0.5, 1.0, 1.5])
            dur_beats = min(dur_beats, main_dur * 2)

        # 选择对位音高
        c_weight = _counterpoint_score(
            prev2_c, prev1_c, main_idx, scale_notes,
            chord_degree, scale_len, n)

        total_w = sum(c_weight)
        if total_w <= 0:
            new_idx = prev1_c
        else:
            probs = [w / total_w for w in c_weight]
            new_idx = random.choices(range(n), weights=probs, k=1)[0]

        prev2_c, prev1_c = prev1_c, new_idx
        counter.append((new_idx, dur_beats))
        total_beats += dur_beats

        # 推进主旋律位置
        main_beats_elapsed += main_dur
        if main_beats_elapsed >= dur_beats:
            main_pos += 1
            main_beats_elapsed -= dur_beats

        # 推进和弦
        chord_beats_elapsed += dur_beats
        if chord_beats_elapsed >= chord_dur_beats:
            chord_idx += 1
            chord_beats_elapsed -= chord_dur_beats

    # 转为 [(freq, dur_sec), ...]
    return [(scale_notes[idx], dur * beat_dur) for idx, dur in counter]


def _counterpoint_score(prev2_c: int, prev1_c: int, main_idx: int,
                        scale_notes: list, chord_degree: int,
                        scale_len: int, n: int) -> list:
    """对位音高评分：反行倾向 + 避免平行五八度 + 和弦音。"""
    weights = []
    chord_root = (chord_degree - 1) % scale_len
    chord_tones = {chord_root, (chord_root + 2) % scale_len, (chord_root + 4) % scale_len}

    for cand in range(n):
        score = 1.0

        # 1. 反行倾向
        d_counter = cand - prev1_c
        d_main = main_idx - prev1_c  # 主旋律方向近似
        if d_counter * d_main < 0 and d_counter != 0:
            score *= 2.5         # 反行：强奖励
        elif d_counter * d_main > 0:
            score *= 0.5         # 平行：惩罚

        # 2. 避免平行五度/八度（音程 = 4 或 7 个半音）
        interval_now = abs(cand - main_idx) % scale_len
        if interval_now in (0, scale_len - 1 if scale_len > 1 else 0):
            score *= 0.15        # 同度/八度
        elif interval_now == 4:
            score *= 0.3         # 五度
        elif interval_now == 3:
            score *= 1.8         # 三度/六度最优

        # 3. 级进优先
        step = abs(cand - prev1_c)
        if step <= 1:
            score *= 2.5
        elif step <= 2:
            score *= 1.8
        elif step >= 6:
            score *= 0.2

        # 4. 和弦音
        if (cand % scale_len) in chord_tones:
            score *= 2.0

        weights.append(max(score, 1e-5))

    return weights


# ═══════════════════════════════════════════════
#  和弦织体（Chord Voicing）— 柱式和弦块
# ═══════════════════════════════════════════════

def generate_chord_blocks(scale_notes: list, chord_prog: list,
                          n_bars: int, bpm: int,
                          time_sig: int = 4,
                          voicing: str = "close") -> list:
    """生成柱式和弦序列。
    返回 [(freqs_list, dur_sec), ...] — 每个元素是一组同时发声的频率和时长。
    voicing: "close" | "open" | "drop2"
    """
    beat_dur = 60.0 / bpm
    scale_len = len(scale_notes) // 2 if len(scale_notes) >= 2 else len(scale_notes)
    n = len(scale_notes)

    chord_seq = []
    bar_dur = time_sig * beat_dur

    for bar_idx in range(n_bars):
        chord_degree = chord_prog[bar_idx % len(chord_prog)]
        chord_root_idx = (chord_degree - 1) % scale_len

        # 和弦构成音级（相对主音偏移）
        if voicing == "close":
            # 密集排列：根-三-五（同八度内）
            intervals = [0, 2, 4]
        elif voicing == "open":
            # 开放排列：根-五-十（跨八度）
            intervals = [0, 4, 7]
        elif voicing == "drop2":
            # Drop-2：根-五-三（三音降八度）
            intervals = [0, 4, scale_len + 2]
        else:
            intervals = [0, 2, 4]

        # 选择基础八度（中低音区）
        base_oct = max(0, scale_len - 2)
        freqs = []
        for interval in intervals:
            idx = min(chord_root_idx + interval + base_oct, n - 1)
            freqs.append(scale_notes[idx])

        # 每小节奏柱式和弦（强拍或半小节）
        for beat_pos in [0, 2]:  # 第1拍和第3拍
            onset = bar_idx * bar_dur + beat_pos * beat_dur
            dur = beat_dur * random.choice([1.0, 1.5, 2.0])
            # 确保不超小节边界
            dur = min(dur, bar_dur - beat_pos * beat_dur)
            if dur > 0:
                chord_seq.append((freqs, dur, onset))

    # 按 onset 排序
    chord_seq.sort(key=lambda x: x[2])

    # 保留 onset: 返回 [(freqs, dur, onset_sec), ...]
    # 便于 MIDI 导出时精确定位和弦起始时刻（音频渲染只用 freqs/dur）。
    return chord_seq


def generate_bass(scale_notes: list, chord_prog: list, n_bars: int,
                  bpm: int, time_sig: int = 4) -> list:
    """生成低音声部（基于总时长）"""
    beat_dur = 60.0 / bpm
    target_duration = n_bars * time_sig * beat_dur
    bass_notes = scale_notes[:len(scale_notes) // 2]

    bass = []
    total_dur = 0.0

    while total_dur < target_duration:
        for chord_idx in chord_prog:
            if total_dur >= target_duration:
                break
            root_idx = min(chord_idx - 1, len(bass_notes) - 1)
            fifth_idx = min(root_idx + 4, len(bass_notes) - 1)

            pattern = [
                (bass_notes[root_idx], beat_dur),
                (bass_notes[fifth_idx], beat_dur * 0.5),
                (bass_notes[root_idx], beat_dur * 0.5),
                (bass_notes[fifth_idx], beat_dur),
                (bass_notes[root_idx], beat_dur),
            ]
            for freq, dur in pattern:
                if total_dur >= target_duration:
                    break
                dur = min(dur, target_duration - total_dur)
                bass.append((freq, dur))
                total_dur += dur

    return bass


def generate_arpeggio(scale_notes: list, chord_prog: list, n_bars: int,
                      bpm: int, time_sig: int = 4,
                      pattern: str = "up") -> list:
    """
    生成琶音音轨（和弦分解）
    pattern: "up" | "down" | "updown" | "random"
    """
    beat_dur = 60.0 / bpm
    arp_note_dur = beat_dur * 0.3
    target_duration = n_bars * time_sig * beat_dur
    chord_intervals = [0, 2, 4, 6]

    arp = []
    total_dur = 0.0
    prog_idx = 0

    while total_dur < target_duration:
        cp = chord_prog[prog_idx % len(chord_prog)]
        root_idx = min(cp - 1, len(scale_notes) - 1)
        arp_pitches = []
        for interval in chord_intervals:
            idx = min(root_idx + interval, len(scale_notes) - 1)
            arp_pitches.append(scale_notes[idx])

        if pattern == "down":
            arp_pitches = list(reversed(arp_pitches))
        elif pattern == "updown":
            arp_pitches = arp_pitches + list(reversed(arp_pitches[1:-1]))
        elif pattern == "random":
            random.shuffle(arp_pitches)

        for freq in arp_pitches:
            if total_dur >= target_duration:
                break
            dur = min(arp_note_dur, target_duration - total_dur)
            arp.append((freq, dur))
            total_dur += dur
        prog_idx += 1

    return arp


def generate_drum_beat(n_bars: int, bpm: int, time_sig: int = 4,
                        complexity: float = 0.3) -> list:
    """生成简易鼓点音轨（合成波形模拟）"""
    sample_rate = 44100
    beat_dur = 60.0 / bpm
    total_samples = int(n_bars * time_sig * beat_dur * sample_rate)
    samples = [0.0] * total_samples

    def _kick(ts, sr):
        t = ts / sr
        freq = 150.0 * math.exp(-t * 30.0) + 40.0
        return math.sin(2 * math.pi * freq * t) * math.exp(-t * 8.0) * 0.6

    def _snare(ts, sr):
        t = ts / sr
        noise = random.uniform(-1, 1) * math.exp(-t * 20.0)
        tone = math.sin(2 * math.pi * 200.0 * t) * math.exp(-t * 15.0) * 0.3
        return (noise + tone) * 0.4

    def _hihat(ts, sr, open_=False):
        t = ts / sr
        decay = 0.1 if open_ else 0.03
        return random.uniform(-1, 1) * math.exp(-t / decay) * 0.15

    sub_beat_samples = int(beat_dur * sample_rate) // 2

    for bar in range(n_bars):
        for beat_in_bar in range(time_sig * 2):
            beat_abs = (bar * time_sig * 2) + beat_in_bar
            pos = beat_abs * sub_beat_samples
            if pos >= total_samples:
                break
            is_downbeat = (beat_in_bar % time_sig == 0)
            is_backbeat = (beat_in_bar % 2 == 1)

            if is_downbeat or (random.random() < complexity * 0.3):
                end_pos = min(pos + sub_beat_samples, total_samples)
                for j in range(pos, end_pos):
                    samples[j] += _kick(j - pos, sample_rate)

            if (is_backbeat and beat_in_bar % time_sig != 0) or \
                    (random.random() < complexity * 0.2):
                end_pos = min(pos + sub_beat_samples, total_samples)
                for j in range(pos, end_pos):
                    samples[j] += _snare(j - pos, sample_rate)

            if random.random() < 0.7 + complexity * 0.2:
                end_pos = min(pos + sub_beat_samples, total_samples)
                for j in range(pos, end_pos):
                    samples[j] += _hihat(j - pos, sample_rate, open_=False)

    return samples
