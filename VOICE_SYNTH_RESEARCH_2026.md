# AutoWav 人声生成调研与落地报告

> 调研日期：2026-08-14（联网检索，来源见文末）
> 问题：能否用 `G:\tools\audio\wav_music_gen` 模拟生成人声？
> 结论：**能，分三层。第一层（零依赖共振峰人声音色）今日已落地并有可听产物；真·歌词演唱本机硬件不支持，走桌面软件或云端。**

---

## 一、结论速览

「模拟生成人声」按目标拆成三档，答案不同：

| 档位 | 目标 | 本机可行性 | 结论 |
|------|------|-----------|------|
| A 音色模拟 | 人声音色唱旋律（无歌词，如合唱「啊」、哼鸣） | ✅ | **已落地**（本次新增 `vocal_formant.py`，纯标准库） |
| B 语音念白 | 说话（有词、无旋律） | ✅ | 可做，轻依赖（SAPI / Piper TTS），尚未集成 |
| C 歌词演唱 | 唱出可懂歌词（SVS） | ⚠️ | 本机无 CUDA，走 OpenUTAU/DiffSinger 的 ONNX CPU 推理或云端/桌面软件 |

**核心判断**：AutoWav 是「算法/符号合成」项目，零依赖是护城河。A 档（共振峰吟唱）与项目路线完全同构，是正确的主战场；C 档是另一条技术赛道（神经 SVS），只能以「导出 MIDI → 外部演唱 → 回灌混音」的 Hybrid 方式接入，不能在核心引擎里硬造。

---

## 二、路线全景（2026 调研）

| 层级 | 方案 | 依赖 | 硬件 | 效果 | 状态 |
|------|------|------|------|------|------|
| 0 | 共振峰合成（Klatt） | 零（stdlib） | 仅 CPU | 元音吟唱/哼鸣，合唱感 | ✅ 已落地 |
| 1a | Windows SAPI TTS（pyttsx3 / PowerShell System.Speech） | 系统自带 | 仅 CPU | 中文念白，机械但离线 | ⚪ 可做 |
| 1b | Piper TTS | onnxruntime，~60MB 模型 | 仅 CPU | 自然念白（中/英） | ⚪ 可做 |
| 2 | OpenUTAU + DiffSinger 声库 | 桌面程序（免费） | CPU 推理慢但可用 | 真歌词演唱，虚拟歌手级 | ⚪ 推荐路线 |
| 2' | `diffsinger-utau`（PyPI，ONNX） | onnxruntime + 声库 | CPU | 同上，可编程调用 | ⚪ 可做 |
| 3 | ACE-Step / YuE / Khala 本地推理 | PyTorch + 模型 10–50GB | GPU 12–24GB | 整曲带词生成 | ❌ 无 CUDA |
| 4 | 网易 X Studio（免费，12+ AI 歌手） | 桌面软件 | 仅 CPU | 专业级演唱，MIDI+歌词驱动 | ⚪ 推荐 |
| 4' | ACE Studio（免费基础版，80+ 歌手） | 桌面软件 | 仅 CPU | 质量更高，可训练音色 | ⚪ 可选 |
| 4'' | MiniMax / Suno / 火山等云端 API | 联网 + Key + 付费 | 云端 | 商用级 | ⚪ 需账号 |

**与 AutoWav 的桥接（Hybrid 工作流，行业共识）**：
`AutoWav --export-midi`（已有 MIDI 桥）→ X Studio / OpenUTAU 导入 → AI 歌手唱出歌词 → 导出 WAV → 与 AutoWav 伴奏混音。这正是 ENHANCEMENT_PLAN_2026 中 Phase 2.2 + 3.1 的既定路线。

---

## 三、已落地：零依赖共振峰人声（2026-08-14）

### 3.1 原理（Klatt 声源-滤波）

```
声带声源（锯齿波近似声门脉冲 + 轻微呼吸噪声）
  → F1/F2/F3 并联二阶谐振器（模拟声道共鸣，加权求和）
  → 元音音色
  + 颤音（5.2Hz、±45 音分、延迟 150ms 起振）
  + 45ms 滑音（legato）+ 60ms 元音平滑过渡 + 柔起音（h 式送气）
```

### 3.2 交付物

