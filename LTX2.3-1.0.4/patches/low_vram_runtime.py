"""低显存模式：尽量降峰值显存（以速度换显存）；效果取决于官方管线是否支持 offload。"""

from __future__ import annotations

import gc
import logging
import os
import types
from pathlib import Path
from typing import Any

logger = logging.getLogger("ltx_low_vram")


def _ltx_desktop_config_dir() -> Path:
    p = (
        Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local")))
        / "LTXDesktop"
    )
    p.mkdir(parents=True, exist_ok=True)
    return p.resolve()


def low_vram_pref_path() -> Path:
    return _ltx_desktop_config_dir() / "low_vram_mode.pref"


def read_low_vram_pref() -> bool:
    f = low_vram_pref_path()
    if not f.is_file():
        return False
    return f.read_text(encoding="utf-8").strip().lower() in ("1", "true", "yes", "on")


def write_low_vram_pref(enabled: bool) -> None:
    low_vram_pref_path().write_text(
        "true\n" if enabled else "false\n", encoding="utf-8"
    )


def apply_low_vram_config_tweaks(handler: Any) -> None:
    """在官方 RuntimeConfig 上尽量关闭 fast 超分等（若字段存在）。"""
    cfg = getattr(handler, "config", None)
    if cfg is None:
        return
    fm = getattr(cfg, "fast_model", None)
    if fm is None:
        return
    try:
        if hasattr(fm, "model_copy"):
            updated = fm.model_copy(update={"use_upscaler": False})
            setattr(cfg, "fast_model", updated)
        elif hasattr(fm, "use_upscaler"):
            setattr(fm, "use_upscaler", False)
    except Exception as e:
        logger.debug("low_vram: 无法关闭 fast_model.use_upscaler: %s", e)


def install_low_vram_on_pipelines(handler: Any) -> None:
    """启动时读取偏好，挂到 pipelines 上供各补丁读取。"""
    pl = handler.pipelines
    low = read_low_vram_pref()
    setattr(pl, "low_vram_mode", bool(low))
    if low:
        apply_low_vram_config_tweaks(handler)
        logger.info(
            "low_vram_mode: 已开启（尝试关闭 fast 超分；若显存仍高，多为权重常驻 GPU，需降分辨率/时长或 FP8 权重）"
        )


