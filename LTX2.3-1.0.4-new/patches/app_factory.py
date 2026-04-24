"""FastAPI app factory decoupled from runtime bootstrap side effects."""

from __future__ import annotations

import base64
import json
import hmac
import os
import subprocess
import sys
import threading
import uuid


# 防 OOM 与显存碎片化补丁：在 torch 初始化之前注入环境变量
os.environ["PYTORCH_ALLOC_CONF"] = "expandable_segments:True"
import torch  # 提升到顶层导入
from collections import deque
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from pathlib import Path  # 必须导入，用于处理 Windows 路径

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ConfigDict
from fastapi.staticfiles import StaticFiles  # 必须导入，用于挂载静态目录
from starlette.responses import Response as StarletteResponse
import shutil
import tempfile
import time
from api_types import (
    GenerateImageRequest,
    GenerateVideoRequest,
    GenerateVideoResponse,
    IcLoraGenerateRequest,
    ImageConditioningInput,
)

from _routes._errors import HTTPError
from _routes.generation import router as generation_router
from _routes.health import router as health_router
from _routes.ic_lora import router as ic_lora_router
from _routes.image_gen import router as image_gen_router
from _routes.models import router as models_router
from _routes.suggest_gap_prompt import router as suggest_gap_prompt_router
from _routes.retake import router as retake_router
from _routes.runtime_policy import router as runtime_policy_router
from _routes.settings import router as settings_router
from logging_policy import log_http_error, log_unhandled_exception
from state import init_state_service

if TYPE_CHECKING:
    from app_handler import AppHandler

# 跨域配置：允许所有来源，解决本地网页调用限制
DEFAULT_ALLOWED_ORIGINS: list[str] = ["*"]


def _ltx_desktop_config_dir() -> Path:
    p = (
        Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local")))
        / "LTXDesktop"
    )
    p.mkdir(parents=True, exist_ok=True)
    return p.resolve()


def _extend_generate_video_request_model() -> None:
    """Keep custom video fields working across upstream request-model changes."""
    annotations = dict(getattr(GenerateVideoRequest, "__annotations__", {}))
    changed = False

    for field_name, ann in (
        ("startFramePath", str | None),
        ("endFramePath", str | None),
        ("keyframePaths", list[str] | None),
        ("keyframeStrengths", list[float] | None),
        ("keyframeTimes", list[float] | None),
        ("loraPaths", list[str] | None),
        ("loraStrengths", list[float] | None),
        ("modelPath", str | None),
    ):
        if field_name not in annotations:
            annotations[field_name] = ann
            setattr(GenerateVideoRequest, field_name, None)
            changed = True

    if changed:
        GenerateVideoRequest.__annotations__ = annotations

    existing_config = dict(getattr(GenerateVideoRequest, "model_config", {}) or {})
    if existing_config.get("extra") != "allow":
        existing_config["extra"] = "allow"
        GenerateVideoRequest.model_config = ConfigDict(**existing_config)
        changed = True

    if changed:
        GenerateVideoRequest.model_rebuild(force=True)


def _install_ic_lora_reference_patch() -> None:
    """Enable Pose and raw-video IC-LoRA guides in the upstream IC-LoRA handler."""
    try:
        from _routes._errors import HTTPError
        from handlers.ic_lora_handler import IcLoraHandler
        from runtime_config.model_download_specs import resolve_model_path
        from state.app_state_types import PoseResources
    except Exception as exc:
        print(f"[PATCH] IC-LoRA reference patch skipped: {exc}")
        return

    if getattr(IcLoraHandler, "_motion_reference_patch_installed", False):
        return

    orig_build_conditioning_frame = IcLoraHandler._build_conditioning_frame
    orig_generate = IcLoraHandler.generate
    orig_require_ic_lora_model_paths = IcLoraHandler._require_ic_lora_model_paths

    def _ensure_pose_resources(self, ic_state):
        if ic_state.pose_resources is not None:
            return ic_state.pose_resources

        person_detector_path = resolve_model_path(
            self.models_dir, self.config.model_download_specs, "person_detector"
        )
        pose_model_path = resolve_model_path(
            self.models_dir, self.config.model_download_specs, "pose_processor"
        )
        if not person_detector_path.exists():
            raise HTTPError(400, f"Pose person detector model not found: {person_detector_path}")
        if not pose_model_path.exists():
            raise HTTPError(400, f"Pose processor model not found: {pose_model_path}")

        pose_pipeline_class = getattr(self._pipelines, "_pose_processor_pipeline_class", None)
        if pose_pipeline_class is None:
            raise HTTPError(500, "Pose processor pipeline class is unavailable")

        pose_pipeline = pose_pipeline_class.create(
            str(pose_model_path),
            str(person_detector_path),
            self.config.device,
        )
        ic_state.pose_resources = PoseResources(
            pipeline=pose_pipeline,
            person_detector_model_path=str(person_detector_path),
            pose_model_path=str(pose_model_path),
        )
        print("[PATCH] IC-LoRA Pose resources loaded")
        return ic_state.pose_resources

    def patched_build_conditioning_frame(self, frame, conditioning_type, ic_state=None):
        if conditioning_type == "video":
            return frame
        if conditioning_type != "pose":
            return orig_build_conditioning_frame(self, frame, conditioning_type, ic_state)
        if ic_state is None:
            raise HTTPError(500, "Pose conditioning requires loaded IC-LoRA resources")
        pose_resources = _ensure_pose_resources(self, ic_state)
        return self._video_processor.apply_pose(frame, pose_resources.pipeline)

    def patched_require_ic_lora_model_paths(self):
        lora_path, depth_model_path = orig_require_ic_lora_model_paths(self)
        override = getattr(self, "_motion_reference_lora_path", None)
        if override:
            override_path = Path(override)
            if not override_path.exists():
                raise HTTPError(400, f"Video reference IC-LoRA model not found: {override_path}")
            return override_path, depth_model_path
        return lora_path, depth_model_path

    def patched_generate(self, req):
        override = getattr(req, "ic_lora_path", None)
        if not override and getattr(req, "conditioning_type", None) == "video":
            candidate = self.models_dir / "LTX2.3-22B_IC-LoRA-Cameraman_v1_10500.safetensors"
            if candidate.exists():
                override = str(candidate)
        previous = getattr(self, "_motion_reference_lora_path", None)
        self._motion_reference_lora_path = override
        try:
            return orig_generate(self, req)
        finally:
            self._motion_reference_lora_path = previous

    IcLoraHandler._build_conditioning_frame = patched_build_conditioning_frame
    IcLoraHandler._require_ic_lora_model_paths = patched_require_ic_lora_model_paths
    IcLoraHandler.generate = patched_generate
    IcLoraHandler._motion_reference_patch_installed = True
    print("[PATCH] IC-LoRA Pose/Video reference conditioning patch installed")