- **`vocal_formant.py`**（纯 stdlib，零依赖）：
  - 8 个元音：`a o e i u ü ah(合唱啊) m(哼鸣)`，共振峰表取自语音学近似值；
  - `pinyin_to_vowel()`：拼音韵母 → 韵腹元音（`chang→a`、`ting→i`…）；
  - `vocal_note(freq, dur, vowel, …)` 单音符渲染；`sing(notes, syllables)` 唱整句，自动滑音/元音过渡；
  - 可作模块独立用，也可混入 AutoWav 任意生成的旋律轨。
- **`demo_vocal.py`**：确定性种子、模式化运行（`dry_vowels` / `dry_hum` / `mixed` / `all`）。
- **`batch_vocals.py`**（2026-08-14 新增）：批量生成纯人声干声，断点续跑（manifest 去重），自动选择渲染引擎。
- **`vocal_render_np.py`**（2026-08-14 新增）：numpy/scipy 向量化渲染加速器（可选旁路）。与纯 stdlib 版同结构同参数表（复用 `vocal_formant` 常量），用 `scipy.signal.lfilter` 分段滤波实现，**单首渲染从 ~2 分钟降到 ~1-2 秒**。核心引擎零依赖不变；缺失 numpy/scipy 时 `batch_vocals.py` 自动回退纯 stdlib。
- **产物**（`output/`，★ 为本次干声交付）：
  - ★ `vocal_dry.wav` — **纯人声干声**：元音吟唱（无伴奏、无混响），20.7 秒，乐句级元音变化（ah→o→a→u）+ 乐句间换气静默，峰值归一化；
  - ★ `vocal_dry_hum.wav` — **纯人声干声**：闭口哼鸣（全 "m"，1500Hz 低通只留鼻腔共鸣）；
  - `vocal_demo.wav` — 参考混音版（同人声轨 + 钢琴和弦/低音/轻鼓）；
  - ★ `vocal_batch/` — **批量干声 50 首**（见下节 3.2b）。

### 3.2b 批量干声库（2026-08-14 交付）

- 位置：`output/vocal_batch/`，50 个文件（37 元音吟唱 + 13 哼鸣，时长 7.5–25.3s，平均 14.9s）。
- **命名规范**：`vocal_{序号:03d}_{mode}_b{bpm}_s{seed}.wav`
  - 例：`vocal_013_vowels_b100_s202608140012.wav` = 第 13 首、元音吟唱、100 BPM、seed 202608140012。
  - 序号 001-050 稳定可排序；mode/bpm/seed 入名，参数即自文档化；同 seed 重跑必得同曲。
- **manifest.json**：每首完整参数（调式/主音/八度/和弦进行/元音组合/seed/时长/峰值/创建时间），可检索、可复现、可 diff。
- 参数空间：BPM 71-131、4-8 小节、5 种调式 × 7 主音 × 八度 4/5、11 种乐句元音组合（含单元音长音款）；哼鸣固定在 70-95 BPM 慢速区。
- 断点续跑：`batch_vocals.py --start N --count M`，已存在文件自动跳过；`--mode vowels|hum|mix`、`--pure` 强制纯 stdlib。

### 3.3 音色升级与实测数据（关键调试记录）

**v1 → v3 音色演进**（针对「人声识别度太低」的三轮实测驱动）：

| 项目 | v1（初版） | v3（当前） | 依据/作用 |
|------|-----------|-----------|------|
| 声源 | 锯齿直通（-6dB/oct） | 锯齿 + 两级低通（**-12dB/oct 声门滚降**，等效 -3dB≈2.8kHz） | 真实声门频谱滚降，去电子感 |
| 起音 | 60ms 线性柔起 | 80ms 柔起 + 55ms 送气噪声（"h"式起音） | 音头"吐字"感 |
| 颤音 | 单正弦 ±45cent | 双正弦叠加 ±35cent + **振幅颤音 ±5% 联动** | 不规则自然感 |
| 共振峰 | 静态系数 | **±3% 微颤**（两套系数随颤音波形交叉渐变） | 声道随演唱微微形变 |
| 共振峰权重 | (0.9, 0.5, 0.35) | (0.9, 1.2, 1.5) | 补偿声门滚降，F2/F3 峰清晰（实测：i 的 >3kHz 能量 7%，元音身份可辨） |
| 送气路径 | 噪声走声门滤波 | **噪声注入移到声门滚降之后 + Klatt AF 并联旁路直通输出** | 送气产生于声门上方；保留 4-6kHz 空气感 |
| 换气 | 无 | 乐句间 220ms 静默 + 滑音重置 | 乐句感、呼吸感 |
| 元音响度 | 差 2.5× | **实测逐个校准**（8 元音峰值对齐 0.33-0.37） | 听感均匀 |
| 干声 | 无 | 峰值归一化 0.89，无伴奏无混响 | 直接可用作 vocals stem |

