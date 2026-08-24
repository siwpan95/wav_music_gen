"""
wav_music_gen 完整纯音乐制作脚本（零依赖、可续跑）

策略：沙箱对单首长曲会静默 SIGKILL，因此把一首 3~5 分钟的曲子拆成若干
「调性/速度统一、音色与织体逐段变化」的短段落（每段 ≤ ~16 小节，远低於被
杀阈值），逐段生成 WAV+MIDI，最后用标准库拼接成 master.wav，并合并出
master.mid（每声部一轨、按时间偏移对齐）。

可续跑：每完成一段就写入 manifest.json；进程被杀后重跑本脚本会自动跳过
已完成段落，直到全部完成并产出 master。

用法：
  python produce.py            # 生成全部段落并拼接 master（统一 I-V-vi-IV + 全局主题动机）
  python produce.py --only 0   # 只生成第 0 段（用于并行/分批）
  python produce.py --concat   # 仅拼接（段落已齐全时）
  python produce.py --chord "1 6 4 5"     # 自定义全局和弦进行
  python produce.py --motif "0 2 4 2:2 0" # 自定义全局主题动机（覆盖自动生成）
"""
import os, sys, json, time, wave, struct
from array import array

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from autowav import generate_music
from midi_io import read_midi, write_midi
from theory import build_scale_notes, SCALES
from melody import generate_motif, vary_motif

OUT = os.path.join(_SCRIPT_DIR, "output")
PROD = os.path.join(OUT, "production")
os.makedirs(PROD, exist_ok=True)
MANIFEST = os.path.join(PROD, "manifest.json")
MASTER_WAV = os.path.join(PROD, "master.wav")
MASTER_MID = os.path.join(PROD, "master.mid")

# ── 全局统一配置：保证整曲调性/速度连贯 ──
BPM = 112
SCALE = "自然小调"
ROOT = "A"
OCTAVE = 4
SR = 44100
PPQ = 480
beat = 60.0 / BPM
bar_dur = 4 * beat

# ── 全局固定和声骨架 + 主题动机（让整曲和声与主题统一）──
CHORD_PROG = [1, 5, 6, 4]   # I-V-vi-IV：经典流行进行，适配 A 自然小调
_scale_notes = build_scale_notes(ROOT, OCTAVE, SCALES[SCALE])
_scale_len = len(_scale_notes) // 2 if len(_scale_notes) >= 2 else len(_scale_notes)
# 主题动机每段采用的变奏（循环），使同一动机在全曲中"发展复现"
MOTIF_VARS = ["none", "transpose_up", "augment", "transpose_down",
              "invert", "diminish", "retrograde", "shifted"]

def secs_to_bars(sec):
    return max(4, round(sec / bar_dur))

# ── 曲式设计（固定调式，靠音色+织体变化营造动态）──
# (名称, 目标秒, 主音色, 低音, 对位, 和弦, 琶音, 鼓)
SECTIONS = [
    ("01_intro",   26, "正弦波",   False, False, False, False, False),
    ("02_verseA",  32, "钢琴",     True,  False, False, True,  False),
    ("03_chorusB", 36, "管风琴",   True,  True,  True,  True,  True),
    ("04_verseA2", 32, "三角波",   True,  False, False, True,  False),
    ("05_bridgeC", 28, "竖琴",     False, False, True,  True,  False),
    ("06_chorusB2",36, "管风琴",   True,  True,  True,  True,  True),
    ("07_outro",   26, "正弦波",   False, False, False, False, False),
]
# 目标总时长 ≈ 26+32+36+32+28+36+26 = 216s ≈ 3.6 分钟

VOICE_CH = {"旋律": 0, "对位": 1, "低音": 2, "和弦": 3, "琶音": 4}
VOICE_VEL = {"旋律": 90, "对位": 75, "低音": 85, "和弦": 70, "琶音": 80}


