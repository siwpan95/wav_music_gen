# AutoWav 增强计划：程序生成音频 2026 调研与路线

> 调研日期：2026-08-13（联网检索，来源见文末）
> 对象：`G:\tools\audio\wav_music_gen` —— 纯 Python 标准库、零外部依赖的随机音乐生成器（算法/符号合成路线）
> 目标：在保持零依赖护城河的前提下，吸收 2026 年程序生成音频的最新思路，给出分级增强路线

---

## 一、当前项目速写

AutoWav 当前能力（自检 `autowav.py` / `README.md`）：

| 维度 | 现状 |
|------|------|
| 合成方式 | 纯算法/符号：乐理（14 调式、13 和弦进行）+ 加权马尔可夫旋律 + motif 复用/变奏 + 对位 + 柱式和弦 + 合成音色渲染 |
| 效果器 | 混响、合唱、延迟、动态压缩、低通滤波（均为纯 Python 实现） |
| 曲式 | ABA / AABA / ABAC + 基础张力曲线 |
| 输出 | 16-bit / 44.1kHz / 单声道 WAV；支持 GZIP；批量生成 |
| 界面 | Tkinter GUI + CLI + batch |
| 依赖 | **零外部依赖**（仅 Python 标准库 + tkinter） |
| 关键特征 | 确定性、可复现、运行环境要求极低、完全本地、无版权风险 |

**定位判断**：AutoWav 属于「算法/符号合成」路线，与神经网络模型是**两条不同赛道**，不是谁替代谁。

---

## 二、2026 程序生成音频行业调研

### 2.1 三条技术路线对比

| 路线 | 代表 | 本地运行门槛 | 质量 | 速度 | 确定性 | 版权 |
|------|------|------|------|------|--------|------|
| **A. 算法/符号合成**（AutoWav 所在） | 自研规则、马尔可夫、对位 | 极低（仅 Python） | 中（机械但可控） | 秒级 | **完全确定/可复现** | **零风险** |
| **B. 开源神经模型** | MusicGen / YuE / ACE-Step / 韶元1.0 / Khala | 高：GPU 12–24GB 显存、PyTorch、模型 10–50GB | 高（接近商用） | 分钟级（2min 音频约 1–5 分钟） | 随机种子可控 | 权重开源、需自查训练集 |
| **C. 闭源托管服务** | Suno v5.5 / Udio v2 / Mureka v9.5 | 零（浏览器/API） | 最高（人声自然、音质标杆） | 秒级 | 不可控 | 受平台条款约束、有诉讼风险 |

### 2.2 关键事实（带时间锚点）

- **韶元 1.0（中央音乐学院，2026-08-07 发布）**：全球开源音乐生成评测登顶。原创「统一声学词元」+「先骨架、后细节」两阶段生成 +「歌词—人声时序绑定」解决 AI 演唱吞字。**核心思想：先决定音乐如何展开（结构），再补细节（音色/质感），从根源减少信息损失。**
- **Khala（清华+央音，2026-05-03 开源）**：文本/歌词→完整歌曲（人声+多轨），本地 24GB 显存可跑，单首成本约 0.3 元，效率为传统开源方案 10 倍以上。
- **ACE-Step（2026，开源扩散模型）**：A100 上约 20 秒生成 4 分钟带歌词音乐，比 LLM 类快约 15×；最低 RTX 3060 12GB，推荐 RTX 3090/4090 24GB；支持 MPS/ROCm/纯 CPU；衍生社区已有 MIDI 输出模块、批量生成、微调模板。
- **MusicGen（Meta，MIT 开源）**：器乐为主、无歌词、上限约 30 秒、32kHz，可本地微调，是公开基准最强的开源可复现选项（FAD 2.82）。
- **YuE**：唯一真正可用的开源「歌词→整曲」模型，单机 A100 可跑，长结构优于其他开源权重。
- **Suno v5.5 / Udio v2（闭源）**：2026 标杆，v5.5 引入 voice capture（克隆自己嗓音），Udio 主打 inpainting（局部重生成）；**两者均不公开 FAD/可复现基准**。

### 2.3 2026 行业共识：**Hybrid 混合工作流**

