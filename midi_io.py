"""
MIDI 进出桥 — 纯 Python 标准库实现，零外部依赖

功能:
  - write_midi(tracks, path, bpm, ppq): 把生成结果导出为标准 MIDI（format 1，
    多轨道，每轨一个声部），可被任意 DAW / 播放器打开。
  - read_midi(path): 解析标准 MIDI，返回每轨音符事件列表。
  - freq_to_midi / midi_to_freq: 频率 <-> MIDI 音高互转。
  - midi_to_melody_idx(notes, scale_notes, bpm): 把导入的 MIDI 音符
    对齐到当前音阶，转为引擎可用的 (音高索引, 时长拍) 旋律种子。

设计约束（硬）:
  - 仅使用 Python 标准库（struct / math / os），不引入任何第三方依赖。
  - 导出的 MIDI 必须能被外部程序正确解析（MThd/MTrk 头、VLQ、音符事件）。
"""

import struct
import math


# ── 频率 <-> MIDI 音高 ──

def freq_to_midi(freq: float):
    """频率(Hz) -> MIDI 音高编号(0-127)；freq<=0 表示休止，返回 None。"""
    if freq is None or freq <= 0:
        return None
    m = 69 + 12 * math.log2(freq / 440.0)
    m = int(round(m))
    return max(0, min(127, m))


def midi_to_freq(midi: int) -> float:
    """MIDI 音高编号 -> 频率(Hz)。"""
    return 440.0 * (2.0 ** ((int(midi) - 69) / 12.0))


# ── 可变长度量 (VLQ) ──

def _vlq_encode(value: int) -> bytes:
    """把整数编码为 MIDI 可变长度量。"""
    if value < 0:
        value = 0
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.insert(0, (value & 0x7F) | 0x80)
        value >>= 7
    return bytes(out)


def _vlq_decode(data: bytes, pos: int):
    """从 data[pos] 解码一个 VLQ，返回 (值, 新位置)。"""
    value = 0
    while True:
        b = data[pos]
        pos += 1
        value = (value << 7) | (b & 0x7F)
        if not (b & 0x80):
            break
    return value, pos


# ── 写出 MIDI ──

def write_midi(tracks: list, filepath: str, bpm: int = 120, ppq: int = 480):
    """
    把多轨音符写出为标准 MIDI 文件。

    tracks: list of dict，每个 dict:
        {
          "name":    str,             # 轨道名（写入 track name meta）
          "channel": int,             # MIDI 通道 0-15
          "notes":   [(midi, start_sec, dur_sec, velocity), ...]
        }
        midi: 0-127；start_sec/dur_sec 单位秒；velocity 0-127（默认 80）。
    """
    ticks_per_sec = ppq * bpm / 60.0
    tempo_us = int(round(60000000 / bpm))

    # 轨道数 >=2 用 format 1，否则 format 0
    fmt = 1 if len(tracks) > 1 else 0

    chunks = []
    for ti, tr in enumerate(tracks):
        channel = tr.get("channel", 0) & 0x0F
        events = []  # (abs_tick, bytes)

        # 第一轨写入全局速度（microseconds per quarter note）
        if ti == 0:
            events.append((0, b"\xff\x51\x03" + tempo_us.to_bytes(3, "big")))

        # 轨道名 meta
        name = tr.get("name", "")
        if name:
            nb = name.encode("utf-8")[:255]
            events.append((0, b"\xff\x03" + _vlq_encode(len(nb)) + nb))

        for note in tr.get("notes", []):
            midi, start, dur, vel = (list(note) + [80])[:4]
            if midi is None:
                continue
            on_tick = int(round(start * ticks_per_sec))
            off_tick = int(round((start + dur) * ticks_per_sec))
            if off_tick <= on_tick:
                off_tick = on_tick + 1
            midi = int(round(midi)) & 0x7F
            vel = int(round(vel)) & 0x7F
            events.append((on_tick, bytes([0x90 | channel, midi, vel])))
            events.append((off_tick, bytes([0x80 | channel, midi, 0])))

        events.sort(key=lambda e: e[0])

        data = bytearray()
        prev = 0
        for tick, b in events:
            data += _vlq_encode(tick - prev)
            data += b
            prev = tick
        # 轨道结束标记
        data += _vlq_encode(0) + b"\xff\x2f\x00"

        chunks.append(b"MTrk" + len(data).to_bytes(4, "big") + bytes(data))

    header = (
        b"MThd"
        + (6).to_bytes(4, "big")
        + fmt.to_bytes(2, "big")
        + len(tracks).to_bytes(2, "big")
        + ppq.to_bytes(2, "big")
    )

    with open(filepath, "wb") as f:
        f.write(header)
        for c in chunks:
            f.write(c)

    print(f"  ✓ MIDI 文件已保存: {filepath}（{len(tracks)} 轨, {bpm} BPM）")


