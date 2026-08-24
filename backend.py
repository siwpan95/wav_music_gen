"""
生成后端抽象层 — 纯 Python 标准库实现，零外部依赖

目的（Phase 0）:
  把「音乐生成」抽象为 GeneratorBackend 接口，默认实现 SymbolicBackend
  即现有 AutoWav 算法/符号引擎。未来可选的神经后端（如 ACEStepBackend）
  通过 register() 注册，CLI 用 --backend 选择。

硬约束:
  - 本模块不 import 任何第三方库。
  - SymbolicBackend.generate 仅做懒加载 import autowav，避免与 __main__ 冲突。
  - 神经后端的 requires_extra=True，缺失时由后端自身给出清晰降级提示，
    绝不污染核心引擎、不要求基础运行环境安装任何东西。
"""

from abc import ABC, abstractmethod


class GeneratorBackend(ABC):
    name = "base"
    requires_extra = False  # True 表示需要第三方库 / 显卡

    @abstractmethod
    def generate(self, spec: dict):
        """
        生成一首音乐。
        spec: dict —— 与 autowav.generate_music 兼容的关键字参数。
        返回: (output_path, params) 或 (output_path, params, score)
        """
        raise NotImplementedError


class SymbolicBackend(GeneratorBackend):
    name = "symbolic"
    requires_extra = False

    def generate(self, spec: dict):
        # 懒加载，避免与 `python autowav.py` 的 __main__ 模块冲突
        from autowav import generate_music
        return generate_music(**spec)


# ── 注册表 ──
_REGISTRY = {"symbolic": SymbolicBackend}


def register(name: str, cls):
    """注册一个后端实现。"""
    _REGISTRY[name] = cls


def available_backends() -> list:
    return list(_REGISTRY.keys())


def get_backend(name: str = "symbolic") -> GeneratorBackend:
    if name not in _REGISTRY:
        raise ValueError(
            f"未知后端 '{name}'。可用后端: {available_backends()}"
        )
    return _REGISTRY[name]()


def is_available(name: str) -> bool:
    return name in _REGISTRY