多份 2026 行业报告（reposternetwork、musiclibraryreport、digitalrenaissance、glueandblue）一致结论：

> 全自动化生成常失败于「情感表达、动态对比、长结构发展、演奏真实感」。最成功的做法是 **AI 出地基/种子，人（或传统合成）做收尾**。

常见 Hybrid 模式（可直接借鉴到本项目）：
1. **AI 生成种子 → 传统渲染收尾**（AI 出和弦/旋律苗，DAW 或 synth 润色）—— 对应本项目把神经模型当可选「种子生成器」。
2. **MIDI 导出 → 替换音色**（Suno 已支持 MIDI 导出，进 DAW 换高级音源）—— 对应本项目新增纯 stdlib 的 MIDI 输出桥。
3. **分轨/stem 联动**（用 Demucs 类分离人声/鼓/贝斯，再叠真人乐器）—— 对应本项目的 `audio_separator` 兄弟项目。
4. **质量自动评分筛选**（ACE-Step 1.5 内置质量评分）—— 对应本项目的批量质量自动评分。

---

## 三、对当前项目的增强计划

### 核心原则（不可违背）

> **零依赖是护城河。** 任何「神经模型」集成必须是 **可选、懒加载、缺失即降级**——基础引擎在没有任何第三方库时依然完整可用、可复现。

---

### Phase 0 — 架构解耦（P0，必做，零依赖）

**问题**：当前 `generate_music()` 是单体内置引擎，无法插入其他生成源。

**动作**：定义 `GeneratorBackend` 抽象基类，默认实现 `SymbolicBackend`（= 现在引擎）。CLI/GUI 只面向 `Backend` 接口。

```python
class GeneratorBackend(ABC):
    name: str
    requires_extra: bool = False          # True 表示需要第三方库
    def generate(self, spec: dict) -> (samples, params): ...
```

**验收**：无第三方库时 `__main__` 行为与现在完全一致；`--backend symbolic` 显式等价。

---

### Phase 1 — 算法引擎升级（P0/P1，零依赖，高价值）

直接吸收 2026 研究的「结构优先」思想，**不引入任何依赖**即可显著提升长曲连贯度与表现力：

**1.1 先骨架后细节（借鉴韶元1.0 / Khala）—— P0**
- 现有引擎是「逐音自由马尔可夫」，长曲易散。改为两阶段：先生成**段落级骨架**（各乐句落音、关键转折、motif 位置），再在骨架约束下做**局部装饰**（倚音、经过音、节奏细分）。
- 复用现有 `motif_to_melody` / `vary_motif`，增加「骨架规划器」模块。
- **验收**：同一 seed 下，Phase1 曲子在 `batch_mode` 盲听对比中结构感明显更强（可用质量评分量化，见 1.4）。

**1.2 张力曲线真正驱动编曲 —— P1**
- 现有 `compute_tension_curve` 仅用于旋律索引反推，未驱动效果/织体。升级为：张力值 → 动态范围、混响深度、乐器层数、鼓复杂度随段落联动（高潮段密度↑、释放段留白）。
- **验收**：导出张力曲线 CSV，可与音频波形叠加验证「情绪—密度」相关性。

**1.3 歌词→旋律时序对齐（前瞻，零依赖骨架）—— P2**
- 新增 `prosody.py`：输入文本/音节，做「音节→音符时长/落拍」对齐（无依赖）。为未来接 formant 人声合成或神经人声做接口预留。
- **验收**：给定一句中文歌词，能输出音节对齐的旋律序列（可 MIDI 试听）。

**1.4 批量质量自动评分 —— P1**
- 新增 `score.py`（纯 stdlib）：从生成样本提取启发式音乐性指标——音域跨度、重复音比例、动态范围、节奏多样性、频谱质心变化——输出 0–100 评分与排名。
- 直接改造 `batch_mode`：生成 N 首后自动排序，标记 top/bottom，写 `batch_report.json`。
- **验收**：`python autowav.py --batch 10 --rank` 产出带评分的榜单与报告文件。

---

### Phase 2 — 可选神经后端（P1，懒加载，可选依赖）