# ── 解析 MIDI ──

def read_midi(filepath: str) -> list:
    """
    解析标准 MIDI 文件，返回轨道列表:
        [ {"name": str, "notes": [(midi, start_sec, dur_sec), ...]}, ... ]
    支持 tempo meta（速度变化）与 running status。
    """
    with open(filepath, "rb") as f:
        data = f.read()

    if data[:4] != b"MThd":
        raise ValueError("不是有效的 MIDI 文件（缺少 MThd 头）")

    header_len = int.from_bytes(data[4:8], "big")
    fmt = int.from_bytes(data[8:10], "big")
    ntracks = int.from_bytes(data[10:12], "big")
    division = int.from_bytes(data[12:14], "big")  # ticks per quarter note
    pos = 8 + header_len

    tracks = []
    for _ in range(ntracks):
        if data[pos:pos + 4] != b"MTrk":
            break
        tlen = int.from_bytes(data[pos + 4:pos + 8], "big")
        tdata = data[pos + 8:pos + 8 + tlen]
        pos += 8 + tlen
        name, notes = _parse_track(tdata, division)
        tracks.append({"name": name, "notes": notes})

    _ = fmt  # format 字段已解析，供将来扩展
    return tracks


def _parse_track(tdata: bytes, division: int):
    """解析单条 MTrk，返回 (轨道名, 音符列表)。"""
    pos = 0
    abs_tick = 0
    tempo = 500000  # 默认 120 BPM
    sec_per_tick = tempo / (division * 1_000_000.0)
    active = {}      # (channel, note) -> start_tick
    notes = []
    track_name = ""
    running_status = None

    while pos < len(tdata):
        delta, pos = _vlq_decode(tdata, pos)
        abs_tick += delta

        status = tdata[pos]
        if status & 0x80:
            running_status = status
            pos += 1
        else:
            status = running_status

        # 系统 / meta 事件
        if status == 0xFF:
            meta_type = tdata[pos]
            pos += 1
            mlen, pos = _vlq_decode(tdata, pos)
            if meta_type == 0x51 and mlen == 3:
                tempo = int.from_bytes(tdata[pos:pos + 3], "big")
                sec_per_tick = tempo / (division * 1_000_000.0)
            elif meta_type == 0x03:
                track_name = tdata[pos:pos + mlen].decode("utf-8", "replace")
            pos += mlen
            if meta_type == 0x2F:  # 轨道结束
                break
            continue

        if status in (0xF0, 0xF7):  # 系统 exclusive
            sylen, pos = _vlq_decode(tdata, pos)
            pos += sylen
            continue

        event_type = status & 0xF0
        channel = status & 0x0F

        if event_type in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
            d1 = tdata[pos]
            d2 = tdata[pos + 1]
            pos += 2
        elif event_type in (0xC0, 0xD0):
            d1 = tdata[pos]
            d2 = 0
            pos += 1
        else:
            d1 = d2 = 0

        if event_type == 0x90 and d2 > 0:
            active[(channel, d1)] = abs_tick
        elif event_type == 0x80 or (event_type == 0x90 and d2 == 0):
            key = (channel, d1)
            if key in active:
                start = active.pop(key)
                dur_ticks = abs_tick - start
                notes.append((d1, start * sec_per_tick, dur_ticks * sec_per_tick))

    return track_name, notes


# ── MIDI -> 引擎旋律种子 ──

def midi_to_melody_idx(notes: list, scale_notes: list, bpm: int,
                        quantize: float = 0.25) -> list:
    """
    把一条 MIDI 音符序列对齐到当前音阶，转为引擎可用的旋律种子:
        [(音高索引, 时长拍), ...]
    时长按 quantize（拍）量化，便于引擎循环复用。
    """
    if not notes or not scale_notes:
        return []
    beat_dur = 60.0 / bpm

    seed = []
    for midi, start, dur in notes:
        freq = midi_to_freq(midi)
        # 找最接近的音阶音
        idx = min(range(len(scale_notes)),
                  key=lambda i: abs(scale_notes[i] - freq))
        dur_beats = max(quantize, round(dur / beat_dur / quantize) * quantize)
        seed.append((idx, dur_beats))
    return seed
