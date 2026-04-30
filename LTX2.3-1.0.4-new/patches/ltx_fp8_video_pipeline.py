"""Fast pipeline wrapper for pre-quantized FP8 distilled checkpoints.

The stock desktop wrapper uses ``QuantizationPolicy.fp8_cast()``, which is
meant to cast BF16 checkpoints to FP8 while loading.  Pre-quantized FP8
checkpoints already contain FP8 weights plus weight/input scales, so casting
them again can produce valid-looking inference that decodes to black frames.

This wrapper loads those checkpoints with the scaled-FP8 state-dict/module
layout.  When TensorRT-LLM is not available, its FP8Linear forward falls back
to a PyTorch dequantize-then-linear path, keeping FP8 storage while avoiding
black output.
"""

from __future__ import annotations

from collections.abc import Iterator
import os
from types import SimpleNamespace
from typing import Any, Final, cast

import torch
from torch import nn

from api_types import ImageConditioningInput
from services.ltx_pipeline_common import (
    default_tiling_config,
    encode_video_output,
    video_chunks_number,
)
from services.services_utils import AudioOrNone, TilingConfigType


_FP8_FALLBACK_INSTALLED = False


def _install_fp8linear_torch_fallback() -> None:
    global _FP8_FALLBACK_INSTALLED
    if _FP8_FALLBACK_INSTALLED:
        return

    from ltx_core.quantization.fp8_scaled_mm import FP8Linear

    def _fallback_forward(self: Any, x: torch.Tensor) -> torch.Tensor:
        weight_scale = self.weight_scale.to(dtype=x.dtype, device=x.device)
        weight = (self.weight.to(dtype=x.dtype) * weight_scale).t().contiguous()
        bias = self.bias
        if bias is not None and bias.dtype != x.dtype:
            bias = bias.to(dtype=x.dtype, device=x.device)
        return torch.nn.functional.linear(x, weight, bias)

    # TensorRT-LLM is not bundled in LTX Desktop, so use a deterministic PyTorch
    # fallback for scaled FP8 checkpoints instead of silently ignoring scales.
    FP8Linear.forward = _fallback_forward  # type: ignore[method-assign]
    _FP8_FALLBACK_INSTALLED = True


def _fp8_layer_names(checkpoint_path: str) -> frozenset[str]:
    from safetensors import safe_open

    names: set[str] = set()
    with safe_open(checkpoint_path, framework="pt", device="cpu") as handle:
        for key in handle.keys():
            if not key.endswith(".weight_scale"):
                continue
            layer_name = key.removeprefix("model.diffusion_model.").removesuffix(
                ".weight_scale"
            )
            if layer_name.startswith("transformer_blocks."):
                names.add(layer_name)
    return frozenset(names)


def _scaled_fp8_quantization_policy(checkpoint_path: str) -> Any:
    from ltx_core.loader.module_ops import ModuleOps
    from ltx_core.loader.sd_ops import KeyValueOperationResult, SDOps
    from ltx_core.model.transformer import LTXModel
    from ltx_core.quantization.fp8_scaled_mm import FP8Linear

    fp8_layers = _fp8_layer_names(checkpoint_path)

    def transpose_fp8_weight(
        key: str, value: torch.Tensor
    ) -> list[KeyValueOperationResult]:
        layer_name = key.removesuffix(".weight")
        if layer_name in fp8_layers and value.dim() == 2:
            return [KeyValueOperationResult(key, value.t())]
        return [KeyValueOperationResult(key, value)]

    def convert_fp8_layers(model: nn.Module) -> nn.Module:
        if not isinstance(model, LTXModel):
            return model
        replacements: list[tuple[nn.Module, str, nn.Linear]] = []
        for name, module in model.named_modules():
            if name not in fp8_layers or not isinstance(module, nn.Linear):
                continue
            parent_name, attr_name = name.rsplit(".", 1)
            replacements.append((model.get_submodule(parent_name), attr_name, module))
        for parent, attr_name, linear in replacements:
            setattr(
                parent,
                attr_name,
                FP8Linear(
                    in_features=linear.in_features,
                    out_features=linear.out_features,
                    bias=linear.bias is not None,
                    device=linear.weight.device,
                ),
            )
        return model

    _install_fp8linear_torch_fallback()
    return SimpleNamespace(
        sd_ops=SDOps("fp8_selected_layers_transpose").with_kv_operation(
            transpose_fp8_weight,
            key_prefix="transformer_blocks.",
            key_suffix=".weight",
        ),
        module_ops=(
            ModuleOps(
                name="fp8_prepare_selected_layers_for_loading",
                matcher=lambda model: isinstance(model, LTXModel),
                mutator=convert_fp8_layers,
            ),
        ),
    )