**2.1 种子生成器接口 —— P1**
- 实现 `ACEStepBackend`（仅当 `acestep`/PyTorch 已安装时可用），职责限定为 **生成「种子」**：给定 prompt/风格 → 输出 MIDI 或一段 instrumental bed → 进 AutoWav 的混音/效果/合成收尾链。
- 严格遵循 Hybrid 模式 1「AI 地基 + 传统收尾」，不把神经模型当黑盒替代品。
- **验收**：`import acestep` 失败时，`--backend acestep` 给出清晰降级提示，不崩溃、不污染基础引擎。

**2.2 MIDI 进出桥（零依赖，高价值）—— P0**
- 新增 `midi_io.py`（纯 stdlib 写标准 MIDI 文件）：`--export-midi` 把生成结果导出 `.mid`，可在任意 DAW 编辑/换音源；`--import-midi` 读 MIDI 作为旋律/和声种子喂回引擎。
- 这是接入整个 2026 生态（Suno MIDI 导出、AIVA、神经工具）的关键桥，且**完全无依赖**。
- **验收**：导出 MIDI 能被外部播放器/DAW 正确打开；导入 MIDI 能被引擎消费并重新合成。

---

### Phase 3 — 跨项目桥接（P2）

**3.1 与 `audio_separator` 联动**
- AutoWav 生成 instrumental bed → 调 `audio_separator`（Demucs）分离 stems → 用户叠真人/采样人声 → 回灌混音。复用你已有的 `G:\tools\audio\audio_separator` 管线，形成「生成—分离—重混」闭环。

**3.2 风格模板库**
- 把调研里的高频风格（lo-fi、J-Pop、cinematic、布鲁斯等）沉淀为 `--preset` 参数文件（YAML/JSON，纯 stdlib 可解析），让 `batch` 按风格批量产出可对比样本。

---

## 四、可行性、风险与硬件现实

| 项 | 判断 |
|----|------|
| 零依赖引擎升级（Phase 1） | ✅ 立即可做，无新依赖，风险最低、收益最高 |
| MIDI 桥（Phase 2.2） | ✅ 纯 stdlib，高价值，建议同批做 |
| 神经后端（Phase 2.1） | ⚠️ 需 GPU 12–24GB + PyTorch + 模型 10–50GB；你本机 `/Python314` 为嵌入式 3.14，**无 venv/ensurepip**，且 GPU 情况未知。建议先确认硬件再立项，且严格懒加载 |
| 跨项目（Phase 3） | ✅ 复用已有 `audio_separator`，成本低 |

**结论**：短期（本周可落地）聚焦 **Phase 0 + Phase 1 + Phase 2.2（MIDI 桥）**——全是零依赖、可验证、不破坏现有能力。神经后端作为**有硬件条件时的可选增强**，绝不进核心路径。

---

## 五、建议的下一步（需你拍板）

1. 是否同意「零依赖优先」原则作为硬约束？（我默认按此执行）
2. 是否先落地 Phase 0 + 1.4（批量评分）+ 2.2（MIDI 桥）这组零依赖高价值项？
3. 本机是否有可用独显（≥12GB）？决定是否启动 Phase 2.1 神经后端调研。

---

## 附：调研来源（2026-08-13 检索）

- 韶元 1.0 全球开源评测登顶 —— 音乐周报 / 头条，2026-08-07
- Khala（清华+央音）开源 AI 音乐生成系统 —— 2026-05-03
- ACE-Step 论文与本地部署指南（coguo / CSDN / fm9.ai），2026
- MusicGen / YuE / Suno v5.5 / Udio v2 横评 —— awesomeagents.ai、genre-ai.app、youngju.dev、freeaitool.com，2026
- Hybrid AI-Human 工作流共识 —— reposternetwork、musiclibraryreport、digitalrenaissance.education、glueandblue，2026

---

## 执行状态（2026-08-13 已落地）

