"""
ACEStepBackend — 可选神经后端（种子生成器），懒加载脚手架

定位（Phase 2.1，严格可选）:
  - 仅当 acestep + PyTorch + 可用 GPU(>=12GB) 已具备时才能工作。
  - 职责限定为「种子生成器」: 给定 prompt/风格，产出 MIDI 或一段
    instrumental bed，再交 AutoWav 的混音/效果/合成做传统收尾
    （对应 2026 Hybrid 工作流: AI 出地基 + 传统收尾）。
  - 本机无达标显卡、且 HF 在本沙箱不可达，因此本文件只搭建接口与
    清晰的降级路径；实际推理实现在有显卡的机器上接入。

硬约束:
  - 模块顶层绝不 import torch / acestep（避免污染、避免无 GPU 时崩溃）。
  - 仅在 generate() 内懒加载；缺失即抛出带指引的 RuntimeError。
"""

from backend import GeneratorBackend, register


class ACEStepBackend(GeneratorBackend):
    name = "acestep"
    requires_extra = True

    def generate(self, spec: dict):
        # 仅在真正使用时才尝试加载重依赖
        try:
            import torch  # noqa: F401
            from acestep.pipeline import ACEStepPipeline  # noqa: F401
        except Exception as exc:  # 未安装 / 无显卡
            raise RuntimeError(
                "ACEStepBackend 需要: acestep + PyTorch + 可用 GPU(>=12GB 显存)。\n"
                "当前环境未满足（本机无达标独显 / 依赖未安装），已自动降级。\n"
                "在具备显卡的机器上启用:\n"
                "  1) pip install torch acestep\n"
                "  2) 参考 download_models.py 拉取权重\n"
                "  3) 再运行: python autowav.py --backend acestep ...\n"
                "注意: 即使下载了权重，本机也无法本地推理（无达标 GPU）。"
            ) from exc

        # ── 以下为接入点（有 GPU 时实现）──
        # 思路:
        #   1. 用 ACEStepPipeline 生成 instrumental bed / MIDI（种子）
        #   2. 把种子转成 AutoWav 的旋律/和声序列
        #   3. 调用 SymbolicBackend 做混音/效果/合成收尾
        # 此处留空，确保默认不执行任何重逻辑、不产生误用。
        raise NotImplementedError(
            "ACEStepBackend 的种子推理管线需在有 GPU 的机器上实现。\n"
            "脚手架已就位: 依赖缺失时会优雅降级，不会污染核心引擎。"
        )


# 注册到后端表
register("acestep", ACEStepBackend)