def load_manifest():
    if os.path.exists(MANIFEST):
        try:
            return json.load(open(MANIFEST, encoding="utf-8"))
        except Exception:
            pass
    return {"done": []}


def save_manifest(m):
    json.dump(m, open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def read_samples(path):
    with wave.open(path, "r") as wf:
        p = wf.getparams()
        raw = wf.readframes(wf.getnframes())
    a = array("h")
    a.frombytes(raw)
    return p, a


def concat_wavs(paths, out, cf_sec=0.10, fade_in=0.5, fade_out=1.0):
    """拼接若干 WAV（须同格式），段间做等功率交叉淡入淡出，首尾轻微淡变。"""
    params = None
    master = None
    for path in paths:
        p, a = read_samples(path)
        if params is None:
            params = p
            master = a[:]
            cf = int(cf_sec * p.framerate)
            continue
        # 仅比较格式字段（声道/位深/采样率），nframes 各段不同属正常
        if (p.nchannels, p.sampwidth, p.framerate) != \
           (params.nchannels, params.sampwidth, params.framerate):
            raise ValueError(f"WAV 格式不一致: {path} ({p} != {params})")
        if cf > 1 and len(master) >= cf and len(a) >= cf:
            tail = master[-cf:]
            head = a[:cf]
            mixed = array("h")
            denom = max(cf - 1, 1)
            for j in range(cf):
                t = j / denom
                v = int(round(tail[j] * (1 - t) + head[j] * t))
                mixed.append(max(-32768, min(32767, v)))
            master = master[:-cf] + mixed + a[cf:]
        else:
            master = master + a

    n = len(master)
    sr = params.framerate
    fi = int(min(fade_in, n / 2) * sr)
    fo = int(min(fade_out, n / 2) * sr)
    for i in range(fi):
        master[i] = int(master[i] * (i / max(fi - 1, 1)))
    for i in range(fo):
        master[n - 1 - i] = int(master[n - 1 - i] * (i / max(fo - 1, 1)))

    with wave.open(out, "w") as wf:
        wf.setparams(params)
        wf.writeframes(master.tobytes())
    dur = n / sr
    print(f"  ✓ 主音频已拼接: {out}（{dur:.1f}s ≈ {dur/60:.1f} 分钟）")
    return dur


def combine_midis(mid_paths, wav_paths, out):
    voices = {}
    offset = 0.0
    for mp, wp in zip(mid_paths, wav_paths):
        if not os.path.exists(mp):
            offset += (wave.open(wp).getnframes() / wave.open(wp).getframerate()) if os.path.exists(wp) else 0
            continue
        with wave.open(wp, "r") as wf:
            dur = wf.getnframes() / wf.getframerate()
        for tr in read_midi(mp):
            nm = tr["name"]
            for note in tr["notes"]:
                midi, start, dur_n = note[0], note[1], note[2]
                voices.setdefault(nm, []).append(
                    (midi, start + offset, dur_n, VOICE_VEL.get(nm, 80)))
        offset += dur
    tracks_out = [{"name": nm, "channel": VOICE_CH.get(nm, 0), "notes": notes}
                  for nm, notes in voices.items()]
    if tracks_out:
        write_midi(tracks_out, out, bpm=BPM, ppq=PPQ)
        print(f"  ✓ 主 MIDI 已合并: {out}（{len(tracks_out)} 轨）")


def generate_section(name, sec, timbre, bass, cp, ch, arp, drum, chord_prog, motif):
    bars = secs_to_bars(sec)
    out_wav = os.path.join(PROD, name + ".wav")
    out_mid = os.path.join(PROD, name + ".mid")
    print(f"\n=== 生成段落 {name}（{bars} 小节 / {timbre}）===")
    t0 = time.time()
    generate_music(
        output_path=out_wav, bpm=BPM, scale_name=SCALE, root_note=ROOT,
        root_octave=OCTAVE, timbre=timbre, n_bars=bars,
        add_bass=bass, add_counterpoint=cp, add_chords=ch,
        add_arpeggio=arp, add_drum=drum, add_reverb=True,
        export_midi=True, midi_path=out_mid,
        chord_progression=chord_prog, motif_seed=motif,
    )
    print(f"[done] {name} 用时 {time.time()-t0:.1f}s")
    return out_wav, out_mid


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, default=None, help="只生成第 N 段（0-based）")
    ap.add_argument("--concat", action="store_true", help="仅拼接已生成的段落")
    ap.add_argument("--force", action="store_true",
                    help="清除已生成段落，用当前参数重新渲染（换和弦/主题后重做整曲）")
    ap.add_argument("--chord", type=str, default=None,
                    help='自定义全局和弦进行，如 "1 5 6 4" 或 "I-vi-IV-V"')
    ap.add_argument("--motif", type=str, default=None,
                    help='自定义主题动机，如 "0 2 4 2:2 0"（音阶内0起算索引:拍）')
    args = ap.parse_args()

    manifest = load_manifest()
    done = set(manifest.get("done", []))

    if args.force:
        print("[force] 清除已生成段落，以新参数重新渲染…")
        for s in SECTIONS:
            for ext in (".wav", ".mid"):
                p = os.path.join(PROD, s[0] + ext)
                if os.path.exists(p):
                    os.remove(p)
        manifest = {"done": []}
        done = set()

    # 全局和声骨架：显式参数 > 已记录(续跑) > 默认
    chord_prog = args.chord or manifest.get("chord_prog") or CHORD_PROG
    manifest["chord_prog"] = chord_prog

    if not args.concat:
        # 全曲统一生成一次主题动机（--motif 显式指定则直接下发；否则生成一次并
        # 记入 manifest，续跑时复用以保证整曲主题统一）
        if args.motif:
            base_motif = args.motif
            manifest["motif"] = args.motif
            print(f"  使用自定义主题动机: {args.motif}")
        elif manifest.get("motif"):
            base_motif = [(int(i), float(d)) for i, d in manifest["motif"]]
            print(f"  复用已记录主题动机（续跑保持统一，{len(base_motif)} 音）")
        else:
            base_motif = generate_motif(_scale_notes, chord_prog, BPM, motif_length=8)
            manifest["motif"] = [[i, d] for i, d in base_motif]
            print(f"  生成全局主题动机（{len(base_motif)} 音），逐段变奏复现…")
        save_manifest(manifest)

        for idx, sec in enumerate(SECTIONS):
            name = sec[0]
            if args.only is not None and idx != args.only:
                continue
            if name in done and args.only is None:
                print(f"[skip] {name} 已完成")
                continue
            # 每段用不同变奏（显式字符串动机则不预变奏，直接下发）
            if args.motif:
                motif_arg = base_motif
            else:
                motif_arg = vary_motif(base_motif, _scale_notes,
                                       MOTIF_VARS[idx % len(MOTIF_VARS)], _scale_len)
            generate_section(*sec, chord_prog, motif_arg)
            if name not in manifest.get("done", []):
                manifest.setdefault("done", []).append(name)
                save_manifest(manifest)

    wavs = [os.path.join(PROD, s[0] + ".wav") for s in SECTIONS]
    mids = [os.path.join(PROD, s[0] + ".mid") for s in SECTIONS]
    all_done = all(os.path.exists(w) for w in wavs)

    if not all_done:
        missing = [s[0] for s, w in zip(SECTIONS, wavs) if not os.path.exists(w)]
        print(f"\n[进度] 仍有段落未生成: {missing}；下次运行将继续。")
        if args.concat:
            print("  （--concat 但段落不齐，跳过拼接）")
        return

    print("\n=== 全部段落就绪，拼接 master ===")
    concat_wavs(wavs, MASTER_WAV)
    combine_midis(mids, wavs, MASTER_MID)
    print(f"\n✅ 制作完成：\n  WAV: {MASTER_WAV}\n  MIDI: {MASTER_MID}")


if __name__ == "__main__":
    main()
