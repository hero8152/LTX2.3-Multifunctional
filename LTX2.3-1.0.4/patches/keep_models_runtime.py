"""仅提供强制卸载 GPU 管线。「保持模型加载」功能已移除。"""

from __future__ import annotations

from typing import Any


def force_unload_gpu_pipeline(pipelines: Any) -> None:
    """释放推理管线占用的显存（切换 GPU、清理、LoRA 重建等场景）。"""
    try:
        pipelines.unload_gpu_pipeline()
    except Exception:
        try:
            type(pipelines).unload_gpu_pipeline(pipelines)
        except Exception:
            pass