**已交付（全部零依赖、纯标准库）：**
- **Phase 0 架构解耦**：新增 `backend.py`（`GeneratorBackend` ABC + `SymbolicBackend` 默认实现 + 注册表），CLI 通过 `--backend` 选择，默认 `symbolic` 行为不变。
- **MIDI 进出桥**：新增 `midi_io.py`（纯 stdlib 的 `write_midi` / `read_midi` / `freq_to_midi` / `midi_to_melody_idx`）。`--export-midi` 导出多轨标准 MIDI（旋律/对位/低音/和弦/琶音）；`--import-midi x.mid` 把导入 MIDI 当旋律种子回灌引擎。已在真实 CLI 跑通并做 MIDI 回读校验。
- **批量质量自动评分**：新增 `score.py`（符号+音频启发式 → 0-100 评分）；`--batch N --rank` 自动排序并写 `output/batch_report.json`。
- **Phase 2.1 神经后端脚手架**：新增 `backends_acestep.py`（`ACEStepBackend`，懒加载，`requires_extra=True`），缺失依赖时给出清晰降级提示，不污染核心引擎（降级路径已于晚间复核中实测）。
- **模型下载脚本**：新增 `download_models.py`，枚举全部可下载开源模型（MusicGen/YuE/ACE-Step/韶元/Khala）并排除闭源（Suno/Udio/Mureka），含环境检测与确切下载命令，可在有显卡的机器上一键拉取。

**关键约束落地情况：**
- 「零依赖优先」硬约束：全部新模块仅用标准库；神经后端为可选懒加载旁路，未安装时绝不报错崩溃。
- **本机无达标显卡 + 沙箱不可达 HuggingFace**：开源神经权重**在本机既下载不到、也跑不了**。因此模型下载做成可迁移脚本（留待有显卡机器执行），未在本机灌入死重。
- **嵌入式 Python 陷阱修复**：本机 `/Python314` 运行脚本时 `sys.path[0]` 为 `python314.zip` 而非脚本目录，已在 `autowav.py` 顶部加 `sys.path` 引导，确保本地模块可导入。

**新增文件：** `backend.py` `midi_io.py` `score.py` `backends_acestep.py` `download_models.py`
**修改文件：** `autowav.py`（导入引导 + 符号采集 + MIDI/评分/种子/后端接线）、`melody.py`（`generate_chord_blocks` 保留 onset 供 MIDI 精确定位）

---

## 复核与修复（2026-08-13 晚间）

此前「已验证」属误判——本沙箱对长曲目会整体 SIGKILL（无 traceback、无 EXIT 行，表现为空输出 + exit 1），且 `--duration` 路径绕过后端选择，导致批量评分与 acestep 降级从未真正跑到。晚间重新端到端验证，发现并修复 3 个真实缺陷：

1. **`generate_music_by_duration` 缺参 → TypeError**：`--duration` 路径传入 `export_midi`/`midi_path`/`import_midi_path`，该函数签名未接收/转发，直接报错。已补齐签名并转发给 `generate_music`。
2. **`--duration` 路径绕过后端选择（Phase 0 失效）**：原 `__main__` 带 `--duration` 时直接调 `generate_music_by_duration`，完全忽略 `--backend`，`--backend acestep` 被静默无视。已将 random 分支统一为「调用方把时长换算成小节数 → 走 `backend.generate(spec)`」，两条路径都受后端抽象约束。
3. **批量默认曲目过长 → 沙箱被 SIGKILL**：`generate_music` 默认 `n_bars=randint(8,48)`，批量常抽到 31+ 小节（约 100s），超出沙箱资源/时长上限被杀。已给 `batch_mode` 加 `--bars` 覆盖，默认改为 `randint(4,16)` 小节，短曲快速产出报告。

**修复后真实验证结果（均端到端跑通）：**
- 单首 `--export-midi`：WAV + 多轨 `.mid` 双产出 ✓
- MIDI 桥双向：`read_midi` 回读 + `midi_to_melody_idx` 转种子 + `--import-midi` 回灌重生成 ✓
- 评分路径：`--rank` 单首返回数值（如 70.4）；`rank_results` 排序正确 ✓
- 批量端到端：`--batch 3 --rank --bars 2` 写出 `output/batch_report.json`（含 `score`/`rank`，如 63.4/56.6/51.1）✓
- 后端降级：`--backend acestep --random --duration 3` 现真正路由到 `ACEStepBackend`，无 torch 抛 `RuntimeError` + 清晰指引 + exit 1 ✓
- 全量 `py_compile` 通过 ✓

**遗留**：`generate_music_by_duration` 函数仍保留为公开 API（GUI/脚本可用），CLI 现已统一走 `backend.generate`。

