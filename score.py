"""
批量质量自动评分 — 纯 Python 标准库实现，零外部依赖

从「符号特征」（旋律音域 / 重复比 / 音程多样性 / 节奏方差）
与「音频特征」（动态范围 / 静音比）计算 0-100 音乐性评分。

设计约束（硬）:
  - 仅使用标准库（math / statistics），不引入任何第三方依赖。
  - 评分是启发式的「相对质量筛选用」，不是绝对审美判定；
    用于 batch_mode 自动排序，筛掉明显单调/死寂/过密的输出。
"""

import math
import statistics


def _window_rms(samples: list, win: int) -> list:
    """把样本切成定长窗口，返回每窗 RMS。"""
    if not samples or win <= 0:
        return [0.0]
    out = []
    for i in range(0, len(samples), win):
        w = samples[i:i + win]
        if not w:
            continue
        rms = math.sqrt(sum(x * x for x in w) / len(w))
        out.append(rms)
    return out or [0.0]


def compute_features(melody_index_seq: list, mixed: list,
                     sample_rate: int) -> dict:
    """
    从符号序列 + 混音样本提取评分特征。
    melody_index_seq: [(音高索引, 时长拍), ...]
    mixed: 混音后的浮点样本列表
    """
    idxs = [i for i, _ in melody_index_seq] if melody_index_seq else []
    rhythm = [d for _, d in melody_index_seq] if melody_index_seq else []

    # ── 旋律符号特征 ──
    if idxs:
        rng = max(idxs) - min(idxs)
        repeats = sum(1 for a, b in zip(idxs, idxs[1:]) if a == b)
        rep_ratio = repeats / max(1, len(idxs) - 1)
        steps = [abs(a - b) for a, b in zip(idxs, idxs[1:])]
        distinct_steps = len(set(steps))
        rhythm_var = statistics.pstdev(rhythm) if len(rhythm) > 1 else 0.0
    else:
        rng = rep_ratio = distinct_steps = rhythm_var = 0

    # ── 音频特征 ──
    win = max(1, sample_rate // 10)  # 约 100ms 窗口
    rms_vals = _window_rms(mixed, win)
    peak = max(rms_vals) or 1e-6
    min_r = min(rms_vals) or 0.0
    dyn_db = 20.0 * math.log10(peak / min_r) if min_r > 1e-6 else 0.0
    silence = sum(1 for r in rms_vals if r < peak * 0.05) / max(1, len(rms_vals))

    return {
        "range": rng,
        "rep_ratio": rep_ratio,
        "distinct_steps": distinct_steps,
        "rhythm_var": rhythm_var,
        "dyn_db": dyn_db,
        "silence": silence,
    }


def score_track(features: dict) -> float:
    """
    把特征归一化为 0-100 评分。
    权重反映「长曲连贯/避免机械重复/有动态对比」的 2026 共识偏好。
    """
    # 各维度分数（0-1，越高越好）
    range_score = min(features["range"] / 30.0, 1.0)          # 音域适中更丰富
    rep_score = 1.0 - min(features["rep_ratio"] / 0.30, 1.0)  # 重复越低越好
    step_score = min(features["distinct_steps"] / 8.0, 1.0)   # 音程多样
    rhy_score = min(features["rhythm_var"] / 0.5, 1.0)        # 节奏多样
    dyn_score = min(features["dyn_db"] / 24.0, 1.0)           # 动态范围大
    sil_score = 1.0 - min(features["silence"] / 0.40, 1.0)    # 静音适中

    weights = [0.20, 0.20, 0.15, 0.15, 0.20, 0.10]
    scores = [range_score, rep_score, step_score,
              rhy_score, dyn_score, sil_score]
    total = sum(w * s for w, s in zip(weights, scores))
    return round(100.0 * total, 1)


def rank_results(results: list) -> list:
    """
    对批量结果按评分降序排名。
    results: [{"path":..., "params":..., "score":float}, ...]
    返回带 "rank" 字段的新列表（不修改原对象顺序的引用语义，复制后排序）。
    """
    ranked = sorted(results, key=lambda r: r.get("score", 0.0), reverse=True)
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    return ranked