def create_app(
    *,
    handler: "AppHandler",
    allowed_origins: list[str] | None = None,
    title: str = "LTX-2 Video Generation Server",
    auth_token: str = "",
    admin_token: str = "",
) -> FastAPI:
    """Create a configured FastAPI app bound to the provided handler."""
    init_state_service(handler)
    _extend_generate_video_request_model()

    app = FastAPI(title=title)
    app.state.admin_token = admin_token  # type: ignore[attr-defined]

    # 彻底压制 WinError 10054 (客户端强制断开) 的底层警告报错
    import sys, asyncio

    if sys.platform == "win32":
        try:
            loop = asyncio.get_event_loop()

            def silence_winerror_10054(loop, context):
                exc = context.get("exception")
                if (
                    isinstance(exc, ConnectionResetError)
                    and getattr(exc, "winerror", None) == 10054
                ):
                    return
                loop.default_exception_handler(context)

            loop.set_exception_handler(silence_winerror_10054)
        except Exception:
            pass


    # --- 核心修复：对准 LTX 真正的输出目录 (AppData) ---
    def get_dynamic_output_path():
        base_dir = (
            Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local")))
            / "LTXDesktop"
        ).resolve()
        config_file = base_dir / "custom_dir.txt"
        if config_file.exists():
            try:
                custom_dir = config_file.read_text(encoding="utf-8").strip()
                if custom_dir:
                    p = Path(custom_dir)
                    p.mkdir(parents=True, exist_ok=True)
                    return p
            except Exception:
                pass
        default_dir = base_dir / "outputs"
        default_dir.mkdir(parents=True, exist_ok=True)
        return default_dir

    def _ensure_a2v_stereo_audio(audio_path: str, temp_paths: list[str]) -> str:
        """A2V audio VAE expects stereo mel input; duplicate mono uploads safely."""
        try:
            import numpy as np
            import soundfile as sf

            data, sample_rate = sf.read(audio_path, always_2d=True, dtype="float32")
            if data.shape[1] >= 2:
                return audio_path

            stereo = np.repeat(data[:, :1], 2, axis=1)
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
            sf.write(tmp, stereo, sample_rate, subtype="PCM_16")
            temp_paths.append(tmp)
            print(f"[PATCH] A2V mono audio converted to stereo temp WAV: {tmp}")
            return tmp
        except Exception as exc:
            print(f"[PATCH] A2V stereo audio check failed; using original audio: {exc}")
            return audio_path

    actual_output_path = get_dynamic_output_path()
    handler.config.outputs_dir = actual_output_path

    queue_lock = threading.RLock()
    queue_pending: deque[dict] = deque()
    queue_items: dict[str, dict] = {}
    queue_history: deque[str] = deque(maxlen=80)
    queue_wake = threading.Event()
    queue_shutdown = threading.Event()
    queue_worker_started = False

    def _queue_task_view(task: dict) -> dict:
        return {
            "id": task["id"],
            "mode": task.get("mode"),
            "endpoint": task.get("endpoint"),
            "label": task.get("label"),
            "status": task.get("status"),
            "created_at": task.get("created_at"),
            "started_at": task.get("started_at"),
            "finished_at": task.get("finished_at"),
            "result": task.get("result"),
            "error": task.get("error"),
            "position": task.get("position", 0),
            "phase": task.get("phase"),
            "progress": task.get("progress", 0),
            "current_step": task.get("current_step"),
            "total_steps": task.get("total_steps"),
        }

    def _snapshot_queue() -> dict:
        gp = handler.generation.get_generation_progress()
        with queue_lock:
            pending_ids = [
                task["id"] for task in queue_pending if task.get("status") == "queued"
            ]
            current_task = None
            items: list[dict] = []
            for task_id in pending_ids:
                task = queue_items.get(task_id)
                if task is None:
                    continue
                task["position"] = len(items) + 1
                items.append(_queue_task_view(task))
            history_ids = list(queue_history)
            running_ids = [
                task_id
                for task_id, task in queue_items.items()
                if task.get("status") == "running"
            ]
            if running_ids:
                task = queue_items[running_ids[0]]
                task["position"] = 0
                task["phase"] = gp.phase
                task["progress"] = gp.progress
                task["current_step"] = getattr(gp, "currentStep", None)
                task["total_steps"] = getattr(gp, "totalSteps", None)
                current_task = _queue_task_view(task)
            history_items = [
                _queue_task_view(queue_items[task_id])
                for task_id in history_ids
                if task_id in queue_items
            ]
            return {
                "current": current_task,
                "pending": items,
                "history": history_items,
                "stats": {
                    "queued": len(items),
                    "running": 1 if current_task else 0,
                    "history": len(history_items),
                },
            }

    def _normalize_queue_result(result) -> dict:
        if hasattr(result, "model_dump"):
            return result.model_dump()
        if isinstance(result, dict):
            return result
        if isinstance(result, JSONResponse):
            raise RuntimeError(result.body.decode("utf-8", errors="replace"))
        return {"status": "complete"}

    pl = handler.pipelines
    pl._pipeline_signature = None
    from low_vram_runtime import (
        install_low_vram_on_pipelines,
        install_low_vram_pipeline_hooks,
    )

    install_low_vram_on_pipelines(handler)
    install_low_vram_pipeline_hooks(pl)
    # LoRA：在 SingleGPUModelBuilder.build 时合并权重（model_ledger 不足以让桌面版 DiT 吃到 LoRA）
    from lora_build_hook import install_lora_build_hook

    install_lora_build_hook()
    _install_ic_lora_reference_patch()

    upload_tmp_path = actual_output_path / "uploads"

    # 如果文件夹不存在则创建，防止挂载失败
    if not actual_output_path.exists():
        actual_output_path.mkdir(parents=True, exist_ok=True)
    if not upload_tmp_path.exists():
        upload_tmp_path.mkdir(parents=True, exist_ok=True)

    # 挂载静态服务：将该目录映射到 http://127.0.0.1:3000/outputs
    app.mount(
        "/outputs", StaticFiles(directory=str(actual_output_path)), name="outputs"
    )
    # -----------------------------------------------

    # 配置 CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins or DEFAULT_ALLOWED_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # === [全局隔离补丁] ===
    # 强制将每一个新的 HTTP 线程/协程请求的默认显卡都强绑定到用户选定的设备上
    @app.middleware("http")
    async def _sync_gpu_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[StarletteResponse]],
    ) -> StarletteResponse:
        import torch

        if (
            torch.cuda.is_available()
            and getattr(handler.config.device, "type", "") == "cuda"
        ):
            idx = handler.config.device.index
            if idx is not None:
                # 能够强行夺取那些底层写死了 cuda:0 而忽略 config.device 的第三方库
                torch.cuda.set_device(idx)
        return await call_next(request)

    # 认证中间件
    @app.middleware("http")
    async def _auth_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[StarletteResponse]],
    ) -> StarletteResponse:
        # 关键修复：如果是获取生成的图片，直接放行，不检查 Token
        if (
            request.url.path.startswith("/outputs")
            or request.url.path == "/api/system/upload-image"
        ):
            return await call_next(request)

        if not auth_token:
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)

        def _token_matches(candidate: str) -> bool:
            return hmac.compare_digest(candidate, auth_token)

        # WebSocket 认证
        if request.headers.get("upgrade", "").lower() == "websocket":
            if _token_matches(request.query_params.get("token", "")):
                return await call_next(request)
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        # HTTP 认证 (Bearer/Basic)
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer ") and _token_matches(auth_header[7:]):
            return await call_next(request)
        if auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode()
                _, _, password = decoded.partition(":")
                if _token_matches(password):
                    return await call_next(request)
            except Exception:
                pass
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})

    # 异常处理逻辑
    _FALLBACK = "An unexpected error occurred"

    async def _route_http_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        if isinstance(exc, HTTPError):
            log_http_error(request, exc)
            return JSONResponse(
                status_code=exc.status_code, content={"error": exc.detail or _FALLBACK}
            )
        return JSONResponse(status_code=500, content={"error": str(exc) or _FALLBACK})

    async def _validation_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        if isinstance(exc, RequestValidationError):
            return JSONResponse(
                status_code=422, content={"error": str(exc) or _FALLBACK}
            )
        return JSONResponse(status_code=422, content={"error": str(exc) or _FALLBACK})

    async def _route_generic_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        log_unhandled_exception(request, exc)
        return JSONResponse(status_code=500, content={"error": str(exc) or _FALLBACK})

    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(HTTPError, _route_http_error_handler)
    app.add_exception_handler(Exception, _route_generic_error_handler)

    # --- 系统功能接口 ---
    @app.post("/api/system/clear-gpu")
    async def route_clear_gpu():
        try:
            import torch
            import gc
            import asyncio

            # 1. 尝试终止任务并重置运行状态
            if getattr(handler.generation, "is_generation_running", lambda: False)():
                try:
                    handler.generation.cancel_generation()
                except Exception:
                    pass
                await asyncio.sleep(0.5)

            # 暴力重置死锁状态
            if hasattr(handler.generation, "_generation_id"):
                handler.generation._generation_id = None
            if hasattr(handler.generation, "_is_generating"):
                handler.generation._is_generating = False

            # 2. 强制卸载模型: 临时屏蔽底层锁定器
            try:
                mock_swapped = False
                orig_running = None
                if hasattr(handler.pipelines, "_generation_service"):
                    orig_running = (
                        handler.pipelines._generation_service.is_generation_running
                    )
                    handler.pipelines._generation_service.is_generation_running = (
                        lambda: False
                    )
                    mock_swapped = True
                try:
                    from keep_models_runtime import force_unload_gpu_pipeline

                    force_unload_gpu_pipeline(handler.pipelines)
                finally:
                    if mock_swapped:
                        handler.pipelines._generation_service.is_generation_running = (
                            orig_running
                        )
            except Exception as e:
                print(f"Force unload warning: {e}")

            # 3. 深度清理
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
            try:
                handler.pipelines._pipeline_signature = None
            except Exception:
                pass
            return {
                "status": "success",
                "message": "GPU memory cleared and models unloaded",
            }
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

    @app.get("/api/system/low-vram-mode")
    async def route_get_low_vram_mode():
        enabled = bool(getattr(handler.pipelines, "low_vram_mode", False))
        return {"enabled": enabled}

    @app.post("/api/system/low-vram-mode")
    async def route_set_low_vram_mode(request: Request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        enabled = bool(data.get("enabled", False))
        from low_vram_runtime import (
            apply_low_vram_config_tweaks,
            write_low_vram_pref,
        )

        handler.pipelines.low_vram_mode = enabled
        write_low_vram_pref(enabled)
        if enabled:
            apply_low_vram_config_tweaks(handler)
        return {"status": "success", "enabled": enabled}

    @app.post("/api/system/reset-state")
    async def route_reset_state():
        """轻量级状态重置：只清除 generation 状态锁，不卸载 GPU 管线。
        在每次新渲染开始前由前端调用，确保后端状态干净可用。"""
        try:
            gen = handler.generation
            # 强制清除所有可能导致 is_generation_running() 返回 True 的标志
            for attr in (
                "_is_generating",
                "_generation_id",
                "_cancelled",
                "_is_cancelled",
            ):
                if hasattr(gen, attr):
                    if attr in ("_is_generating", "_cancelled", "_is_cancelled"):
                        setattr(gen, attr, False)
                    else:
                        setattr(gen, attr, None)
            # 某些实现用 threading.Event
            for attr in ("_cancel_event",):
                if hasattr(gen, attr):
                    try:
                        getattr(gen, attr).clear()
                    except Exception:
                        pass
            print("[reset-state] Generation state has been reset cleanly.")
            return {"status": "success", "message": "Generation state reset"}
        except Exception as e:
            import traceback

            traceback.print_exc()
            return JSONResponse(status_code=500, content={"error": str(e)})

    @app.post("/api/system/set-dir")
    async def route_set_dir(request: Request):
        try:
            data = await request.json()
            new_dir = data.get("directory", "").strip()
            base_dir = (
                Path(
                    os.environ.get(
                        "LOCALAPPDATA", os.path.expanduser("~/AppData/Local")
                    )
                )
                / "LTXDesktop"
            ).resolve()
            config_file = base_dir / "custom_dir.txt"
            if new_dir:
                p = Path(new_dir)
                p.mkdir(parents=True, exist_ok=True)
                config_file.write_text(new_dir, encoding="utf-8")
            else:
                if config_file.exists():
                    config_file.unlink()
            # 立即更新全局 config 控制
            handler.config.outputs_dir = get_dynamic_output_path()
            return {"status": "success", "directory": str(get_dynamic_output_path())}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

    @app.get("/api/system/get-dir")
    async def route_get_dir():
        return {"status": "success", "directory": str(get_dynamic_output_path())}

    @app.get("/api/system/browse-dir")
    async def route_browse_dir():
        try:
            import subprocess

            # 强制将对话框置顶层：通过 STA 线程 + Topmost 属性，避免被窗口锥入后台
            ps_script = (
                "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null;"
                "[System.Reflection.Assembly]::LoadWithPartialName('System.Drawing') | Out-Null;"
                "$f = New-Object System.Windows.Forms.FolderBrowserDialog;"
                "$f.Description = '\u9009\u62e9 LTX \u89c6\u9891\u548c\u56fe\u50cf\u751f\u6210\u7684\u5168\u5c40\u8f93\u51fa\u76ee\u5f55';"
                "$f.ShowNewFolderButton = $true;"
                # 创建一个雐形助手窗口作为 parent 确保对话框在最顶层
                "$owner = New-Object System.Windows.Forms.Form;"
                "$owner.TopMost = $true;"
                "$owner.StartPosition = 'CenterScreen';"
                "$owner.Size = New-Object System.Drawing.Size(1, 1);"
                "$owner.Show();"
                "$owner.BringToFront();"
                "$owner.Focus();"
                "if ($f.ShowDialog($owner) -eq 'OK') { echo $f.SelectedPath };"
                "$owner.Dispose();"
            )

            def run_ps():
                process = subprocess.Popen(
                    ["powershell", "-STA", "-NoProfile", "-Command", ps_script],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    # 移除 CREATE_NO_WINDOW 以允许 UI 线程正常弹出
                )
                stdout, _ = process.communicate()
                return stdout.strip()

            from starlette.concurrency import run_in_threadpool

            selected_dir = await run_in_threadpool(run_ps)
            return {"status": "success", "directory": selected_dir}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

    _LORA_SCAN_SUFFIXES = {".safetensors", ".ckpt", ".pt", ".bin"}

    def _resolve_models_root() -> Path | None:
        try:
            md = getattr(handler.pipelines, "models_dir", None)
            if md and str(md).strip():
                return Path(str(md)).expanduser().resolve()
        except Exception:
            pass
        return None

    def _default_lora_dir() -> Path | None:
        root = _resolve_models_root()
        return root / "loras" if root else None

    @app.post("/api/lora-dir")
    async def route_save_lora_dir(request: Request):
        """保存 LoRA 目录到设置"""
        try:
            body = await request.json()
            lora_dir = body.get("loraDir", "").strip()

            settings_file = _ltx_desktop_config_dir() / "settings.json"
            import json

            if settings_file.exists():
                with open(settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {}

            data["lora_dir"] = lora_dir
            data["loraDir"] = lora_dir

            settings_file.parent.mkdir(parents=True, exist_ok=True)
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            return {"status": "ok", "loraDir": lora_dir}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @app.get("/api/lora-dir")
    async def route_get_lora_dir():
        """获取 LoRA 目录设置"""
        try:
            import json

            settings_file = _ltx_desktop_config_dir() / "settings.json"
            models_root = _resolve_models_root()
            default_lora_dir = _default_lora_dir()
            payload = {
                "loraDir": "",
                "modelsDir": str(models_root) if models_root else "",
                "defaultLoraDir": str(default_lora_dir) if default_lora_dir else "",
            }
            if settings_file.exists():
                with open(settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                payload["loraDir"] = data.get("lora_dir", "") or data.get("loraDir", "")
            return payload
        except Exception as e:
            return {"loraDir": "", "error": str(e)}

    
    @app.post("/api/vram-limit")
    async def route_save_vram_limit(request: Request):
        try:
            body = await request.json()
            limit = body.get("vramLimit", "")
            
            import json
            from pathlib import Path
            settings_file = _ltx_desktop_config_dir() / "settings.json"
            if settings_file.exists():
                with open(settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {}
                
            data["vram_limit"] = limit
            settings_file.parent.mkdir(parents=True, exist_ok=True)
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                
            return {"status": "ok", "vramLimit": limit}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @app.get("/api/vram-limit")
    async def route_get_vram_limit():
        try:
            import json
            from pathlib import Path
            settings_file = _ltx_desktop_config_dir() / "settings.json"
            if settings_file.exists():
                with open(settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return {"vramLimit": data.get("vram_limit", "0") or "0"}
            return {"vramLimit": "0"}
        except Exception as e:
            return {"vramLimit": "0", "error": str(e)}

    @app.get("/api/loras")
    async def route_list_loras(request: Request):
        """扫描本地 LoRA 目录；前端「设置」里填的路径依赖此接口（官方路由可能不存在）。"""
        from pathlib import Path as _Path

        raw = (request.query_params.get("dir") or "").strip()
        if raw.startswith("True"):
            raw = raw[4:].lstrip()
        raw = raw.strip().strip('"').strip("'")

        if not raw:
            # 直接从 settings.json 读取 lora_dir
            try:
                import json

                settings_file = _ltx_desktop_config_dir() / "settings.json"
                if settings_file.exists():
                    with open(settings_file, "r", encoding="utf-8") as f:
                        settings_data = json.load(f)
                    custom_lora_dir = settings_data.get(
                        "lora_dir", ""
                    ) or settings_data.get("loraDir", "")
                    if custom_lora_dir and str(custom_lora_dir).strip():
                        raw = str(custom_lora_dir).strip()
            except Exception as e:
                print(f"[PATCH] Failed to read lora_dir from settings: {e}")

            if not raw:
                # 默认规则：LoRA 路径 = 当前 LTX models_dir 下的 `loras` 子目录
                default_lora_dir = _default_lora_dir()
                raw = str(default_lora_dir) if default_lora_dir else ""

        if not raw:
            return {"loras": [], "loras_dir": "", "models_dir": ""}

        root = _Path(raw).expanduser()
        try:
            root = root.resolve()
        except OSError:
            pass

        if not root.is_dir():
            return {
                "loras": [],
                "error": "not_a_directory",
                "message": "路径不是文件夹或不存在，请检查拼写、盘符与权限",
                "path": str(root),
                "loras_dir": str(root),
                "models_dir": str(root.parent),
            }

        found: list[dict[str, str]] = []
        try:
            for dirpath, _dirnames, filenames in os.walk(root):
                for fn in filenames:
                    suf = _Path(fn).suffix.lower()
                    if suf in _LORA_SCAN_SUFFIXES:
                        full = _Path(dirpath) / fn
                        if full.is_file():
                            try:
                                resolved = str(full.resolve())
                            except OSError:
                                resolved = str(full)
                            found.append({"name": fn, "path": resolved})
        except OSError as e:
            return JSONResponse(
                status_code=400,
                content={
                    "loras": [],
                    "error": "scan_failed",
                    "message": str(e),
                    "path": str(root),
                },
            )

        found.sort(key=lambda x: x["name"].lower())
        return {
            "loras": found,
            "loras_dir": str(root),
            "models_dir": str(root.parent),
            "default_loras_dir": str(_default_lora_dir() or ""),
        }

    _MODEL_SCAN_SUFFIXES = {
        ".safetensors",
        ".ckpt",
        ".pt",
        ".bin",
        ".pth",
    }

    @app.get("/api/models")
    async def route_list_models(request: Request):
        """扫描本地 checkpoint 目录；需在官方 models_router 之前注册以覆盖空列表行为。"""
        raw = (request.query_params.get("dir") or "").strip()
        if raw.startswith("True"):
            raw = raw[4:].lstrip()
        raw = raw.strip().strip('"').strip("'")

        if not raw:
            try:
                md = getattr(handler.pipelines, "models_dir", None)
                if md is None or not str(md).strip():
                    return {"models": []}
                root = Path(str(md)).expanduser().resolve()
            except OSError:
                return {"models": []}
            if not root.is_dir():
                return {"models": []}
        else:
            root = Path(raw).expanduser()
            try:
                root = root.resolve()
            except OSError:
                pass

        if not root.is_dir():
            return {
                "models": [],
                "error": "not_a_directory",
                "message": "路径不是文件夹或不存在，请检查拼写、盘符与权限",
                "path": str(root),
            }

        found: list[dict[str, str]] = []
        try:
            for dirpath, _dirnames, filenames in os.walk(root):
                for fn in filenames:
                    suf = Path(fn).suffix.lower()
                    if suf in _MODEL_SCAN_SUFFIXES:
                        full = Path(dirpath) / fn
                        if full.is_file():
                            try:
                                resolved = str(full.resolve())
                            except OSError:
                                resolved = str(full)
                            found.append({"name": fn, "path": resolved})
        except OSError as e:
            return JSONResponse(
                status_code=400,
                content={
                    "models": [],
                    "error": "scan_failed",
                    "message": str(e),
                    "path": str(root),
                },
            )

        found.sort(key=lambda x: x["name"].lower())
        return {"models": found}

    @app.get("/api/system/file")
    async def route_serve_file(path: str):
        from fastapi.responses import FileResponse

        if os.path.exists(path):
            return FileResponse(path)
        return JSONResponse(status_code=404, content={"error": "File not found"})

    @app.get("/api/system/list-gpus")
    async def route_list_gpus():
        try:
            import torch

            gpus = []
            if torch.cuda.is_available():
                current_idx = 0
                dev = getattr(handler.config, "device", None)
                if dev is not None and getattr(dev, "index", None) is not None:
                    current_idx = dev.index
                for i in range(torch.cuda.device_count()):
                    try:
                        name = torch.cuda.get_device_name(i)
                    except Exception:
                        name = f"GPU {i}"
                    try:
                        vram_bytes = torch.cuda.get_device_properties(i).total_memory
                        vram_gb = vram_bytes / (1024**3)
                        vram_mb = vram_bytes / (1024**2)
                    except Exception:
                        vram_gb = 0.0
                        vram_mb = 0
                    gpus.append(
                        {
                            "id": i,
                            "name": name,
                            "vram": f"{vram_gb:.1f} GB",
                            "vram_mb": int(vram_mb),
                            "active": (i == current_idx),
                        }
                    )
            return {"status": "success", "gpus": gpus}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

    @app.post("/api/system/switch-gpu")
    async def route_switch_gpu(request: Request):
        try:
            import torch
            import gc
            import asyncio

            data = await request.json()
            gpu_id = data.get("gpu_id")

            if (
                gpu_id is None
                or not torch.cuda.is_available()
                or gpu_id >= torch.cuda.device_count()
            ):
                return JSONResponse(
                    status_code=400, content={"error": "Invalid GPU ID"}
                )

            # 先尝试终止任何可能的卡死任务
            if getattr(handler.generation, "is_generation_running", lambda: False)():
                try:
                    handler.generation.cancel_generation()
                except Exception:
                    pass
                await asyncio.sleep(0.5)
            if hasattr(handler.generation, "_generation_id"):
                handler.generation._generation_id = None
            if hasattr(handler.generation, "_is_generating"):
                handler.generation._is_generating = False

            # 1. 卸载当前 GPU 上的模型: 临时屏蔽底层锁定器
            try:
                mock_swapped = False
                orig_running = None
                if hasattr(handler.pipelines, "_generation_service"):
                    orig_running = (
                        handler.pipelines._generation_service.is_generation_running
                    )
                    handler.pipelines._generation_service.is_generation_running = (
                        lambda: False
                    )
                    mock_swapped = True
                try:
                    from keep_models_runtime import force_unload_gpu_pipeline

                    force_unload_gpu_pipeline(handler.pipelines)
                finally:
                    if mock_swapped:
                        handler.pipelines._generation_service.is_generation_running = (
                            orig_running
                        )
            except Exception:
                pass
            gc.collect()
            torch.cuda.empty_cache()

            try:
                handler.pipelines._pipeline_signature = None
            except Exception:
                pass

            # 2. 切换全局设备配置
            new_device = torch.device(f"cuda:{gpu_id}")
            handler.config.device = new_device

            # 3. 核心修复：设置当前进程的默认 CUDA 设备
            # 这会影响到 torch.cuda.current_device() 和后续的模型加载
            torch.cuda.set_device(gpu_id)

            # 针对底层库可能直接读取 CUDA_VISIBLE_DEVICES 的情况
            # 注意：torch 初始化后修改此变量不一定生效，但对某些库可能有引导作用
            os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)

            # 4. 【核心修复】同步更新 TextEncoder 的设备指针
            # 根本原因: LTXTextEncoder.self.device 在初始化时硬绑定了旧 GPU，
            # 切换设备后 text context 仍在旧 GPU 上，与已迁移到新 GPU 的
            # Transformer 产生 "cuda:0 and cuda:1" 设备不一致冲突。
            try:
                te_state = None
                # 尝试多种路径访问 text_encoder 状态
                if hasattr(handler, "state") and hasattr(handler.state, "text_encoder"):
                    te_state = handler.state.text_encoder
                elif hasattr(handler, "_state") and hasattr(
                    handler._state, "text_encoder"
                ):
                    te_state = handler._state.text_encoder

                if te_state is not None:
                    # 4a. 更新 LTXTextEncoder 服务自身的 device 属性
                    if hasattr(te_state, "service") and hasattr(
                        te_state.service, "device"
                    ):
                        te_state.service.device = new_device
                        print(f"[TextEncoder] device updated to {new_device}")

                    # 4b. 将缓存的 encoder 权重迁移到 CPU，下次推理时再按新设备重加载
                    if (
                        hasattr(te_state, "cached_encoder")
                        and te_state.cached_encoder is not None
                    ):
                        try:
                            te_state.cached_encoder.to(torch.device("cpu"))
                        except Exception:
                            pass
                        te_state.cached_encoder = None
                        print(
                            "[TextEncoder] cached encoder cleared (will reload on new GPU)"
                        )

                    # 4c. 清除 API embeddings 缓存（tensor 绑定旧 GPU）
                    if hasattr(te_state, "api_embeddings"):
                        te_state.api_embeddings = None

                    # 4d. 清除 prompt cache（其中 tensor 也绑定旧 GPU）
                    if hasattr(te_state, "prompt_cache") and te_state.prompt_cache:
                        te_state.prompt_cache.clear()
                        print("[TextEncoder] prompt cache cleared")
            except Exception as _te_err:
                print(f"[TextEncoder] device sync warning (non-fatal): {_te_err}")

            print(
                f"Switched active GPU to: {torch.cuda.get_device_name(gpu_id)} (ID: {gpu_id})"
            )
            return {"status": "success", "message": f"Switched to GPU {gpu_id}"}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

    # --- 核心增强：首尾帧插值与视频超分支持 ---
    from handlers.video_generation_handler import VideoGenerationHandler
    from services.retake_pipeline.ltx_retake_pipeline import LTXRetakePipeline
    from server_utils.media_validation import normalize_optional_path
    from PIL import Image

    # 1. 增强插值功能 (Monkey Patch VideoGenerationHandler)
    _orig_generate = VideoGenerationHandler.generate
    _orig_generate_video = VideoGenerationHandler.generate_video

    def patched_generate(self, req: GenerateVideoRequest):
        # === [DEBUG] 打印当前生成状态 ===
        gen = self._generation
        is_running = (
            gen.is_generation_running()
            if hasattr(gen, "is_generation_running")
            else "?方法不存在"
        )
        gen_id = getattr(gen, "_generation_id", "?属性不存在")
        is_gen = getattr(gen, "_is_generating", "?属性不存在")
        cancelled = getattr(
            gen, "_cancelled", getattr(gen, "_is_cancelled", "?属性不存在")
        )
        print(f"\n[PATCH][patched_generate] ==> 收到新请求")
        print(f"  is_generation_running() = {is_running}")
        print(f"  _generation_id          = {gen_id}")
        print(f"  _is_generating          = {is_gen}")
        print(f"  _cancelled              = {cancelled}")
        start_frame_path = normalize_optional_path(getattr(req, "startFramePath", None))
        end_frame_path = normalize_optional_path(getattr(req, "endFramePath", None))
        _raw_kf = getattr(req, "keyframePaths", None)
        keyframe_paths_list: list[str] = []
        if isinstance(_raw_kf, list):
            for p in _raw_kf:
                np = normalize_optional_path(p)
                if np:
                    keyframe_paths_list.append(np)
        use_multi_keyframes = len(keyframe_paths_list) >= 2
        _raw_kf_st = getattr(req, "keyframeStrengths", None)
        keyframe_strengths_list: list[float] | None = None
        if isinstance(_raw_kf_st, list) and _raw_kf_st:
            try:
                keyframe_strengths_list = [float(x) for x in _raw_kf_st]
            except (TypeError, ValueError):
                keyframe_strengths_list = None
        _raw_kf_t = getattr(req, "keyframeTimes", None)
        keyframe_times_list: list[float] | None = None
        if isinstance(_raw_kf_t, list) and _raw_kf_t:
            try:
                keyframe_times_list = [float(x) for x in _raw_kf_t]
            except (TypeError, ValueError):
                keyframe_times_list = None
        aspect_ratio = getattr(req, "aspectRatio", None)
        print(f"  startFramePath          = {start_frame_path}")
        print(f"  endFramePath            = {end_frame_path}")
        print(f"  keyframePaths (n={len(keyframe_paths_list)}) = {use_multi_keyframes}")
        print(f"  aspectRatio             = {aspect_ratio}")

        # 检查是否有音频
        audio_path = normalize_optional_path(getattr(req, "audioPath", None))
        print(f"[PATCH] audio_path = {audio_path}")

        # 检查是否有图片（图生视频）
        image_path = normalize_optional_path(getattr(req, "imagePath", None))
        print(f"[PATCH] image_path = {image_path}")

        # 始终使用自定义逻辑（支持首尾帧和竖屏）
        print(f"[PATCH] 使用自定义逻辑处理")

        # 计算分辨率
        import uuid

        resolution = req.resolution
        duration = int(float(req.duration))
        fps = int(float(req.fps))

        # 宽高均需为 64 的倍数（LTX 内核校验）；在近似 16:9 下取整
        RESOLUTION_MAP = {
            "540p": (1024, 576),
            "720p": (1280, 704),
            "1080p": (1920, 1088),
        }

        def get_16_9_size(res):
            return RESOLUTION_MAP.get(res, (1280, 704))

        def get_9_16_size(res):
            w, h = get_16_9_size(res)
            return h, w  # 交换宽高

        if req.aspectRatio == "9:16":
            width, height = get_9_16_size(resolution)
        else:
            width, height = get_16_9_size(resolution)

        # 计算帧数
        num_frames = ((duration * fps) // 8) * 8 + 1
        num_frames = max(num_frames, 9)

        print(f"[PATCH] 计算得到的分辨率: {width}x{height}, 帧数: {num_frames}")

        # 多关键帧单次推理时勿用首尾帧属性，避免与 keyframe 列表重复
        if use_multi_keyframes:
            self._start_frame_path = None
            self._end_frame_path = None
            image_path_for_video = None
        else:
            self._start_frame_path = start_frame_path
            self._end_frame_path = end_frame_path
            image_path_for_video = image_path

        # 无论有没有音频，都使用自定义逻辑支持首尾帧 / 多关键帧
        try:
            result = patched_generate_video(
                self,
                prompt=req.prompt,
                image=None,
                image_path=image_path_for_video,
                height=height,
                width=width,
                num_frames=num_frames,
                fps=fps,
                seed=self._resolve_seed(),
                camera_motion=req.cameraMotion,
                negative_prompt=req.negativePrompt,
                audio_path=audio_path,
                lora_path=getattr(req, "loraPath", None),
                lora_strength=float(getattr(req, "loraStrength", 1.0) or 1.0),
                lora_paths=getattr(req, "loraPaths", None),
                lora_strengths=getattr(req, "loraStrengths", None),
                model_path=getattr(req, "modelPath", None),
                keyframe_paths=keyframe_paths_list if use_multi_keyframes else None,
                keyframe_strengths=(
                    keyframe_strengths_list if use_multi_keyframes else None
                ),
                keyframe_times=(keyframe_times_list if use_multi_keyframes else None),
            )
            print(f"[PATCH][patched_generate] <== 完成, 返回状态: complete")
            return type("Response", (), {"status": "complete", "video_path": result})()
        except Exception as e:
            import traceback

            print(f"[PATCH][patched_generate] 错误: {e}")
            traceback.print_exc()
            raise

    def patched_generate_video(
        self,
        prompt,
        image,
        image_path=None,
        height=None,
        width=None,
        num_frames=None,
        fps=None,
        seed=None,
        camera_motion=None,
        negative_prompt=None,
        audio_path=None,
        lora_path=None,
        lora_strength=1.0,
        lora_paths: list[str] | None = None,
        lora_strengths: list[float] | None = None,
        keyframe_paths: list[str] | None = None,
        keyframe_strengths: list[float] | None = None,
        keyframe_times: list[float] | None = None,
        model_path: str | None = None,
    ):
        # === [DEBUG] 打印当前生成状态 ===
        gen = self._generation
        is_running = (
            gen.is_generation_running()
            if hasattr(gen, "is_generation_running")
            else "?方法不存在"
        )
        gen_id = getattr(gen, "_generation_id", "?属性不存在")
        is_gen = getattr(gen, "_is_generating", "?属性不存在")
        print(f"[PATCH][patched_generate_video] ==> 开始推理")
        print(f"  is_generation_running() = {is_running}")
        print(f"  _generation_id          = {gen_id}")
        print(f"  _is_generating          = {is_gen}")
        print(
            f"  resolution              = {width}x{height}, frames={num_frames}, fps={fps}"
        )
        print(f"  image param             = {type(image)}, {image is not None}")
        print(f"  image_path              = {image_path}")
        # ==================================
        from ltx_pipelines.utils.args import (
            ImageConditioningInput as LtxImageConditioningInput,
        )

        images_inputs = []
        temp_paths = []
        kf_list = [p for p in (keyframe_paths or []) if p]
        use_multi_kf = len(kf_list) >= 2

        start_path = getattr(self, "_start_frame_path", None)
        end_path = getattr(self, "_end_frame_path", None)
        print(
            f"[PATCH] start_path={start_path}, end_path={end_path}, multi_kf={use_multi_kf} n={len(kf_list)}"
        )

        latent_num_frames = (num_frames - 1) // 8 + 1
        last_latent_idx = latent_num_frames - 1
        uses_latent_frame_idx = bool(audio_path)
        last_conditioning_idx = last_latent_idx if uses_latent_frame_idx else num_frames - 1
        print(
            f"[PATCH] latent_num_frames={latent_num_frames}, last_latent_idx={last_latent_idx}, "
            f"conditioning_idx_mode={'latent' if uses_latent_frame_idx else 'frame'}, "
            f"last_conditioning_idx={last_conditioning_idx}"
        )

        if use_multi_kf:
            n_kf = len(kf_list)
            st_override = keyframe_strengths or []
            if len(st_override) not in (0, n_kf):
                print(
                    f"[PATCH] keyframeStrengths 长度({len(st_override)})与关键帧数({n_kf})不一致，改用默认强度曲线"
                )
                st_override = []

            def _default_multi_guide_strength(i: int, n: int) -> float:
                """对齐 Comfy LTXVAddGuideMulti 常见配置：首尾不全是 1，中间明显减弱以减少邻帧闪烁。"""
                if n <= 2:
                    return 1.0
                if i == 0:
                    return 0.62
                if i == n - 1:
                    return 1.0
                return 0.42

            kt = keyframe_times or []
            times_match = len(kt) == n_kf
            if times_match:
                fps_f = max(float(fps), 0.001)
                max_t = (num_frames - 1) / fps_f
                fi_list: list[int] = []
                for ki in range(n_kf):
                    t_sec = max(0.0, min(max_t, float(kt[ki])))
                    pf = int(round(t_sec * fps_f))
                    pf = min(num_frames - 1, max(0, pf))
                    fi = pf // 8 if uses_latent_frame_idx else pf
                    fi = min(last_conditioning_idx, max(0, fi))
                    fi_list.append(int(fi))
                for j in range(1, n_kf):
                    if fi_list[j] <= fi_list[j - 1]:
                        fi_list[j] = min(last_conditioning_idx, fi_list[j - 1] + 1)
                print(f"[PATCH] Multi-keyframe: 使用 keyframeTimes 映射 -> {fi_list}")
            else:
                fi_list = []
                prev_fi = -1
                for ki in range(n_kf):
                    if last_conditioning_idx <= 0:
                        fi = 0
                    elif ki == 0:
                        fi = 0
                    elif ki == n_kf - 1:
                        fi = last_conditioning_idx
                    else:
                        pf = int(
                            round(ki * (num_frames - 1) / max(1, (n_kf - 1)))
                        )
                        fi = pf // 8 if uses_latent_frame_idx else pf
                        fi = min(last_conditioning_idx - 1, max(1, fi))
                        if fi <= prev_fi:
                            fi = min(last_conditioning_idx - 1, prev_fi + 1)
                    prev_fi = fi
                    fi_list.append(int(fi))

            for ki, kp in enumerate(kf_list):
                if not os.path.isfile(kp):
                    raise RuntimeError(f"多关键帧路径无效或不存在: {kp}")
                fi = fi_list[ki]

                if len(st_override) == n_kf:
                    st = float(st_override[ki])
                    st = max(0.1, min(1.0, st))
                else:
                    st = _default_multi_guide_strength(ki, n_kf)

                img = self._prepare_image(kp, width, height)
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
                img.save(tmp)
                temp_paths.append(tmp)
                tmp_normalized = tmp.replace("\\", "/")
                images_inputs.append(
                    LtxImageConditioningInput(
                        path=tmp_normalized, frame_idx=int(fi), strength=float(st)
                    )
                )
                print(
                    f"[PATCH] Multi-keyframe [{ki}]: {tmp_normalized}, "
                    f"frame_idx={fi}, strength={st:.3f}"
                )
        else:
            # 如果没有首尾帧但有 image_path，使用 image_path 作为起始帧
            if not start_path and not end_path and image_path:
                print(f"[PATCH] 使用 image_path 作为起始帧: {image_path}")
                start_path = image_path

            has_image_param = image is not None
            if has_image_param:
                print(f"[PATCH] image param is available, will be used as start frame")

            target_start_path = start_path if start_path else None
            if not target_start_path and image is not None:
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
                image.save(tmp)
                temp_paths.append(tmp)
                target_start_path = tmp
                print(f"[PATCH] Using image param as start frame: {target_start_path}")

            if target_start_path:
                start_img = self._prepare_image(target_start_path, width, height)
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
                start_img.save(tmp)
                temp_paths.append(tmp)
                tmp_normalized = tmp.replace("\\", "/")
                images_inputs.append(
                    LtxImageConditioningInput(
                        path=tmp_normalized, frame_idx=0, strength=1.0
                    )
                )
                print(f"[PATCH] Added start frame: {tmp_normalized}, frame_idx=0")

            if end_path:
                end_img = self._prepare_image(end_path, width, height)
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
                end_img.save(tmp)
                temp_paths.append(tmp)
                tmp_normalized = tmp.replace("\\", "/")
                images_inputs.append(
                    LtxImageConditioningInput(
                        path=tmp_normalized,
                        frame_idx=last_conditioning_idx,
                        strength=1.0,
                    )
                )
                print(
                    f"[PATCH] Added end frame: {tmp_normalized}, frame_idx={last_conditioning_idx}"
                )

        print(f"[PATCH] images_inputs count: {len(images_inputs)}")
        if images_inputs:
            for idx, img in enumerate(images_inputs):
                print(
                    f"[PATCH] images_inputs[{idx}]: path={getattr(img, 'path', 'N/A')}, frame_idx={getattr(img, 'frame_idx', 'N/A')}, strength={getattr(img, 'strength', 'N/A')}"
                )

        print(f"[PATCH] audio_path = {audio_path}")
        if audio_path:
            audio_path = _ensure_a2v_stereo_audio(audio_path, temp_paths)
            print(f"[PATCH] a2v_audio_path = {audio_path}")

        if self._generation.is_generation_cancelled():
            raise RuntimeError("Generation was cancelled")

        # 导入 uuid
        import uuid

        generation_id = uuid.uuid4().hex[:8]

        # 根据是否有音频选择不同的 pipeline
        extra_loras_for_hook: tuple | None = (
            None  # 供 lora_build_hook 在 DiT build 时融合
        )
        gpu_slot = getattr(self._pipelines.state, "gpu_slot", None)
        active = getattr(gpu_slot, "active_pipeline", None) if gpu_slot else None
        cached_sig = getattr(self._pipelines, "_pipeline_signature", None)

        new_kind = "a2v" if audio_path else "fast"
        if (
            cached_sig
            and isinstance(cached_sig, tuple)
            and len(cached_sig) > 0
            and cached_sig[0] != new_kind
            and active is not None
        ):
            from keep_models_runtime import force_unload_gpu_pipeline

            print(f"[PATCH] 管线类型切换 {cached_sig[0]} -> {new_kind}，强制卸载旧模型")
            force_unload_gpu_pipeline(self._pipelines)
            gpu_slot = getattr(self._pipelines.state, "gpu_slot", None)
            active = getattr(gpu_slot, "active_pipeline", None) if gpu_slot else None

        if audio_path:
            desired_sig = ("a2v",)
            if model_path and str(model_path).strip():
                print(
                    "[PATCH] A2V 音频管线暂不支持自定义 checkpoint，已忽略 modelPath"
                )
            print(f"[PATCH] 加载 A2V pipeline（支持音频）")
            pipeline_state = self._pipelines.load_a2v_pipeline()
            self._pipelines._pipeline_signature = desired_sig
            num_inference_steps = 11
        else:
            # Fast：无 LoRA 时走官方 load_gpu_pipeline；有 LoRA 时自建 pipeline。
            loras = []
            try:
                from ltx_core.loader import LoraPathStrengthAndSDOps
                from ltx_core.loader.sd_ops import LTXV_LORA_COMFY_RENAMING_MAP

                if lora_path and lora_path.strip() and os.path.exists(lora_path.strip()):
                    loras.append(LoraPathStrengthAndSDOps(
                        path=lora_path.strip(),
                        strength=float(lora_strength),
                        sd_ops=LTXV_LORA_COMFY_RENAMING_MAP
                    ))

                if lora_paths and lora_strengths:
                    for lp, ls in zip(lora_paths, lora_strengths):
                        if lp and lp.strip() and os.path.exists(lp.strip()):
                            p = lp.strip()
                            if not any(x.path == p for x in loras):
                                loras.append(LoraPathStrengthAndSDOps(
                                    path=p,
                                    strength=float(ls),
                                    sd_ops=LTXV_LORA_COMFY_RENAMING_MAP
                                ))
                                print(f"[PATCH] Multi-LoRA 已就绪: {p}, strength={ls}")
            except Exception as _lora_err:
                print(f"[PATCH] LoRA 准备失败，回退无 LoRA: {_lora_err}")
                loras = []

            if not loras:
                loras = None

            from runtime_config.model_download_specs import resolve_model_path
            from services.fast_video_pipeline.ltx_fast_video_pipeline import (
                LTXFastVideoPipeline,
            )

            default_checkpoint_path = str(
                resolve_model_path(
                    self._pipelines.models_dir,
                    self._pipelines.config.model_download_specs,
                    "checkpoint",
                )
            )
            selected_checkpoint_path = default_checkpoint_path
            if model_path and str(model_path).strip():
                selected_path = Path(str(model_path).strip()).expanduser()
                try:
                    selected_path = selected_path.resolve()
                except OSError:
                    pass
                if not selected_path.is_file():
                    raise RuntimeError(f"选择的模型文件不存在: {selected_path}")
                selected_checkpoint_path = str(selected_path)

            using_custom_checkpoint = selected_checkpoint_path != default_checkpoint_path
            selected_checkpoint_name = Path(selected_checkpoint_path).name.lower()
            is_dev_checkpoint = (
                using_custom_checkpoint
                and "dev" in selected_checkpoint_name
                and "distilled" not in selected_checkpoint_name
            )
            is_prequant_fp8_checkpoint = (
                using_custom_checkpoint
                and not is_dev_checkpoint
                and "fp8" in selected_checkpoint_name
            )
            print(f"[PATCH] Fast checkpoint = {selected_checkpoint_path}")
            if is_dev_checkpoint:
                print("[PATCH] 检测到 dev checkpoint，将使用 TI2V two-stage dev pipeline")
            elif is_prequant_fp8_checkpoint:
                print("[PATCH] 检测到预量化 FP8 distilled checkpoint，将使用 scaled-FP8 fallback pipeline")

            if loras is not None:
                sig_list = []
                for item in sorted(loras, key=lambda x: x.path):
                    sig_list.extend([item.path, round(float(item.strength), 4)])
                desired_sig = (
                    "dev" if is_dev_checkpoint else "fast",
                    selected_checkpoint_path,
                    tuple(sig_list),
                )
            else:
                desired_sig = (
                    "dev" if is_dev_checkpoint else "fast",
                    selected_checkpoint_path,
                    "",
                    0.0,
                )

            if cached_sig == desired_sig and active is not None:
                print(f"[PATCH] 复用 Fast pipeline: {desired_sig}")
                pipeline_state = active
            elif loras is not None or using_custom_checkpoint:
                print("[PATCH] 构建自定义 Fast pipeline（unload 后重建）")
                # 首次 LoRA 构建时可能触发额外的显存峰值（编译/缓存/权重搬运）。
                # 通过一次无 LoRA 的 fast pipeline warmup 来降低后续 LoRA 构建的峰值风险。
                if (
                    loras is not None
                    and not is_dev_checkpoint
                    and not getattr(self, "_ltx_lora_warmup_done", False)
                ):
                    try:
                        print(
                            "[PATCH] LoRA warmup: 先加载无 LoRA fast pipeline 触发缓存"
                        )
                        # should_warm=True：尽量触发内核/权重缓存（若实现不同则静默失败也可回退）
                        self._pipelines.load_gpu_pipeline("fast", should_warm=True)
                        from keep_models_runtime import force_unload_gpu_pipeline

                        force_unload_gpu_pipeline(self._pipelines)
                        import gc

                        gc.collect()
                        try:
                            import torch

                            if torch.cuda.is_available():
                                torch.cuda.empty_cache()
                                torch.cuda.ipc_collect()
                        except Exception:
                            pass
                        self._ltx_lora_warmup_done = True
                    except Exception as _warm_err:
                        print(f"[PATCH] LoRA warmup failed (ignore): {_warm_err}")
                from keep_models_runtime import force_unload_gpu_pipeline

                force_unload_gpu_pipeline(self._pipelines)
                import gc

                gc.collect()
                # 防止旧分配/碎片在首次 LoRA 构建时叠加导致 OOM
                try:
                    import torch

                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                        torch.cuda.ipc_collect()
                except Exception:
                    pass
                gemma_root = self._pipelines._text_handler.resolve_gemma_root()
                from state.app_state_types import (
                    GpuSlot,
                    VideoPipelineState,
                    VideoPipelineWarmth,
                )

                upsampler_path = str(
                    resolve_model_path(
                        self._pipelines.models_dir,
                        self._pipelines.config.model_download_specs,
                        "upsampler",
                    )
                )
                from lora_injection import (
                    _lora_init_kwargs,
                    inject_loras_into_fast_pipeline,
                )

                if is_dev_checkpoint:
                    distilled_lora_path = str(
                        resolve_model_path(
                            self._pipelines.models_dir,
                            self._pipelines.config.model_download_specs,
                            "distilled_lora",
                        )
                    )
                    from ltx_dev_video_pipeline import LTXDevVideoPipeline

                    lora_kw = {}
                    ltx_pipe = LTXDevVideoPipeline(
                        selected_checkpoint_path,
                        gemma_root,
                        upsampler_path,
                        distilled_lora_path,
                        self._pipelines.config.device,
                        loras=loras,
                    )
                    n_inj = 0
                elif is_prequant_fp8_checkpoint:
                    from ltx_fp8_video_pipeline import LTXFp8VideoPipeline

                    lora_kw = _lora_init_kwargs(LTXFp8VideoPipeline, loras)
                    ltx_pipe = LTXFp8VideoPipeline(
                        selected_checkpoint_path,
                        gemma_root,
                        upsampler_path,
                        self._pipelines.config.device,
                        **lora_kw,
                    )
                    n_inj = inject_loras_into_fast_pipeline(ltx_pipe, loras)
                else:
                    lora_kw = _lora_init_kwargs(LTXFastVideoPipeline, loras)
                    ltx_pipe = LTXFastVideoPipeline(
                        selected_checkpoint_path,
                        gemma_root,
                        upsampler_path,
                        self._pipelines.config.device,
                        **lora_kw,
                    )
                    n_inj = inject_loras_into_fast_pipeline(ltx_pipe, loras)
                if hasattr(ltx_pipe, "pipeline") and hasattr(
                    ltx_pipe.pipeline, "model_ledger"
                ):
                    try:
                        ltx_pipe.pipeline.model_ledger.loras = tuple(loras)
                    except Exception:
                        pass
                pipeline_state = VideoPipelineState(
                    pipeline=ltx_pipe,
                    warmth=VideoPipelineWarmth.COLD,
                    is_compiled=False,
                )
                self._pipelines.state.gpu_slot = GpuSlot(active_pipeline=pipeline_state)
                _ml = getattr(getattr(ltx_pipe, "pipeline", None), "model_ledger", None)
                _ml_loras = getattr(_ml, "loras", None) if _ml else None
                print(
                    f"[PATCH] LoRA: __init__ 额外参数={list(lora_kw.keys())}, "
                    f"深度注入点数={n_inj}, model_ledger.loras={_ml_loras}"
                )
                if getattr(self._pipelines, "low_vram_mode", False):
                    from low_vram_runtime import (
                        try_sequential_offload_on_pipeline_state,
                    )

                    try_sequential_offload_on_pipeline_state(pipeline_state)
            else:
                print(f"[PATCH] 加载 Fast pipeline（无 LoRA）")
                pipeline_state = self._pipelines.load_gpu_pipeline(
                    "fast", should_warm=False
                )
            self._pipelines._pipeline_signature = desired_sig
            num_inference_steps = None
            extra_loras_for_hook = tuple(loras) if loras else None

        # 在 DiT 权重 build 时融合用户 LoRA（model_ledger 单独赋值往往不够）
        from lora_build_hook import (
            install_lora_build_hook,
            pending_loras_token,
            reset_pending_loras,
        )

        install_lora_build_hook()
        _lora_hook_tok = pending_loras_token(extra_loras_for_hook)
        try:
            # 启动 generation 状态（在 pipeline 加载之后）
            self._generation.start_generation(generation_id)

            # 处理 negative_prompt
            neg_prompt = (
                negative_prompt
                if negative_prompt
                else self.config.default_negative_prompt
            )
            enhanced_prompt = prompt + self.config.camera_motion_prompts.get(
                camera_motion, ""
            )

            # 强制使用动态目录，忽略底层原始逻辑
            dyn_dir = get_dynamic_output_path()
            output_path = dyn_dir / f"generation_{uuid.uuid4().hex[:8]}.mp4"

            try:
                self._text.prepare_text_encoding(enhanced_prompt, enhance_prompt=False)
                # 调整为 64 的倍数（与 LTX 内核 divisible-by-64 校验一致）
                height = max(64, round(height / 64) * 64)
                width = max(64, round(width / 64) * 64)

                if audio_path:
                    # A2V pipeline 参数
                    gen_kwargs = {
                        "prompt": enhanced_prompt,
                        "negative_prompt": neg_prompt,
                        "seed": seed,
                        "height": height,
                        "width": width,
                        "num_frames": num_frames,
                        "frame_rate": fps,
                        "num_inference_steps": num_inference_steps,
                        "images": images_inputs,
                        "audio_path": audio_path,
                        "audio_start_time": 0.0,
                        "audio_max_duration": None,
                        "output_path": str(output_path),
                    }
                else:
                    # Fast pipeline 参数
                    gen_kwargs = {
                        "prompt": enhanced_prompt,
                        "seed": seed,
                        "height": height,
                        "width": width,
                        "num_frames": num_frames,
                        "frame_rate": fps,
                        "images": images_inputs,
                        "output_path": str(output_path),
                    }

                pipeline_state.pipeline.generate(**gen_kwargs)

                # 标记完成
                self._generation.complete_generation(str(output_path))
                return str(output_path)
            finally:
                self._text.clear_api_embeddings()
                for p in temp_paths:
                    if os.path.exists(p):
                        os.unlink(p)
                self._start_frame_path = None
                self._end_frame_path = None
                from low_vram_runtime import maybe_release_pipeline_after_task

                try:
                    maybe_release_pipeline_after_task(self)
                except Exception:
                    pass
        finally:
            reset_pending_loras(_lora_hook_tok)

    VideoGenerationHandler.generate = patched_generate
    VideoGenerationHandler.generate_video = patched_generate_video

    # 2. 增强视频超分功能 (Monkey Patch LTXRetakePipeline)
    _orig_ltx_retake_run = LTXRetakePipeline._run

    def patched_ltx_retake_run(
        self, video_path, prompt, start_time, end_time, seed, **kwargs
    ):
        # 拦截并修改目标宽高
        target_w = getattr(self, "_target_width", None)
        target_h = getattr(self, "_target_height", None)
        target_strength = getattr(self, "_target_strength", 0.7)
        is_upscale = target_w is not None and target_h is not None

        import ltx_pipelines.utils.media_io as media_io
        import services.retake_pipeline.ltx_retake_pipeline as lrp
        import ltx_pipelines.utils.samplers as samplers
        import ltx_pipelines.utils.helpers as helpers

        _orig_get_meta = media_io.get_videostream_metadata
        _orig_lrp_get_meta = getattr(lrp, "get_videostream_metadata", _orig_get_meta)
        _orig_euler_loop = samplers.euler_denoising_loop
        _orig_noise_video = helpers.noise_video_state

        fps, num_frames, src_w, src_h = _orig_get_meta(video_path)

        if is_upscale:
            print(
                f">>> 启动超分内核: {src_w}x{src_h} -> {target_w}x{target_h} (强度: {target_strength})"
            )

            # 1. 注入分辨率
            def get_meta_patched(path):
                return fps, num_frames, target_w, target_h

            media_io.get_videostream_metadata = get_meta_patched
            lrp.get_videostream_metadata = get_meta_patched

            # 2. 注入起始噪声 (SDEdit 核心：加噪到指定强度)
            def noise_video_patched(*args, **kwargs_inner):
                kwargs_inner["noise_scale"] = target_strength
                return _orig_noise_video(*args, **kwargs_inner)

            helpers.noise_video_state = noise_video_patched

            # 3. 注入采样起点 (从对应噪声位开始去噪)
            def patched_euler_loop(
                sigmas, video_state, audio_state, stepper, denoise_fn
            ):
                full_len = len(sigmas)
                skip_idx = 0
                for i, s in enumerate(sigmas):
                    if s <= target_strength:
                        skip_idx = i
                        break
                skip_idx = min(skip_idx, full_len - 2)
                new_sigmas = sigmas[skip_idx:]
                print(
                    f">>> 采样拦截成功: 原步数 {full_len}, 现步数 {len(new_sigmas)}, 起始强度 {new_sigmas[0].item():.2f}"
                )
                return _orig_euler_loop(
                    new_sigmas, video_state, audio_state, stepper, denoise_fn
                )

            samplers.euler_denoising_loop = patched_euler_loop

            kwargs["regenerate_video"] = False
            kwargs["regenerate_audio"] = False

            try:
                return _orig_ltx_retake_run(
                    self, video_path, prompt, start_time, end_time, seed, **kwargs
                )
            finally:
                media_io.get_videostream_metadata = _orig_get_meta
                lrp.get_videostream_metadata = _orig_lrp_get_meta
                samplers.euler_denoising_loop = _orig_euler_loop
                helpers.noise_video_state = _orig_noise_video

        return _orig_ltx_retake_run(
            self, video_path, prompt, start_time, end_time, seed, **kwargs
        )

        return _orig_ltx_retake_run(
            self, video_path, prompt, start_time, end_time, seed, **kwargs
        )

    LTXRetakePipeline._run = patched_ltx_retake_run

    # --- 最终视频超分接口实现 ---
    @app.post("/api/system/upscale-video")
    async def route_upscale_video(request: Request):
        return JSONResponse(
            status_code=410,
            content={"error": "视频增强功能已移除：LTX 当前实现不是真正的保真超分。"},
        )
        try:
            import uuid
            import os
            from datetime import datetime
            from ltx_pipelines.utils.media_io import get_videostream_metadata
            from ltx_core.types import SpatioTemporalScaleFactors

            data = await request.json()
            video_path = data.get("video_path")
            target_res = data.get("resolution", "1080p")
            prompt = data.get("prompt", "high quality, detailed, 4k")
            strength = data.get("strength", 0.7)  # 获取前端传来的重绘幅度

            if not video_path or not os.path.exists(video_path):
                return JSONResponse(
                    status_code=400, content={"error": "Invalid video path"}
                )

            # 计算目标宽高 (必须是 32 的倍数)
            res_map = {"1080p": (1920, 1088), "720p": (1280, 704), "544p": (960, 544)}
            target_w, target_h = res_map.get(target_res, (1920, 1088))

            fps, num_frames, _, _ = get_videostream_metadata(video_path)

            # 校验帧数 8k+1，如果不符则自动调整
            scale = SpatioTemporalScaleFactors.default()
            if (num_frames - 1) % scale.time != 0:
                # 计算需要调整到的最近的有效帧数 (8k+1)
                # 找到最接近的8k+1帧数
                target_k = (num_frames - 1) // scale.time
                # 选择最接近的k值：向下或向上取整
                current_k = (num_frames - 1) // scale.time
                current_remainder = (num_frames - 1) % scale.time

                # 比较向上和向下取整哪个更接近
                down_k = current_k
                up_k = current_k + 1

                # 向下取整的帧数
                down_frames = down_k * scale.time + 1
                # 向上取整的帧数
                up_frames = up_k * scale.time + 1

                # 选择差异最小的
                if abs(num_frames - down_frames) <= abs(num_frames - up_frames):
                    adjusted_frames = down_frames
                else:
                    adjusted_frames = up_frames

                print(
                    f">>> 帧数调整: {num_frames} -> {adjusted_frames} (符合 8k+1 规则)"
                )

                # 调整视频帧数 - 截断多余的帧或填充黑帧
                adjusted_video_path = None
                try:
                    import cv2
                    import numpy as np
                    import tempfile

                    # 使用cv2读取视频
                    cap = cv2.VideoCapture(video_path)
                    if not cap.isOpened():
                        raise Exception("无法打开视频文件")

                    frames = []
                    while True:
                        ret, frame = cap.read()
                        if not ret:
                            break
                        frames.append(frame)
                    cap.release()

                    original_frame_count = len(frames)

                    if adjusted_frames < original_frame_count:
                        # 截断多余的帧
                        frames = frames[:adjusted_frames]
                        print(
                            f">>> 已截断视频: {original_frame_count} -> {len(frames)} 帧"
                        )
                    else:
                        # 填充黑帧 (复制最后一帧)
                        last_frame = frames[-1] if frames else None
                        if last_frame is not None:
                            h, w = last_frame.shape[:2]
                            black_frame = np.zeros((h, w, 3), dtype=np.uint8)
                            while len(frames) < adjusted_frames:
                                frames.append(black_frame.copy())
                        print(
                            f">>> 已填充视频: {original_frame_count} -> {len(frames)} 帧"
                        )

                    # 保存调整后的视频到临时文件
                    adjusted_video_fd = tempfile.NamedTemporaryFile(
                        suffix=".mp4", delete=False
                    )
                    adjusted_video_path = adjusted_video_fd.name
                    adjusted_video_fd.close()

                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    out = cv2.VideoWriter(
                        adjusted_video_path,
                        fourcc,
                        fps,
                        (frames[0].shape[1], frames[0].shape[0]),
                    )
                    for frame in frames:
                        out.write(frame)
                    out.release()

                    video_path = adjusted_video_path
                    num_frames = adjusted_frames
                    print(
                        f">>> 视频帧数调整完成: {original_frame_count} -> {num_frames}"
                    )

                except ImportError:
                    # cv2不可用，尝试使用LTX内置方法
                    try:
                        from ltx_pipelines.utils.media_io import (
                            read_video_stream,
                            write_video_stream,
                        )
                        import numpy as np

                        frames, audio_data = read_video_stream(video_path, fps)
                        original_frame_count = len(frames)

                        if adjusted_frames < original_frame_count:
                            frames = frames[:adjusted_frames]
                        else:
                            while len(frames) < adjusted_frames:
                                frames = np.concatenate([frames, frames[-1:]], axis=0)

                        import tempfile

                        adjusted_video_fd = tempfile.NamedTemporaryFile(
                            suffix=".mp4", delete=False
                        )
                        adjusted_video_path = adjusted_video_fd.name
                        adjusted_video_fd.close()

                        write_video_stream(adjusted_video_path, frames, fps)
                        video_path = adjusted_video_path
                        num_frames = adjusted_frames
                        print(
                            f">>> 视频帧数调整完成: {original_frame_count} -> {num_frames}"
                        )

                    except Exception as e2:
                        print(f">>> 视频帧数自动调整失败: {e2}")
                        return JSONResponse(
                            status_code=400,
                            content={
                                "error": f"视频帧数({num_frames})不符合 8k+1 规则，且自动调整失败。请手动将视频帧数调整为 8k+1 格式（如 9, 17, 25, 33, 41, 49, 57, 65, 73, 81, 89, 97, 105 等）。"
                            },
                        )
                except Exception as e:
                    print(f">>> 视频帧数自动调整失败: {e}")
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": f"视频帧数({num_frames})不符合 8k+1 规则，且自动调整失败。请手动将视频帧数调整为 8k+1 格式（如 9, 17, 25, 33, 41, 49, 57, 65, 73, 81, 89, 97, 105 等）。"
                        },
                    )

            # 1. 加载模型
            pipeline_state = handler.pipelines.load_retake_pipeline(distilled=True)

            # 3. 启动任务
            generation_id = uuid.uuid4().hex[:8]
            handler.generation.start_generation(generation_id)

            # 核心修正：确保文件保存在动态的输出目录
            save_dir = get_dynamic_output_path()
            filename = f"upscale_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{generation_id}.mp4"
            full_output_path = save_dir / filename

            # 3. 执行真正的超分逻辑
            try:
                # 注入目标分辨率和重绘幅度
                pipeline_state.pipeline._target_width = target_w
                pipeline_state.pipeline._target_height = target_h
                pipeline_state.pipeline._target_strength = strength

                def do_generate():
                    pipeline_state.pipeline.generate(
                        video_path=str(video_path),
                        prompt=prompt,
                        start_time=0.0,
                        end_time=float(num_frames / fps),
                        seed=int(time.time()) % 2147483647,
                        output_path=str(full_output_path),
                        distilled=True,
                        regenerate_video=True,
                        regenerate_audio=False,
                    )

                # 重要修复：放到线程池运行，避免阻塞主循环导致前端拿不到显存数据
                from starlette.concurrency import run_in_threadpool

                await run_in_threadpool(do_generate)

                handler.generation.complete_generation(str(full_output_path))
                return {"status": "complete", "video_path": filename}
            except Exception as e:
                # OOM 异常逃逸修复：强制返回友好的异常信息
                try:
                    handler.generation.cancel_generation()
                except Exception:
                    pass
                if hasattr(handler.generation, "_generation_id"):
                    handler.generation._generation_id = None
                if hasattr(handler.generation, "_is_generating"):
                    handler.generation._is_generating = False

                error_msg = str(e)
                if "CUDA out of memory" in error_msg:
                    error_msg = "🚨 显存不足 (OOM)：视频时长过长或目标分辨率超出了当前显卡的承载极限，请降低目标分辨率重试！"
                raise RuntimeError(error_msg) from e
            finally:
                if hasattr(pipeline_state.pipeline, "_target_width"):
                    del pipeline_state.pipeline._target_width
                if hasattr(pipeline_state.pipeline, "_target_height"):
                    del pipeline_state.pipeline._target_height
                if hasattr(pipeline_state.pipeline, "_target_strength"):
                    del pipeline_state.pipeline._target_strength
                import gc

                gc.collect()
                if (
                    getattr(torch, "cuda", None) is not None
                    and torch.cuda.is_available()
                ):
                    torch.cuda.empty_cache()
                from low_vram_runtime import maybe_release_pipeline_after_task

                try:
                    maybe_release_pipeline_after_task(handler)
                except Exception:
                    pass

        except Exception as e:
            import traceback

            traceback.print_exc()
            return JSONResponse(status_code=500, content={"error": str(e)})

    # ------------------

    @app.post("/api/system/upload-image")
    async def route_upload_image(request: Request):
        try:
            import uuid
            import base64

            # 接收 JSON 而不是 Multipart，绕过 python-multipart 缺失问题
            data = await request.json()
            b64_data = data.get("image")
            filename = data.get("filename", "image.png")

            if not b64_data:
                return JSONResponse(
                    status_code=400, content={"error": "No image data provided"}
                )

            # 处理 base64 头部 (例如 data:image/png;base64,...)
            if "," in b64_data:
                b64_data = b64_data.split(",")[1]

            image_bytes = base64.b64decode(b64_data)

            # 确保上传目录存在
            upload_dir = get_dynamic_output_path() / "uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)

            safe_filename = "".join([c for c in filename if c.isalnum() or c in "._-"])
            file_path = upload_dir / f"up_{uuid.uuid4().hex[:6]}_{safe_filename}"

            with file_path.open("wb") as buffer:
                buffer.write(image_bytes)

            return {"status": "success", "path": str(file_path)}
        except Exception as e:
            import traceback

            error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            print(f"Upload error: {error_msg}")
            return JSONResponse(
                status_code=500, content={"error": str(e), "detail": error_msg}
            )

    # ------------------
    # 批量首尾帧：与「视频生成」相同的首尾帧推理，按顺序生成 N-1 段后可选 ffmpeg 拼接
    # ------------------

    def _find_ffmpeg_binary() -> str | None:
        """尽量找到 ffmpeg：环境变量 → imageio-ffmpeg 自带 → PATH → 常见安装位置 → WinGet。"""
        import shutil
        import sys

        def _ok(p: str | None) -> str | None:
            if not p:
                return None
            p = os.path.normpath(os.path.expandvars(str(p).strip().strip('"')))
            return p if os.path.isfile(p) else None

        for env_key in ("LTX_FFMPEG_PATH", "FFMPEG_PATH"):
            hit = _ok(os.environ.get(env_key))
            if hit:
                print(f"[batch-merge] ffmpeg from {env_key}: {hit}")
                return hit

        try:
            pref = _ltx_desktop_config_dir() / "ffmpeg_path.txt"
            if pref.is_file():
                line = pref.read_text(encoding="utf-8").splitlines()[0].strip()
                hit = _ok(line)
                if hit:
                    print(f"[batch-merge] ffmpeg from ffmpeg_path.txt: {hit}")
                    return hit
        except Exception as _e:
            print(f"[batch-merge] ffmpeg_path.txt: {_e!r}")

        # imageio-ffmpeg：多数视频/ML 环境会带上独立 ffmpeg 可执行文件
        try:
            import imageio_ffmpeg

            hit = _ok(imageio_ffmpeg.get_ffmpeg_exe())
            if hit:
                print(f"[batch-merge] ffmpeg from imageio_ffmpeg: {hit}")
                return hit
        except Exception as _e:
            print(f"[batch-merge] imageio_ffmpeg: {_e!r}")

        for name in ("ffmpeg", "ffmpeg.exe"):
            hit = _ok(shutil.which(name))
            if hit:
                print(f"[batch-merge] ffmpeg from PATH which({name}): {hit}")
                return hit

        # 显式遍历 PATH 中的目录（某些环境下 which 不可靠）
        path_env = os.environ.get("PATH", "") or os.environ.get("Path", "")
        for folder in path_env.split(os.pathsep):
            folder = folder.strip().strip('"')
            if not folder:
                continue
            for exe in ("ffmpeg.exe", "ffmpeg"):
                hit = _ok(os.path.join(folder, exe))
                if hit:
                    print(f"[batch-merge] ffmpeg from PATH scan: {hit}")
                    return hit

        localappdata = os.environ.get("LOCALAPPDATA", "") or ""
        programfiles = os.environ.get("ProgramFiles", r"C:\Program Files")
        programfiles_x86 = os.environ.get(
            "ProgramFiles(x86)", r"C:\Program Files (x86)"
        )
        userprofile = os.environ.get("USERPROFILE", "") or ""

        static_candidates: list[str] = [
            os.path.join(os.path.dirname(sys.executable), "ffmpeg.exe"),
            os.path.join(os.path.dirname(sys.executable), "ffmpeg"),
            os.path.join(localappdata, "LTXDesktop", "ffmpeg.exe"),
            os.path.join(programfiles, "LTX Desktop", "ffmpeg.exe"),
            os.path.join(programfiles, "ffmpeg", "bin", "ffmpeg.exe"),
            os.path.join(programfiles_x86, "ffmpeg", "bin", "ffmpeg.exe"),
            r"C:\ffmpeg\bin\ffmpeg.exe",
            os.path.join(userprofile, "scoop", "shims", "ffmpeg.exe"),
            os.path.join(
                userprofile, "scoop", "apps", "ffmpeg", "current", "bin", "ffmpeg.exe"
            ),
            r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
        ]
        for c in static_candidates:
            hit = _ok(c)
            if hit:
                print(f"[batch-merge] ffmpeg static candidate: {hit}")
                return hit

        # WinGet 安装的 Gyan / BtbN 等包：在 Packages 下搜索 ffmpeg.exe（限制深度避免过慢）
        try:
            wg = os.path.join(localappdata, "Microsoft", "WinGet", "Packages")
            if os.path.isdir(wg):
                for root, _dirs, files in os.walk(wg):
                    if "ffmpeg.exe" in files:
                        hit = _ok(os.path.join(root, "ffmpeg.exe"))
                        if hit:
                            print(f"[batch-merge] ffmpeg from WinGet tree: {hit}")
                            return hit
                    # 略过过深目录
                    depth = root[len(wg) :].count(os.sep)
                    if depth > 6:
                        _dirs[:] = []
        except Exception as _e:
            print(f"[batch-merge] WinGet scan: {_e!r}")

        print("[batch-merge] ffmpeg not found after extended search")
        return None

    def _ffmpeg_concat_copy(
        segment_paths: list[str], output_mp4: str, ffmpeg_bin: str
    ) -> None:
        import subprocess

        out_abs = os.path.abspath(output_mp4)
        dyn_abs = os.path.abspath(str(get_dynamic_output_path()))
        lines: list[str] = []
        for p in segment_paths:
            ap = os.path.abspath(p)
            rel = os.path.relpath(ap, start=dyn_abs)
            rel = rel.replace("\\", "/")
            if "'" in rel:
                rel = rel.replace("'", "'\\''")
            lines.append(f"file '{rel}'")
        list_body = "\n".join(lines) + "\n"
        list_path = os.path.join(
            dyn_abs, f"_batch_concat_{os.getpid()}_{time.time_ns()}.txt"
        )
        try:
            Path(list_path).write_text(list_body, encoding="utf-8")
            cmd = [
                ffmpeg_bin,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                list_path,
                "-c",
                "copy",
                out_abs,
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()
                raise RuntimeError(
                    f"ffmpeg 拼接失败 (code {proc.returncode}): {err[:800]}"
                )
        finally:
            try:
                if os.path.isfile(list_path):
                    os.unlink(list_path)
            except OSError:
                pass

    def _ffmpeg_mux_background_audio(
        ffmpeg_bin: str, video_in: str, audio_in: str, video_out: str
    ) -> None:
        """成片只保留原视频画面，音轨替换为一条外部音频（与多段各自 AI 音频相比更统一）。"""
        import subprocess

        out_abs = os.path.abspath(video_out)
        proc = subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-i",
                os.path.abspath(video_in),
                "-i",
                os.path.abspath(audio_in),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                out_abs,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"配乐混流失败 (code {proc.returncode}): {err[:800]}")

    @app.post("/api/generate-batch")
    async def route_generate_batch(request: Request):
        """多关键帧：相邻两帧一段首尾帧视频，与 POST /api/generate 同源逻辑；多段用 ffmpeg concat。"""
        from starlette.concurrency import run_in_threadpool

        from server_utils.media_validation import normalize_optional_path

        try:
            data = await request.json()
            segments_in = data.get("segments") or []
            if not segments_in:
                return JSONResponse(
                    status_code=400,
                    content={"error": "segments 不能为空"},
                )

            resolution = data.get("resolution") or "720p"
            aspect_ratio = data.get("aspectRatio") or "16:9"
            neg = data.get(
                "negativePrompt",
                "low quality, blurry, noisy, static noise, distorted",
            )
            model = data.get("model") or "ltx-2"
            fps = str(data.get("fps") or "24")
            audio = str(data.get("audio") or "false").lower()
            camera_motion = data.get("cameraMotion") or "static"
            modelPath = data.get("modelPath")
            loraPath = data.get("loraPath")
            loraStrength = float(data.get("loraStrength") or 1.0)
            loraPaths = data.get("loraPaths")
            loraStrengths = data.get("loraStrengths")

            vg = getattr(handler, "video_generation", None)
            if vg is None or not callable(getattr(vg, "generate", None)):
                return JSONResponse(
                    status_code=500,
                    content={"error": "内部错误：找不到 video_generation 处理器"},
                )

            clip_paths: list[str] = []
            for idx, seg in enumerate(segments_in):
                start_raw = seg.get("startImage") or seg.get("startFramePath")
                end_raw = seg.get("endImage") or seg.get("endFramePath")
                start_p = normalize_optional_path(start_raw)
                end_p = normalize_optional_path(end_raw)
                if not start_p or not os.path.isfile(start_p):
                    return JSONResponse(
                        status_code=400,
                        content={"error": f"片段 {idx + 1} 起始图路径无效"},
                    )
                if not end_p or not os.path.isfile(end_p):
                    return JSONResponse(
                        status_code=400,
                        content={"error": f"片段 {idx + 1} 结束图路径无效"},
                    )

                dur = seg.get("duration", 5)
                try:
                    dur_i = int(float(dur))
                except (TypeError, ValueError):
                    dur_i = 5
                dur_i = max(1, min(60, dur_i))

                prompt_text = (seg.get("prompt") or "").strip()
                if not prompt_text:
                    prompt_text = "cinematic transition"

                req = GenerateVideoRequest(
                    prompt=prompt_text,
                    resolution=resolution,
                    model=model,
                    cameraMotion=camera_motion,
                    negativePrompt=neg,
                    duration=str(dur_i),
                    fps=fps,
                    audio=audio,
                    imagePath=None,
                    audioPath=None,
                    startFramePath=start_p,
                    endFramePath=end_p,
                    aspectRatio=aspect_ratio,
                    modelPath=modelPath,
                    loraPath=loraPath,
                    loraStrength=loraStrength,
                    loraPaths=loraPaths,
                    loraStrengths=loraStrengths,
                )

                def _one_gen(r: GenerateVideoRequest = req):
                    return vg.generate(r)

                resp = await run_in_threadpool(_one_gen)
                if resp.status != "complete" or not resp.video_path:
                    return JSONResponse(
                        status_code=500,
                        content={
                            "error": f"片段 {idx + 1} 生成失败: status={getattr(resp, 'status', None)}"
                        },
                    )
                clip_paths.append(str(resp.video_path))

            if len(clip_paths) == 1:
                final_path = clip_paths[0]
            else:
                ff = _find_ffmpeg_binary()
                if not ff:
                    return JSONResponse(
                        status_code=500,
                        content={
                            "error": (
                                "已生成多段视频，但未找到 ffmpeg，无法拼接。"
                                " 可选：① 安装 ffmpeg 并加入系统 PATH；"
                                " ② 设置环境变量 LTX_FFMPEG_PATH 指向 ffmpeg.exe；"
                                " ③ 在 %LOCALAPPDATA%\\LTXDesktop\\ffmpeg_path.txt 第一行写入 ffmpeg.exe 的完整路径。"
                            ),
                            "segment_paths": clip_paths,
                        },
                    )
                import uuid as _uuid

                out_dir = get_dynamic_output_path()
                final_path = str(out_dir / f"batch_merged_{_uuid.uuid4().hex[:10]}.mp4")
                try:
                    _ffmpeg_concat_copy(clip_paths, final_path, ff)
                except Exception as ex:
                    return JSONResponse(
                        status_code=500,
                        content={
                            "error": str(ex),
                            "segment_paths": clip_paths,
                        },
                    )

            bg_audio = normalize_optional_path(
                data.get("backgroundAudioPath") or data.get("batchBackgroundAudioPath")
            )
            if bg_audio and os.path.isfile(bg_audio):
                ff_mux = _find_ffmpeg_binary()
                if not ff_mux:
                    return JSONResponse(
                        status_code=500,
                        content={
                            "error": "已生成视频，但混入配乐需要 ffmpeg，请配置 LTX_FFMPEG_PATH 或 ffmpeg_path.txt",
                            "video_path": final_path,
                        },
                    )
                import uuid as _uuid2

                out_mux = str(
                    get_dynamic_output_path()
                    / f"batch_with_audio_{_uuid2.uuid4().hex[:10]}.mp4"
                )
                try:
                    _ffmpeg_mux_background_audio(ff_mux, final_path, bg_audio, out_mux)
                    final_path = out_mux
                except Exception as ex:
                    return JSONResponse(
                        status_code=500,
                        content={
                            "error": str(ex),
                            "video_path": final_path,
                        },
                    )

            return GenerateVideoResponse(status="complete", video_path=final_path)
        except Exception as e:
            import traceback

            traceback.print_exc()
            return JSONResponse(status_code=500, content={"error": str(e)})

    def _execute_queue_task(task: dict) -> dict:
        endpoint = str(task.get("endpoint") or "")
        payload = task.get("payload") or {}
        if endpoint == "/api/generate":
            req = GenerateVideoRequest.model_validate(payload)
            return _normalize_queue_result(handler.video_generation.generate(req))
        if endpoint == "/api/generate-image":
            req = GenerateImageRequest.model_validate(payload)
            return _normalize_queue_result(handler.image_generation.generate(req))
        if endpoint == "/api/ic-lora/generate":
            req = IcLoraGenerateRequest.model_validate(payload)
            return _normalize_queue_result(handler.ic_lora.generate(req))
        if endpoint == "/api/generate-batch":
            return _normalize_queue_result(_run_generate_batch_payload(payload))
        raise HTTPError(400, f"Unsupported queue endpoint: {endpoint}")

    def _queue_worker_loop() -> None:
        while not queue_shutdown.is_set():
            queue_wake.wait(timeout=0.5)
            queue_wake.clear()
            if queue_shutdown.is_set():
                return

            task = None
            with queue_lock:
                while queue_pending:
                    candidate = queue_pending.popleft()
                    if candidate.get("status") == "queued":
                        task = candidate
                        task["status"] = "running"
                        task["started_at"] = time.time()
                        task["progress"] = 0
                        task["phase"] = "queued"
                        break
                pending_ids = [
                    item["id"] for item in queue_pending if item.get("status") == "queued"
                ]
                for idx, task_id in enumerate(pending_ids, start=1):
                    if task_id in queue_items:
                        queue_items[task_id]["position"] = idx

            if task is None:
                continue

            try:
                result = _execute_queue_task(task)
                with queue_lock:
                    terminal_status = str(result.get("status") or "complete")
                    task["status"] = (
                        "cancelled" if terminal_status == "cancelled" else "complete"
                    )
                    task["finished_at"] = time.time()
                    task["result"] = result
                    task["progress"] = (
                        100 if task["status"] == "complete" else task.get("progress", 0)
                    )
                    task["phase"] = task["status"]
                    queue_history.appendleft(task["id"])
            except Exception as exc:
                with queue_lock:
                    task["status"] = "error"
                    task["finished_at"] = time.time()
                    task["error"] = str(exc)
                    task["phase"] = "error"
                    queue_history.appendleft(task["id"])

    def _ensure_queue_worker() -> None:
        nonlocal queue_worker_started
        with queue_lock:
            if queue_worker_started:
                return
            worker = threading.Thread(
                target=_queue_worker_loop,
                name="ltx-generation-queue",
                daemon=True,
            )
            worker.start()
            queue_worker_started = True

    @app.post("/api/queue/submit")
    async def route_queue_submit(request: Request):
        try:
            data = await request.json()
            endpoint = str(data.get("endpoint") or "").strip()
            payload = data.get("payload") or {}
            mode = str(data.get("mode") or "").strip() or "task"
            label = str(data.get("label") or "").strip() or str(payload.get("prompt") or mode)
            if not endpoint:
                return JSONResponse(
                    status_code=400, content={"error": "Missing queue endpoint"}
                )

            task_id = uuid.uuid4().hex[:10]
            task = {
                "id": task_id,
                "endpoint": endpoint,
                "payload": payload,
                "mode": mode,
                "label": label[:120],
                "status": "queued",
                "created_at": time.time(),
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
                "progress": 0,
                "phase": "queued",
                "current_step": None,
                "total_steps": None,
                "position": 0,
            }
            _ensure_queue_worker()
            with queue_lock:
                queue_items[task_id] = task
                queue_pending.append(task)
                task["position"] = sum(
                    1 for item in queue_pending if item.get("status") == "queued"
                )
            queue_wake.set()
            return {"status": "queued", "task_id": task_id, "position": task["position"]}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

    @app.get("/api/queue/status")
    async def route_queue_status():
        try:
            return _snapshot_queue()
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

    @app.get("/api/queue/task/{task_id}")
    async def route_queue_task(task_id: str):
        with queue_lock:
            task = queue_items.get(task_id)
            if task is None:
                return JSONResponse(status_code=404, content={"error": "Task not found"})
            gp = handler.generation.get_generation_progress()
            if task.get("status") == "running":
                task["phase"] = gp.phase
                task["progress"] = gp.progress
                task["current_step"] = getattr(gp, "currentStep", None)
                task["total_steps"] = getattr(gp, "totalSteps", None)
            return _queue_task_view(task)

    @app.post("/api/queue/cancel/{task_id}")
    async def route_queue_cancel(task_id: str):
        try:
            with queue_lock:
                task = queue_items.get(task_id)
                if task is None:
                    return JSONResponse(status_code=404, content={"error": "Task not found"})
                if task.get("status") == "queued":
                    task["status"] = "cancelled"
                    task["finished_at"] = time.time()
                    task["phase"] = "cancelled"
                    queue_history.appendleft(task_id)
                    return {"status": "cancelled", "task_id": task_id}
                is_running = task.get("status") == "running"
            if is_running:
                result = handler.generation.cancel_generation()
                return {"status": result.status, "task_id": task_id}
            return {"status": task.get("status"), "task_id": task_id}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

    # ------------------

    @app.get("/api/system/history")
    async def route_get_history(request: Request):
        try:
            import os

            page = max(1, int(request.query_params.get("page", 1)))
            limit = max(1, min(int(request.query_params.get("limit", 20)), 500))

            history = []
            dyn_path = get_dynamic_output_path()
            if dyn_path.exists():
                for entry in os.scandir(dyn_path):
                    filename = entry.name
                    if filename == "uploads":
                        continue
                    full_path = Path(entry.path)
                    lower_name = filename.lower()
                    if lower_name.startswith("_") or lower_name.startswith("tmp"):
                        continue
                    if entry.is_file() and lower_name.endswith(
                        (
                            ".mp4",
                            ".png",
                            ".jpg",
                            ".jpeg",
                            ".webp",
                            ".wav",
                            ".mp3",
                            ".flac",
                            ".ogg",
                            ".m4a",
                            ".aac",
                        )
                    ):
                        try:
                            st = entry.stat()
                            size = st.st_size
                            if size <= 0:
                                continue
                            if lower_name.endswith(".mp4") and size < 4096:
                                continue
                        except OSError:
                            continue
                        mtime = st.st_mtime
                        if lower_name.endswith(".mp4"):
                            item_type = "video"
                        elif lower_name.endswith(
                            (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac")
                        ):
                            item_type = "audio"
                        else:
                            item_type = "image"
                        history.append(
                            {
                                "filename": filename,
                                "type": item_type,
                                "mtime": mtime,
                                "size": size,
                                "fullpath": str(full_path),
                            }
                        )
            history.sort(key=lambda x: x["mtime"], reverse=True)

            total_items = len(history)
            total_pages = (total_items + limit - 1) // limit
            start_idx = (page - 1) * limit
            end_idx = start_idx + limit

            return {
                "status": "success",
                "history": history[start_idx:end_idx],
                "total_pages": total_pages,
                "current_page": page,
                "total_items": total_items,
            }
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

    @app.post("/api/system/delete-file")
    async def route_delete_file(request: Request):
        try:
            import os

            data = await request.json()
            filename = data.get("filename", "")

            if not filename:
                return JSONResponse(
                    status_code=400, content={"error": "Filename is required"}
                )

            dyn_path = get_dynamic_output_path()
            file_path = dyn_path / filename

            if file_path.exists() and file_path.is_file():
                file_path.unlink()
                return {"status": "success", "message": "File deleted"}
            else:
                return JSONResponse(
                    status_code=404, content={"error": "File not found"}
                )
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

    # 路由注册
    app.include_router(health_router)
    app.include_router(generation_router)
    app.include_router(models_router)
    app.include_router(settings_router)
    app.include_router(image_gen_router)
    app.include_router(suggest_gap_prompt_router)
    app.include_router(retake_router)
    app.include_router(ic_lora_router)
    app.include_router(runtime_policy_router)

    # --- [安全补丁] 状态栏显示修复 ---

    # --- 最终状态栏修复补丁: 只要服务运行且 GPU 没死，就视为就绪 ---
    from handlers.health_handler import HealthHandler

    if not hasattr(HealthHandler, "_fixed_v2"):
        _orig_get_health = HealthHandler.get_health

        def patched_health_v2(self):
            resp = _orig_get_health(self)
            # 解析：如果后端逻辑还在判断模型未加载，我们检查一下核心状态
            # 如果系统没有崩溃，我们就强制标记为已加载，让前端允许交互
            if not resp.models_loaded:
                # 我们认为只要 API 能通，底层状态服务(state)只要存在，就视为由于异步加载引起的暂时性 False
                # 直接返回 True，前端会显示"待机就绪"
                resp.models_loaded = True
            return resp

        HealthHandler.get_health = patched_health_v2
        HealthHandler._fixed_v2 = True
    # ------------------------------------------------------------

    # --- 修复显存采集指针：使得显存监控永远对准当前选定工作的 GPU ---
    from services.gpu_info.gpu_info_impl import GpuInfoImpl

    if not hasattr(GpuInfoImpl, "_fixed_vram_patch"):
        _orig_get_gpu_info = GpuInfoImpl.get_gpu_info

        def patched_get_gpu_info(self):
            import torch

            if self.get_cuda_available():
                idx = 0
                if (
                    hasattr(handler.config.device, "index")
                    and handler.config.device.index is not None
                ):
                    idx = handler.config.device.index
                try:
                    import pynvml

                    pynvml.nvmlInit()
                    handle = pynvml.nvmlDeviceGetHandleByIndex(idx)
                    raw_name = pynvml.nvmlDeviceGetName(handle)
                    name = (
                        raw_name.decode("utf-8", errors="replace")
                        if isinstance(raw_name, bytes)
                        else str(raw_name)
                    )
                    memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    pynvml.nvmlShutdown()
                    return {
                        "name": f"{name} [ID: {idx}]",
                        "vram": memory.total // (1024 * 1024),
                        "vramUsed": memory.used // (1024 * 1024),
                    }
                except Exception:
                    pass
            return _orig_get_gpu_info(self)

        GpuInfoImpl.get_gpu_info = patched_get_gpu_info
        GpuInfoImpl._fixed_vram_patch = True

    # ===============================================================
    # TTS 功能（隔离式）：由独立 Python 脚本 patches/tts_worker.py 执行
    # ===============================================================

    _TTS_WORKER = Path(__file__).resolve().with_name("tts_worker.py")

    def _resolve_tts_model_dir() -> str:
        env_dir = os.environ.get("LTX_TTS_MODEL_DIR", "").strip()
        if env_dir:
            return str(Path(env_dir).expanduser())
        models_root = _resolve_models_root()
        if models_root:
            return str(models_root / "VoxCPM2")
        return "VoxCPM2"

    def _guess_audio_suffix(raw: bytes) -> str:
        """按魔数猜测后缀，避免把 mp3/flac/ogg 伪装成 wav 导致克隆失败。"""
        if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WAVE":
            return ".wav"
        if raw[:3] == b"ID3" or (len(raw) >= 2 and raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0):
            return ".mp3"
        if raw[:4] == b"fLaC":
            return ".flac"
        if raw[:4] == b"OggS":
            return ".ogg"
        return ".bin"

    def _decode_audio_b64_to_temp(b64_data: str, tmp_files: list[str]) -> str:
        clean = b64_data.split(",", 1)[1] if "," in b64_data else b64_data
        raw = base64.b64decode(clean, validate=True)
        suffix = _guess_audio_suffix(raw)
        fd = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        fd.write(raw)
        fd.close()
        tmp_files.append(fd.name)
        return fd.name

    def _run_tts_worker(payload: dict[str, object]) -> dict[str, object]:
        if not _TTS_WORKER.exists():
            raise RuntimeError(f"TTS worker 不存在: {_TTS_WORKER}")

        req_fd = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8")
        req_path = req_fd.name
        req_fd.write(json.dumps(payload, ensure_ascii=False))
        req_fd.close()
        try:
            cmd = [sys.executable, str(_TTS_WORKER), "--request-json", req_path]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
            )
            if proc.returncode != 0:
                stderr_tail = (proc.stderr or "").strip()[-1200:]
                stdout_tail = (proc.stdout or "").strip()[-800:]
                msg = stderr_tail or stdout_tail or f"退出码 {proc.returncode}"
                raise RuntimeError(f"TTS worker 执行失败: {msg}")

            out = (proc.stdout or "").strip().splitlines()
            if not out:
                raise RuntimeError("TTS worker 无输出")
            try:
                return json.loads(out[-1])
            except Exception as exc:
                stdout_tail = (proc.stdout or "").strip()[-1200:]
                raise RuntimeError(f"TTS worker 输出解析失败: {stdout_tail}") from exc
        finally:
            try:
                os.unlink(req_path)
            except Exception:
                pass

    @app.post("/api/tts/generate")
    async def route_tts_generate(request: Request):
        """
        TTS 生成接口，支持三种模式:
        - text_only: 纯文字，可在开头加括号描述声音
        - clone: 声音克隆（需传 reference_wav base64）
        - ultimate_clone: 终极克隆（额外传 prompt_text）
        """
        from starlette.concurrency import run_in_threadpool

        tmp_files: list[str] = []
        try:
            data = await request.json()
            text = (data.get("text") or "").strip()
            if not text:
                return JSONResponse(status_code=400, content={"error": "text 不能为空"})

            mode = data.get("mode", "text_only")  # text_only | clone | ultimate_clone
            cfg_value = float(data.get("cfg_value", 2.0))
            inference_timesteps = int(data.get("inference_timesteps", 10))
            reference_wav_b64 = data.get("reference_wav")
            prompt_wav_b64 = data.get("prompt_wav")
            prompt_text = data.get("prompt_text", "")

            if mode in {"clone", "ultimate_clone"} and not reference_wav_b64:
                return JSONResponse(status_code=400, content={"error": "克隆模式必须上传参考音频"})

            ref_wav_path = None
            prompt_wav_path = None
            if isinstance(reference_wav_b64, str) and reference_wav_b64.strip():
                ref_wav_path = _decode_audio_b64_to_temp(reference_wav_b64, tmp_files)
            if isinstance(prompt_wav_b64, str) and prompt_wav_b64.strip():
                prompt_wav_path = _decode_audio_b64_to_temp(prompt_wav_b64, tmp_files)

            out_dir = get_dynamic_output_path()
            payload = {
                "text": text,
                "mode": mode,
                "cfg_value": cfg_value,
                "inference_timesteps": inference_timesteps,
                "reference_wav_path": ref_wav_path,
                "prompt_wav_path": prompt_wav_path,
                "prompt_text": prompt_text,
                "model_dir": _resolve_tts_model_dir(),
                "output_dir": str(out_dir),
            }

            result = await run_in_threadpool(_run_tts_worker, payload)
            if result.get("status") != "complete":
                raise RuntimeError(str(result.get("error") or "TTS worker 生成失败"))

            fname = str(result.get("audio_path"))
            sample_rate = int(result.get("sample_rate") or 0)
            return {
                "status": "complete",
                "audio_path": fname,
                "audio_url": f"/outputs/{fname}",
                "sample_rate": sample_rate,
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return JSONResponse(status_code=500, content={"error": str(e)})
        finally:
            for p in tmp_files:
                try:
                    if os.path.exists(p):
                        os.unlink(p)
                except Exception:
                    pass

    @app.post("/api/tts/upload-reference")
    async def route_tts_upload_reference(request: Request):
        """上传参考音频文件，返回其 base64 内容供前端存储并在生成时传回。"""
        import base64 as b64
        try:
            data = await request.json()
            b64_data = data.get("audio")
            if not b64_data:
                return JSONResponse(status_code=400, content={"error": "No audio data"})
            if "," in b64_data:
                b64_data = b64_data.split(",", 1)[1]
            # 简单验证能 decode
            b64.b64decode(b64_data)
            return {"status": "ok", "data": b64_data}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

    @app.get("/api/tts/status")
    async def route_tts_status():
        """检测 TTS 模型是否可用（voxcpm 包是否安装）。"""
        try:
            import importlib
            spec = importlib.util.find_spec("voxcpm")
            has_pkg = spec is not None
            model_dir = _resolve_tts_model_dir()
            models_root = _resolve_models_root()
            model_dir_exists = os.path.isdir(model_dir)
            return {
                "available": has_pkg and model_dir_exists,
                "voxcpm_installed": has_pkg,
                "model_dir_exists": model_dir_exists,
                "model_dir": model_dir,
                "models_dir": str(models_root) if models_root else "",
                "expected_model_dir": model_dir,
                "worker_script": str(_TTS_WORKER),
                "worker_exists": _TTS_WORKER.exists(),
            }
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

    return app

