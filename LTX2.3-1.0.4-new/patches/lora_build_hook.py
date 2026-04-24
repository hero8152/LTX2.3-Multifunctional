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

import torch

logger = logging.getLogger(__name__)

# 当前 HTTP 请求/生成任务中要额外融合的 LoRA（LoraPathStrengthAndSDOps 元组）
_pending_user_loras: contextvars.ContextVar[tuple[Any, ...] | None] = contextvars.ContextVar(
    "ltx_pending_user_loras", default=None
)

_HOOK_INSTALLED = False
_FP8_LORA_PATCH_INSTALLED = False


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


def _install_fp8_lora_fusion_patch() -> None:
    """Make LTX's scaled-FP8 LoRA fusion tolerant of checkpoint layout variants."""
    global _FP8_LORA_PATCH_INSTALLED
    if _FP8_LORA_PATCH_INSTALLED:
        return
    try:
        import ltx_core.loader.fuse_loras as fuse_mod
    except ImportError:
        return

    _orig_scaled = getattr(fuse_mod, "_fuse_delta_with_scaled_fp8", None)
    if _orig_scaled is None:
        return

    def _quantize_preserve_layout(tensor: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        tensor_fp32 = tensor.to(torch.float32)
        fp8_min = torch.finfo(torch.float8_e4m3fn).min
        fp8_max = torch.finfo(torch.float8_e4m3fn).max
        max_abs = torch.amax(torch.abs(tensor_fp32))
        if max_abs == 0:
            max_abs = torch.ones((), dtype=torch.float32, device=tensor_fp32.device)
        scale = fp8_max / max_abs
        quantized = torch.clamp(tensor_fp32 * scale, min=fp8_min, max=fp8_max).to(torch.float8_e4m3fn)
        return quantized, scale.reciprocal()

    def _patched_scaled(deltas: torch.Tensor, weight: torch.Tensor, key: str, scale_key: str, model_sd: Any) -> dict[str, torch.Tensor]:
        weight_scale = model_sd.sd[scale_key].to(device=weight.device)
        delta = deltas.to(device=weight.device, dtype=torch.float32)
        weight_fp32 = weight.to(torch.float32)

        # Standard LTX scaled-FP8 layout: checkpoint stores (in, out), LoRA delta is (out, in).
        normal_layout = weight_fp32.t() * weight_scale
        if normal_layout.shape == delta.shape:
            new_weight = normal_layout + delta
            new_fp8_weight, new_weight_scale = fuse_mod.quantize_weight_to_fp8_per_tensor(new_weight)
            return {key: new_fp8_weight, scale_key: new_weight_scale}
        if normal_layout.shape == delta.t().shape:
            new_weight = normal_layout + delta.t()
            new_fp8_weight, new_weight_scale = fuse_mod.quantize_weight_to_fp8_per_tensor(new_weight)
            return {key: new_fp8_weight, scale_key: new_weight_scale}

        # Some FP8 checkpoints already arrive in the module/storage layout.
        storage_layout = weight_fp32 * weight_scale
        if storage_layout.shape == delta.shape:
            new_weight = storage_layout + delta
            new_fp8_weight, new_weight_scale = _quantize_preserve_layout(new_weight)
            return {key: new_fp8_weight, scale_key: new_weight_scale}
        if storage_layout.shape == delta.t().shape:
            new_weight = storage_layout + delta.t()
            new_fp8_weight, new_weight_scale = _quantize_preserve_layout(new_weight)
            return {key: new_fp8_weight, scale_key: new_weight_scale}

        print(
            "[PATCH] FP8 LoRA shape mismatch, skip layer: "
            f"{key}, weight={tuple(weight.shape)}, delta={tuple(deltas.shape)}, "
            f"normal={tuple(normal_layout.shape)}, storage={tuple(storage_layout.shape)}"
        )
        return {}

    fuse_mod._fuse_delta_with_scaled_fp8 = _patched_scaled
    _FP8_LORA_PATCH_INSTALLED = True
    logger.info("lora_build_hook: 已挂载 scaled-FP8 LoRA 融合兼容补丁")


def install_lora_build_hook() -> None:
    global _HOOK_INSTALLED
    _install_fp8_lora_fusion_patch()
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