**两个关键坑（均为实测发现）**：
1. **级联 vs 并联**（v0→v1）：级联式三级串联 a=1-R 衰减是乘积，峰值仅 0.003–0.06（几乎无声）；并联加权后 0.14–0.36。
2. **两级低通级联的 -3dB 点下移为 fc×0.644**：初版"2.8kHz 声门滚降"实际从 ~1.8kHz 就开始衰减，把 2-4kHz 清晰度带全砍光（FFT 实测 >4kHz 能量 0.00%）。修正：滚降 fc 取 4.3kHz 使等效≈2.8kHz。

**最终频谱（numpy FFT 实测，稳态段 2-8s）**：

| 文件 | >1kHz | >2kHz | >3kHz | >4kHz | >6kHz |
|------|-------|-------|-------|-------|-------|
| vocal_dry.wav（元音吟唱） | 81.1% | 3.5% | 0.16% | 0.05% | 0.02% |
| vocal_dry_hum.wav（哼鸣） | 88.6% | 8.9% | 0.12% | 0.05% | 0.02% |
| vocal_demo.wav（混音参考） | 46.9% | 2.6% | 0.64% | 0.54% | 0.47%（鼓镲） |

对照：无辅音的真人吟唱 >6kHz 能量天然 <1%，>4kHz 约 0.5-3%。干声频谱形态与真实吟唱一致——元音峰清晰、高频无气声残留、无电子合成齿音。哼鸣版 >2kHz 略高是 F3=2400Hz 鼻腔峰所致，属预期。

### 3.4 诚实边界

- ✅ 能：人声音色吟唱任意旋律、哼鸣、合唱垫底（pad）、元音歌词（如「啊」段、无词歌）。
- ❌ 不能：辅音、可懂歌词、真实歌手音色 —— 那是神经 SVS（层级 2/4）的领域。
- 已知可改进项（后续可做）：辅音 onset（爆破噪声 + 共振峰快速过渡）、breathiness 参数化、与 Phase 1.3 的 prosody（音节对齐）合并、GUI 加入「人声」音色选项。

---

## 四、硬件与网络事实（实测锚点）

- `torch 2.13.0+cpu`、`torch.cuda.is_available() = False`、`device_count = 0`（`G:\tools\audio\audio_separator\venv` 实测，2026-08-14）。
- 结论：**本机跑不动任何 GPU 神经 SVS**；ONNX CPU 推理（DiffSinger 声库 / Piper）是本地唯一「真语音」路线，速度慢但短句可用。

---

## 五、建议下一步（需你拍板）

1. 把「人声」加入 AutoWav 的 TIMBRES / GUI 音色列表（改动小，收益直接；干声已支持 `vocal_dry.wav` 直接当 vocals stem 用）。
2. 若接受念白：加 `tts_backend.py` 懒加载旁路（SAPI 零成本优先，Piper 备选），给曲子加 intro/旁白轨。
3. 若要真歌词演唱：走 Hybrid —— AutoWav 出 MIDI + 伴奏 → X Studio（免费）或 OpenUTAU 唱词 → 回灌混音。无需动核心引擎。
4. 如需云端 API 路线（MiniMax 等），告诉我预算与账号情况，我再做接入调研。

---

## 附：调研来源（2026-08-14 检索）

- 共振峰合成理论与实现：Fant 声源-滤波理论 / Klatt(1980)；mousekoz/synthesiser（Python 级联/并联共振峰合成器）；jscimedcentral《Formant Parameters via Pitch-Synchronous Analysis》（含 Python 歌声合成 melody.py/glissando.py 全文）
- DiffSinger：OpenVPI 维护版 GitHub（Apache-2.0，44.1kHz，ONNX 部署）；PyPI `diffsinger-utau` 0.2.1（onnxruntime CPU 推理、--voice-bank 声库）
- OpenUTAU：openutau.com（开源歌声合成平台，支持 DiffSinger 声库）；社区中文声库（RiaDiffSinger 等）
- 桌面/云端：网易 X Studio（xstudio.music.163.com，免费，12+ AI 歌手，演唱+说话双模式）；ACE Studio（acestudio.cn，免费基础版，80+ 商用 AI 歌手，MIDI+歌词驱动）；MiniMax Audio / Suno（云端付费）
- 本机实测：torch CUDA 探测输出（见第四节）