class LTXFp8VideoPipeline:
    pipeline_kind: Final = "fast-fp8"

    @staticmethod
    def create(
        checkpoint_path: str,
        gemma_root: str | None,
        upsampler_path: str,
        device: torch.device,
    ) -> "LTXFp8VideoPipeline":
        return LTXFp8VideoPipeline(
            checkpoint_path=checkpoint_path,
            gemma_root=gemma_root,
            upsampler_path=upsampler_path,
            device=device,
        )

    def __init__(
        self,
        checkpoint_path: str,
        gemma_root: str | None,
        upsampler_path: str,
        device: torch.device,
        **_ignored: Any,
    ) -> None:
        from ltx_pipelines.distilled import DistilledPipeline

        self._checkpoint_path = checkpoint_path
        self._gemma_root = gemma_root
        self._upsampler_path = upsampler_path
        self._device = device
        self._quantization = _scaled_fp8_quantization_policy(checkpoint_path)

        self.pipeline = DistilledPipeline(
            distilled_checkpoint_path=checkpoint_path,
            gemma_root=cast(str, gemma_root),
            spatial_upsampler_path=upsampler_path,
            loras=[],
            device=device,
            quantization=self._quantization,
        )

    def _run_inference(
        self,
        prompt: str,
        seed: int,
        height: int,
        width: int,
        num_frames: int,
        frame_rate: float,
        images: list[ImageConditioningInput],
        tiling_config: TilingConfigType,
    ) -> tuple[torch.Tensor | Iterator[torch.Tensor], AudioOrNone]:
        from ltx_pipelines.utils.args import ImageConditioningInput as _LtxImageInput

        return self.pipeline(
            prompt=prompt,
            seed=seed,
            height=height,
            width=width,
            num_frames=num_frames,
            frame_rate=frame_rate,
            images=[
                _LtxImageInput(img.path, img.frame_idx, img.strength)
                for img in images
            ],
            tiling_config=tiling_config,
            streaming_prefetch_count=2,
        )

    @torch.inference_mode()
    def generate(
        self,
        prompt: str,
        seed: int,
        height: int,
        width: int,
        num_frames: int,
        frame_rate: float,
        images: list[ImageConditioningInput],
        output_path: str,
    ) -> None:
        tiling_config = default_tiling_config()
        video, audio = self._run_inference(
            prompt=prompt,
            seed=seed,
            height=height,
            width=width,
            num_frames=num_frames,
            frame_rate=frame_rate,
            images=images,
            tiling_config=tiling_config,
        )
        chunks = video_chunks_number(num_frames, tiling_config)
        encode_video_output(
            video=video,
            audio=audio,
            fps=int(frame_rate),
            output_path=output_path,
            video_chunks_number_value=chunks,
        )

    @torch.inference_mode()
    def warmup(self, output_path: str) -> None:
        warmup_frames = 9
        tiling_config = default_tiling_config()

        try:
            video, audio = self._run_inference(
                prompt="test warmup",
                seed=42,
                height=256,
                width=384,
                num_frames=warmup_frames,
                frame_rate=8,
                images=[],
                tiling_config=tiling_config,
            )
            chunks = video_chunks_number(warmup_frames, tiling_config)
            encode_video_output(
                video=video,
                audio=audio,
                fps=8,
                output_path=output_path,
                video_chunks_number_value=chunks,
            )
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def compile_transformer(self) -> None:
        from ltx_pipelines.distilled import DistilledPipeline

        self.pipeline = DistilledPipeline(
            distilled_checkpoint_path=self._checkpoint_path,
            gemma_root=cast(str, self._gemma_root),
            spatial_upsampler_path=self._upsampler_path,
            loras=[],
            device=self._device,
            quantization=self._quantization,
            torch_compile=True,
        )
