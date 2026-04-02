"""将用户 LoRA 注入 Fast 视频管线：兼容 ModelLedger 与 LTX-2 DiffusionStage/Builder。"""

from __future__ import annotations

import inspect
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _lora_init_kwargs(
    pipeline_cls: type, loras: list[Any] | tuple[Any, ...]
) -> dict[str, Any]:
    if not loras:
        return {}
    try:
        sig = inspect.signature(pipeline_cls.__init__)
        names = sig.parameters.keys()
    except (TypeError, ValueError):
        return {}
    tup = tuple(loras)
    for key in ("loras", "lora", "extra_loras", "user_loras"):
        if key in names:
            return {key: tup}
    return {}


def inject_loras_into_fast_pipeline(ltx_pipe: Any, loras: list[Any] | tuple[Any, ...]) -> int:
    """在已构造的管线上尽量把 LoRA 写进会参与 build 的 Builder / ledger。返回成功写入的处数。"""
    if not loras:
        return 0
    tup = tuple(loras)
    patched = 0
    visited: set[int] = set()

    def visit(obj: Any, depth: int) -> None:
        nonlocal patched
        if obj is None or depth > 10:
            return
        oid = id(obj)
        if oid in visited:
            return
        visited.add(oid)

        # ModelLedger.loras（旧桌面）
        ml = getattr(obj, "model_ledger", None)
        if ml is not None:
            try:
                ml.loras = tup
                patched += 1
                logger.info("LoRA: 已设置 model_ledger.loras")
            except Exception as e:
                logger.debug("model_ledger.loras: %s", e)

        # SingleGPUModelBuilder.with_loras（常见与变体属性名）
        for holder in (obj, ml):
            if holder is None:
                continue
            candidates: list[Any] = []
            for attr in (
                "_transformer_builder",
                "transformer_builder",
                "_model_builder",
                "model_builder",
            ):
                tb = getattr(holder, attr, None)
                if tb is not None:
                    candidates.append((attr, tb))
            try:
                for attr in dir(holder):
                    al = attr.lower()
                    if "transformer" in al and "builder" in al and attr not in (
                        "_transformer_builder",
                        "transformer_builder",
                    ):
                        tb = getattr(holder, attr, None)
                        if tb is not None:
                            candidates.append((attr, tb))
            except Exception:
                pass
            for attr, tb in candidates:
                if hasattr(tb, "with_loras"):
                    try:
                        new_tb = tb.with_loras(tup)
                        setattr(holder, attr, new_tb)
                        patched += 1
                        logger.info("LoRA: 已更新 %s.with_loras", attr)
                    except Exception as e:
                        logger.debug("with_loras %s: %s", attr, e)

        # DiffusionStage（类名或 isinstance）
        is_diffusion = type(obj).__name__ == "DiffusionStage"
        if not is_diffusion:
            try:
                from ltx_pipelines.utils.blocks import DiffusionStage as _DS

                is_diffusion = isinstance(obj, _DS)
            except ImportError:
                pass
        if is_diffusion:
            tb = getattr(obj, "_transformer_builder", None)
            if tb is not None and hasattr(tb, "with_loras"):
                try:
                    obj._transformer_builder = tb.with_loras(tup)
                    patched += 1
                    logger.info("LoRA: 已写入 DiffusionStage._transformer_builder")
                except Exception as e:
                    logger.debug("DiffusionStage: %s", e)

        # 常见嵌套属性
        for name in (
            "pipeline",
            "inner",
            "_inner",
            "fast_pipeline",
            "_pipeline",
            "stage_1",
            "stage_2",
            "stage",
            "_stage",
            "stages",
            "diffusion",
            "_diffusion",
        ):
            try:
                ch = getattr(obj, name, None)
            except Exception:
                continue
            if ch is not None and ch is not obj:
                visit(ch, depth + 1)

        if isinstance(obj, (list, tuple)):
            for item in obj[:8]:
                visit(item, depth + 1)

    root = getattr(ltx_pipe, "pipeline", ltx_pipe)
    visit(root, 0)
    return patched
