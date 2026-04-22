"""Standalone TTS worker process for VoxCPM-based generation."""

from __future__ import annotations

# === [核心修复] 彻底封印 PyTorch 的所有动态编译机制 ===
import os
# 1. 禁用 Dynamo 编译器 (PyTorch 2.x)
os.environ["TORCH_COMPILE_DISABLE"] = "1"
# 2. 禁用 TorchScript JIT 编译器 (解决 nvrtc 报错)
os.environ["PYTORCH_JIT"] = "0"
# 3. 禁用底层算子融合器 NvFuser
os.environ["NVFUSER_DISABLE"] = "1"

import torch
import torch._dynamo
torch._dynamo.config.disable = True

# 如果环境支持，强行在代码层关闭 nvfuser
try:
    if hasattr(torch._C, '_jit_set_nvfuser_enabled'):
        torch._C._jit_set_nvfuser_enabled(False)
except Exception:
    pass
# ==============================================================

import argparse
import json
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

_MODEL_CACHE: dict[str, object] = {}




def _to_1d_float32(audio: np.ndarray) -> np.ndarray:
    arr = np.asarray(audio)
    orig_dtype = arr.dtype

    if arr.ndim == 0:
        arr = arr.reshape(1)
    elif arr.ndim == 2:
        # Prefer channel-average while keeping the time axis.
        if arr.shape[0] <= 8 and arr.shape[1] > arr.shape[0]:
            arr = arr.mean(axis=0)
        else:
            arr = arr.mean(axis=1)
    elif arr.ndim > 2:
        arr = np.squeeze(arr)
        if arr.ndim != 1:
            arr = arr.reshape(-1)

    if np.issubdtype(orig_dtype, np.integer):
        scale = float(max(abs(np.iinfo(orig_dtype).min), np.iinfo(orig_dtype).max))
        arr = arr.astype(np.float32) / max(scale, 1.0)
    else:
        arr = arr.astype(np.float32, copy=False)

    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    if arr.size == 0:
        return np.zeros(1, dtype=np.float32)

    # Remove obvious DC offset.
    arr = arr - float(np.mean(arr))
    return arr


def _resample_linear(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr:
        return audio
    if audio.size <= 1:
        return audio
    dst_len = max(1, int(round(audio.size * float(dst_sr) / float(src_sr))))
    x_old = np.arange(audio.size, dtype=np.float64)
    x_new = np.linspace(0.0, float(audio.size - 1), dst_len, dtype=np.float64)
    out = np.interp(x_new, x_old, audio.astype(np.float64))
    return out.astype(np.float32)


def _read_audio_any(path: str) -> tuple[np.ndarray, int]:
    try:
        data, sr = sf.read(path, always_2d=False)
        return np.asarray(data), int(sr)
    except Exception:
        try:
            import librosa
        except Exception as exc:
            raise RuntimeError(
                "参考音频无法解码（建议上传 WAV，或安装 librosa 以支持更多格式）"
            ) from exc
        data, sr = librosa.load(path, sr=None, mono=False)
        return np.asarray(data), int(sr)


def _prepare_reference_audio(
    path: str, out_dir: Path, target_sr: int, stem: str
) -> str:
    data, sr = _read_audio_any(path)
    mono = _to_1d_float32(data)
    mono = _resample_linear(mono, sr, target_sr)

    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    if peak > 0:
        mono = mono / peak * 0.95

    out_path = out_dir / f"{stem}.wav"
    sf.write(str(out_path), mono, target_sr, subtype="PCM_16")
    return str(out_path)


def _normalize_generated_audio(wav: object) -> np.ndarray:
    if hasattr(wav, "detach") and callable(getattr(wav, "detach")):
        wav = wav.detach().cpu().numpy()
    arr = _to_1d_float32(np.asarray(wav))

    peak = float(np.max(np.abs(arr))) if arr.size else 0.0
    if peak <= 1e-9:
        return np.zeros(1, dtype=np.float32)

    # Prevent clipping/noise if model output scale drifts.
    if peak > 1.0:
        arr = arr / peak
    arr = np.clip(arr, -0.98, 0.98)
    return arr.astype(np.float32)


def _get_model(model_dir: str):
    if model_dir not in _MODEL_CACHE:
        from voxcpm import VoxCPM

        _MODEL_CACHE[model_dir] = VoxCPM.from_pretrained(model_dir, load_denoiser=False)
    return _MODEL_CACHE[model_dir]


def run_generate(req: dict[str, object]) -> dict[str, object]:
    text = str(req.get("text") or "").strip()
    if not text:
        raise RuntimeError("text 不能为空")

    mode = str(req.get("mode") or "text_only").strip() or "text_only"
    model_dir = str(req.get("model_dir") or "").strip()
    output_dir = Path(str(req.get("output_dir") or ".")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    cfg_value = float(req.get("cfg_value") or 2.0)
    inference_timesteps = int(req.get("inference_timesteps") or 10)

    model = _get_model(model_dir)
    sample_rate = int(getattr(getattr(model, "tts_model", None), "sample_rate", 24000))

    ref_in = req.get("reference_wav_path")
    prompt_in = req.get("prompt_wav_path")
    prompt_text = str(req.get("prompt_text") or "")

    temp_dir = Path(tempfile.mkdtemp(prefix="ltx_tts_"))
    ref_ready = None
    prompt_ready = None
    try:
        if isinstance(ref_in, str) and ref_in.strip():
            ref_ready = _prepare_reference_audio(
                ref_in.strip(), temp_dir, sample_rate, "reference"
            )
        if isinstance(prompt_in, str) and prompt_in.strip():
            prompt_ready = _prepare_reference_audio(
                prompt_in.strip(), temp_dir, sample_rate, "prompt"
            )

        if mode in {"clone", "ultimate_clone"} and not ref_ready:
            raise RuntimeError("克隆模式必须提供参考音频")

        gen_kwargs: dict[str, object] = {
            "text": text,
            "cfg_value": cfg_value,
            "inference_timesteps": inference_timesteps,
        }
        if mode == "clone":
            gen_kwargs["reference_wav_path"] = ref_ready
        elif mode == "ultimate_clone":
            gen_kwargs["reference_wav_path"] = ref_ready
            if prompt_ready:
                gen_kwargs["prompt_wav_path"] = prompt_ready
            if prompt_text:
                gen_kwargs["prompt_text"] = prompt_text

        wav = model.generate(**gen_kwargs)
        out = _normalize_generated_audio(wav)

        import uuid

        fname = f"tts_{uuid.uuid4().hex[:8]}.wav"
        out_path = output_dir / fname
        sf.write(str(out_path), out, sample_rate, subtype="PCM_16")
        return {"status": "complete", "audio_path": fname, "sample_rate": sample_rate}
    finally:
        try:
            for p in temp_dir.glob("*"):
                try:
                    p.unlink()
                except Exception:
                    pass
            temp_dir.rmdir()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-json", required=True, help="Path to request json")
    args = parser.parse_args()

    req_path = Path(args.request_json)
    req = json.loads(req_path.read_text(encoding="utf-8"))
    result = run_generate(req)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