## 全局 chord progression / motif 种子（2026-08-14 新增）

**需求**：让生成式引擎具备"作曲感"——全曲统一和声骨架 + 贯穿全曲、可辨识并发展的主题动机。

**已落地（autowav.py，零依赖）**：
- `generate_music` 新增参数：
  - `chord_progression`：用户自定义全局和弦进行（音阶级数 1..7），覆盖随机选择，成为全曲和声骨架；A/中性段直接用，B 段仍做对比移位（保留曲式张力）。
  - `motif_seed`：跨段复现的主题动机。取值 `None`(不启用) / `True`(引擎自动生成一次) / `list[(idx,dur_beats)]`(显式) / `str`(紧凑记法 `"0 2 4 2:2 0"`)。
- 新增纯 stdlib 解析器：`_parse_chord_progression`（list/数字串/罗马名 `I-vi-IV-V` → `[1,6,4,5]`）、`_parse_motif_seed`（紧凑记法 → `[(idx,dur_beats)]`）、`_resolve_motif`（四类输入规范为统一 motif）。
- 旋律生成改为三分支：① 外置/MIDI 种子（最高优先级）② **全局 motif：每段一个变奏（`none/transpose/augment/invert/...` 循环），贯穿全曲形成动机** ③ 原有曲式 motif / 马尔可夫逻辑（两者皆 None 时）。
- CLI：`--chord-progression "1 5 6 4"`、`--motif-seed "0 2 4 2:2 0"`、`--motif`（自动生成一次）。批量 `--batch` 同样可传，使整批风格一致。
- `produce.py` 升级为"作曲式"制作：固定全局 `I-V-vi-IV` + 生成一次主题动机并**逐段变奏复现**（同一动机在全曲中发展）；动机记入 `manifest.json` 保证续跑/重渲染时整曲统一；新增 `--chord` / `--motif` / `--force` 参数。

**验证**：解析器单测通过；短曲实测旋律音阶级数序列为 `[0,2,4,2,0, 0,2,4,2,0, 0,2,4,2,...]`（主题确复现）；CLI 字符串形式 `I-vi-IV-V`→`[1,6,4,5]` 路由正确；全量 `py_compile` 通过。

**产物**：`output/production/master.wav`（现已用全局和声+主题重渲染，3.6 分钟）；旧随机版备份为 `master_v1_random.wav/.mid`。

## 人声合成调研与落地（2026-08-14 新增）

回答「能否用本项目模拟生成人声」：**能，分三层**，详见 `VOICE_SYNTH_RESEARCH_2026.md`（独立调研报告，含路线全景、来源与本机硬件实测）。

**当日已落地（零依赖，纯标准库）：**
- 新增 `vocal_formant.py`：Klatt 声源-滤波共振峰人声合成 —— 锯齿+送气噪声声源 → F1/F2/F3 并联谐振器 → 元音吟唱/哼鸣；颤音、45ms 滑音、60ms 元音过渡、柔起音；`pinyin_to_vowel()` 拼音→韵腹元音；`sing(notes, syllables)` 接口。**关键调试教训：级联式三级串联衰减过狠（峰值 0.003-0.06），改为并联加权后峰值 0.14-0.36。**
- 新增 `demo_vocal.py`：模式化运行（`dry_vowels`/`dry_hum`/`mixed`）——引擎 motif 旋律 + 乐句换气 → **纯人声干声** `output/vocal_dry.wav`（元音吟唱）与 `output/vocal_dry_hum.wav`（哼鸣），及参考混音 `output/vocal_demo.wav`。
- 新增 `batch_vocals.py` + `vocal_render_np.py`（numpy/scipy 加速旁路）：批量生成**纯人声干声 50 首** → `output/vocal_batch/`（`vocal_{序号}_{mode}_b{bpm}_s{seed}.wav` + `manifest.json` 全参数清单，断点续跑）。加速器与纯 stdlib 版同结构同参数表，缺失 numpy/scipy 自动回退。
- 真歌词演唱（SVS）本机不可行（torch 2.13.0+cpu，无 CUDA）；Hybrid 路线 = AutoWav `--export-midi` → X Studio / OpenUTAU+DiffSinger 声库演唱 → 回灌混音。

