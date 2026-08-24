"""
下载开源神经音乐模型权重 — 可迁移脚本（纯标准库）

背景:
  本机（G:\tools 所在机器）**没有 >=12GB 显存的独立显卡**，且当前沙箱
  **无法访问 HuggingFace**（curl 探测 http_code=000）。因此这些权重
  在本机既下载不到、也跑不了。本脚本用于在「有显卡 + 能联网」的机器上
  一键拉取 AutoWav 增强计划里提到的、可下载的开源模型。

可下载（开源权重）:
  - MusicGen (Meta, MIT)         facebook/musicgen-small / -medium / -large
  - YuE (开源歌词->整曲)          m-a-p/YuE
  - ACE-Step (开源扩散)           ACE-Step/ACE-Step
  - 韶元 1.0 (央音, 开源)         CCMT/SHAO-1.0 (示例仓库名, 以官方为准)
  - Khala (清华+央音, 开源)       thu-ccm/Khala (示例仓库名, 以官方为准)

不可下载（闭源托管，仅 API/网页，无权重）:
  - Suno v5.5 / Udio v2 / Mureka v9.5  —— 不在此脚本范围。

用法:
  python download_models.py            # 交互式选择要下载的模型
  python download_models.py --all      # 尝试下载全部可下载模型
  python download_models.py musicgen   # 只下载指定模型
  python download_models.py --check    # 仅检测网络/工具是否就绪

注意: 下载前请确保目标机器满足对应模型的显存/磁盘要求，否则即便下载
      成功也无法加载推理。
"""

import subprocess
import sys
import shutil
import urllib.request


# 模型清单: (key, 显示名, HF 仓库或 git 地址, 备注)
MODELS = [
    ("musicgen", "MusicGen (Meta, MIT)",
     "https://huggingface.co/facebook/musicgen-small",
     "器乐为主, 无歌词; 需 audiocraft+PyTorch; 最小 musicgen-small ~1-2GB"),
    ("yue", "YuE (开源歌词->整曲)",
     "https://huggingface.co/m-a-p/YuE",
     "需单卡 A100 级; 权重较大; 长结构优于其他开源"),
    ("acestep", "ACE-Step (开源扩散)",
     "https://huggingface.co/ACE-Step/ACE-Step",
     "A100 上约 20s 生成 4 分钟; 推荐 RTX3090/4090 24GB; 支持 MPS/ROCm/CPU"),
    ("shao", "韶元 1.0 (央音, 开源)",
     "https://huggingface.co/CCMT/SHAO-1.0",
     "2026-08 全球开源评测登顶; 以央音官方发布仓库为准"),
    ("khala", "Khala (清华+央音, 开源)",
     "https://huggingface.co/thu-ccm/Khala",
     "文本/歌词->完整歌曲; 本地 24GB 显存可跑; 以官方发布仓库为准"),
]


def _have_hf_cli() -> bool:
    # 新官方 CLI 为 `hf`（已替代废弃的 huggingface-cli）
    return shutil.which("hf") is not None or shutil.which("huggingface-cli") is not None


def _hf_reachable() -> bool:
    try:
        urllib.request.urlopen("https://huggingface.co", timeout=8)
        return True
    except Exception:
        return False


def check_env():
    print("=== 环境检测 ===")
    print(f"  hf CLI: {'已安装' if _have_hf_cli() else '未安装 (pip install -U hf-hub)'}")
    print(f"  HuggingFace 可达: {'是' if _hf_reachable() else '否 (本沙箱/网络受限)'}")
    print("  提示: 神经模型需要 >=12GB 显存 GPU 才能本地推理。")
    return _have_hf_cli() and _hf_reachable()


def download(key: str, repo: str):
    print(f"\n>>> 下载 {key}: {repo}")
    if not _hf_reachable():
        print("  ✗ HuggingFace 不可达，跳过（在能联网的机器上运行本脚本）。")
        return False
    if not _have_hf_cli():
        print("  ✗ 未找到 hf CLI（已替代废弃的 huggingface-cli）。请先安装: pip install -U hf-hub")
        return False
    # 默认下载到 ./models/<key>
    out = f"models/{key}"
    cmd = ["hf", "download", repo, "--local-dir", out]
    print("  命令:", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
        print(f"  ✓ 已下载到 {out}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ✗ 下载失败: {e}")
        return False


def main():
    args = sys.argv[1:]
    if "--check" in args:
        check_env()
        return

    if "--all" in args:
        ready = check_env()
        if not ready:
            print("\n环境未就绪，仅打印计划命令，不实际下载。")
        for key, _, repo, _ in MODELS:
            if ready:
                download(key, repo)
        return

    # 指定模型
    want = [a for a in args if a in {m[0] for m in MODELS}]
    if not want:
        print("选择要下载的模型（输入序号，空格分隔；all=全部；check=检测环境）:")
        for i, (k, name, _, note) in enumerate(MODELS, 1):
            print(f"  {i}. {k:10s} {name}\n       {note}")
        sel = input("> ").strip().split()
        if "all" in sel:
            want = [m[0] for m in MODELS]
        else:
            idxs = [int(x) for x in sel if x.isdigit()]
            want = [MODELS[i - 1][0] for i in idxs if 0 < i <= len(MODELS)]

    ready = check_env()
    for key, _, repo, _ in MODELS:
        if key in want:
            if ready:
                download(key, repo)
            else:
                print(f"\n(跳过) {key}: {repo}  —— 环境未就绪，请在达标机器上运行。")


if __name__ == "__main__":
    main()
