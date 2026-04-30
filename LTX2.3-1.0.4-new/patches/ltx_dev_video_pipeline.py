"""Patch-side wrapper for LTX dev checkpoints.

The desktop Fast wrapper is built around ``DistilledPipeline``.  Dev checkpoints
need the full TI2V two-stage pipeline; otherwise LoRA keys can match the wrong
stage shape and fail during FP8 fusion.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Final

import torch

from api_types import ImageConditioningInput
from services.ltx_pipeline_common import (
    default_tiling_config,
    encode_video_output,
    video_chunks_number,
)
from services.services_utils import AudioOrNone, TilingConfigType, device_supports_fp8


class LTXDevVideoPipeline:
    pipeline_kind: Final = "dev"

    def __init__(
        self,
        checkpoint_path: str,
        gemma_root: str | None,
        upsampler_path: str,
        distilled_lora_path: str,
        device: torch.device,
        loras: list[object] | tuple[object, ...] | None = None,
    ) -> None:
        from ltx_core.loader import LoraPathStrengthAndSDOps
        from ltx_core.quantization import QuantizationPolicy
        from ltx_pipelines.ti2vid_two_stages import TI2VidTwoStagesPipeline
        from ltx_pipelines.utils.constants import detect_params

        self._checkpoint_path = checkpoint_path
        self._device = device
        self._params = detect_params(checkpoint_path)

        quantization = None
        if "fp8" in checkpoint_path.lower() and device_supports_fp8(device):
            try:
                quantization = QuantizationPolicy.fp8_scaled_mm()
            except Exception as exc:
                print(f"[PATCH] Dev FP8 scaled-mm 不可用，回退 fp8_cast: {exc}")
                quantization = QuantizationPolicy.fp8_cast()

        distilled_lora = []
        checkpoint_name = Path(checkpoint_path).name.lower()
        distilled_lora_name = Path(distilled_lora_path).name.lower() if distilled_lora_path else ""
        incompatible_builtin_lora = (
            "2.3" in checkpoint_name
            and ("2-19b" in distilled_lora_name or "19b" in distilled_lora_name)
        )
        if incompatible_builtin_lora:
            print(
                "[PATCH] Dev two-stage: 跳过不匹配的内置 distilled LoRA "
                f"({distilled_lora_name})，当前 checkpoint 是 {checkpoint_name}"
            )
        elif distilled_lora_path and Path(distilled_lora_path).is_file():
            distilled_lora = [
                LoraPathStrengthAndSDOps(
                    path=distilled_lora_path,
                    strength=1.0,
                    sd_ops=None,
                )
            ]
        elif distilled_lora_path:
            print(
                "[PATCH] Dev two-stage: distilled LoRA 不存在，跳过内置 stage-2 distilled LoRA: "
                f"{distilled_lora_path}"
            )

        self.pipeline = TI2VidTwoStagesPipeline(
            checkpoint_path=checkpoint_path,
            distilled_lora=distilled_lora,
            spatial_upsampler_path=upsampler_path,
            gemma_root=gemma_root or "",
            loras=tuple(loras or ()),
            device=device,
            quantization=quantization,
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
        try:
            from low_vram_runtime import get_streaming_prefetch_count

            streaming_prefetch_count = get_streaming_prefetch_count()
        except Exception:
            streaming_prefetch_count = None

        params = self._params
        return self.pipeline(
            prompt=prompt,
            negative_prompt="",
            seed=seed,
            height=height,
            width=width,
            num_frames=num_frames,
            frame_rate=frame_rate,
            num_inference_steps=params.num_inference_steps,
            video_guider_params=params.video_guider_params,
            audio_guider_params=params.audio_guider_params,
            images=[_LtxImageInput(img.path, img.frame_idx, img.strength) for img in images],
            tiling_config=tiling_config,
            streaming_prefetch_count=streaming_prefetch_count,
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
