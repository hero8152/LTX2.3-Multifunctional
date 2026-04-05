"""
在 SingleGPUModelBuilder.build() 时合并「当前请求」的用户 LoRA。

桌面版 Fast 管线往往只在 model_ledger 上挂 loras，真正 load 权重时仍用
初始化时的空 loras Builder；此处对 DiT/Transformer 的 Builder 在 build 前注入。
"""

from __future__ import annotations

import contextvars
import logging
from dataclasses import replace
from typing import Any

logger = logging.getLogger(__name__)

# 当前 HTTP 请求/生成任务中要额外融合的 LoRA（LoraPathStrengthAndSDOps 元组）
_pending_user_loras: contextvars.ContextVar[tuple[Any, ...] | None] = contextvars.ContextVar(
    "ltx_pending_user_loras", default=None
)

_HOOK_INSTALLED = False


def pending_loras_token(loras: tuple[Any, ...] | None):
    """返回 contextvar Token，供 finally reset；loras 为 None 表示本任务不用额外 LoRA。"""
    return _pending_user_loras.set(loras)


def reset_pending_loras(token: contextvars.Token | None) -> None:
    if token is not None:
        _pending_user_loras.reset(token)


def _get_pending() -> tuple[Any, ...] | None:
    return _pending_user_loras.get()


def _is_ltx_diffusion_transformer_builder(builder: Any) -> bool:
    """避免给 Gemma / VAE / Upsampler 的 Builder 误加视频 LoRA。"""
    cfg = getattr(builder, "model_class_configurator", None)
    if cfg is None:
        return False
    name = getattr(cfg, "__name__", "") or ""
    # 排除明显非 DiT 的
    for bad in (
        "Gemma",
        "VideoEncoder",
        "VideoDecoder",
        "AudioEncoder",
        "AudioDecoder",
        "Vocoder",
        "EmbeddingsProcessor",
        "LatentUpsampler",
    ):
        if bad in name:
            return False
    try:
        from ltx_core.model.transformer import LTXModelConfigurator

        if isinstance(cfg, type):
            try:
                if issubclass(cfg, LTXModelConfigurator):
                    return True
            except TypeError:
                pass
        if cfg is LTXModelConfigurator:
            return True
    except ImportError:
        pass
    # 兜底：LTX 主 transformer 配置器命名习惯（排除已列出的 VAE/Gemma）
    return "LTX" in name and "ModelConfigurator" in name


def install_lora_build_hook() -> None:
    global _HOOK_INSTALLED
    if _HOOK_INSTALLED:
        return
    try:
        from ltx_core.loader.single_gpu_model_builder import SingleGPUModelBuilder
    except ImportError:
        logger.warning("lora_build_hook: 无法导入 SingleGPUModelBuilder，跳过")
        return

    _orig_build = SingleGPUModelBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any) -> Any:
        extra = _get_pending()
        if extra and _is_ltx_diffusion_transformer_builder(self):
            have = {getattr(x, "path", None) for x in self.loras}
            add = tuple(x for x in extra if getattr(x, "path", None) not in have)
            if add:
                merged = (*tuple(self.loras), *add)
                self = replace(self, loras=merged)
                logger.info(
                    "lora_build_hook: 已向 DiT Builder 合并 %d 个用户 LoRA: %s",
                    len(add),
                    [getattr(x, "path", x) for x in add],
                )
        return _orig_build(self, *args, **kwargs)

    SingleGPUModelBuilder.build = build  # type: ignore[method-assign]
    _HOOK_INSTALLED = True
    logger.info("lora_build_hook: 已挂载 SingleGPUModelBuilder.build")