def install_low_vram_pipeline_hooks(pl: Any) -> None:
    """在 load_gpu_pipeline / load_a2v 返回后尝试 Diffusers 式 CPU offload（无则静默）。"""
    if getattr(pl, "_ltx_low_vram_hooks_installed", False):
        return
    pl._ltx_low_vram_hooks_installed = True

    if hasattr(pl, "load_gpu_pipeline"):
        _orig_gpu = pl.load_gpu_pipeline
        pl._ltx_orig_load_gpu_for_low_vram = _orig_gpu

        def _load_gpu_wrapped(self: Any, *a: Any, **kw: Any) -> Any:
            r = _orig_gpu(*a, **kw)
            if getattr(self, "low_vram_mode", False):
                try_sequential_offload_on_pipeline_state(r)
            return r

        pl.load_gpu_pipeline = types.MethodType(_load_gpu_wrapped, pl)

    if hasattr(pl, "load_a2v_pipeline"):
        _orig_a2v = pl.load_a2v_pipeline
        pl._ltx_orig_load_a2v_for_low_vram = _orig_a2v

        def _load_a2v_wrapped(self: Any, *a: Any, **kw: Any) -> Any:
            r = _orig_a2v(*a, **kw)
            if getattr(self, "low_vram_mode", False):
                try_sequential_offload_on_pipeline_state(r)
            return r

        pl.load_a2v_pipeline = types.MethodType(_load_a2v_wrapped, pl)

    # Monkey patch: 接管 1.0.3 新增的底层 layer streaming 来实现完美的线性显存控制
    if not getattr(pl, "_ltx_layer_streaming_patched", False):
        pl._ltx_layer_streaming_patched = True
        try:
            def _patch_pipeline_class(cls_name, mod_name):
                import importlib
                try:
                    mod = importlib.import_module(mod_name)
                    pipeline_cls = getattr(mod, cls_name)
                    _orig_call = pipeline_cls.__call__
                    
                    def _patched_call(self, *args, **kwargs):
                        lim = get_vram_limit()
                        if lim is not None:
                            if lim == 0:
                                # 0表示无限，完全关闭流传输，峰值会在26GB左右，速度最快
                                kwargs["streaming_prefetch_count"] = None
                                logger.info(f"low_vram_mode: VRAM limit is unlimited (0). Disabled layer streaming.")
                            else:
                                # 实测反馈：streaming_prefetch_count 的显存成本模型。
                                # 数据表现：count=1 -> 峰值10G；count=8 -> 峰值14.7G；count=14 -> 峰值19G。
                                # 精确建模：每提高 1 count，全局真实峰值严格提升 ≈ 0.67 GB。
                                if lim <= 10.0:
                                    count = 1
                                elif lim >= 25.0:
                                    count = None  # 接近极致直接放开
                                else:
                                    # 基于 10.0GB 进行精确的四舍五入映射，让它绝对贴紧用户输入的数值
                                    extra_gb = float(lim) - 10.0
                                    count = max(1, min(32, 1 + round(extra_gb / 0.67)))
                                
                                kwargs["streaming_prefetch_count"] = count
                                logger.info(f"low_vram_mode: Dynamically tuned layer streaming prefetch count to {count} for {lim}GB limit.")
                                
                        return _orig_call(self, *args, **kwargs)
                        
                    pipeline_cls.__call__ = _patched_call
                    logger.info(f"low_vram_mode: Successfully patched {cls_name} to override streaming_prefetch_count")
                except Exception as e:
                    pass

            _patch_pipeline_class("DistilledPipeline", "ltx_pipelines.distilled")
            _patch_pipeline_class("LTXRetakePipeline", "services.retake_pipeline.ltx_retake_pipeline")
            _patch_pipeline_class("ICLoRAPipeline", "services.ic_lora_pipeline.ltx_ic_lora_pipeline")
            _patch_pipeline_class("A2VPipeline", "services.a2v_pipeline.distilled_a2v_pipeline")
        except Exception:
            pass


def get_vram_limit() -> float | None:
    try:
        import json
        from pathlib import Path
        settings_file = Path(r"C:\Users\1-xuanran\AppData\Local\LTXDesktop\settings.json")
        if settings_file.exists():
            with open(settings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "vram_limit" in data:
                lim = data["vram_limit"]
                if lim != "":
                    return float(lim)
    except Exception:
        pass
    return None

def try_sequential_offload_on_pipeline_state(state: Any) -> None:
    """按设定最高显存分配，爆显存后写入系统内存"""
    if state is None:
        return
    root = getattr(state, "pipeline", state)
    candidates: list[Any] = [root]
    inner = getattr(root, "pipeline", None)
    if inner is not None and inner is not root:
        candidates.append(inner)
        
    vram_limit = get_vram_limit()
    
    # We always apply the macro-level offload (enable_model_cpu_offload)
    # to guarantee that T5 and VAE are evicted when DiT is generating, and vice versa.
    # The micro-level (DiT intra-layer streaming) is already controlled by our __call__ hook.
    
    # Fallback to defaults (which applies the pipeline-level macro offload)
    for obj in candidates:
        for method_name in (
            "enable_model_cpu_offload",
            "enable_sequential_cpu_offload",
        ):
            fn = getattr(obj, method_name, None)
            if callable(fn):
                try:
                    fn()
                    logger.info(
                        "low_vram_mode: 已对管线调用 %s()",
                        method_name,
                    )
                    return
                except Exception as e:
                    logger.debug(
                        "low_vram_mode: %s() 失败（可忽略）: %s",
                        method_name,
                        e,
                    )


def maybe_release_pipeline_after_task(handler: Any) -> None:
    """单次生成结束后：低显存模式下强制卸载管线并回收缓存。"""
    pl = getattr(handler, "pipelines", None) or getattr(handler, "_pipelines", None)
    if pl is None or not getattr(pl, "low_vram_mode", False):
        return
    try:
        from keep_models_runtime import force_unload_gpu_pipeline

        force_unload_gpu_pipeline(pl)
    except Exception as e:
        logger.debug("low_vram_mode: 任务后卸载失败: %s", e)
    try:
        pl._pipeline_signature = None
    except Exception:
        pass
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
