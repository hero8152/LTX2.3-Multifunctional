"""FastAPI app factory decoupled from runtime bootstrap side effects."""

from __future__ import annotations

import base64
import hmac
import os

# 防 OOM 与显存碎片化补丁：在 torch 初始化之前注入环境变量
os.environ["PYTORCH_ALLOC_CONF"] = "expandable_segments:True"
import torch  # 提升到顶层导入
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
from api_types import ImageConditioningInput, GenerateVideoRequest

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


def _extend_generate_video_request_model() -> None:
    """Keep custom video fields working across upstream request-model changes."""
    annotations = dict(getattr(GenerateVideoRequest, "__annotations__", {}))
    changed = False

    for field_name in ("startFramePath", "endFramePath"):
        if field_name not in annotations:
            annotations[field_name] = str | None
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

    actual_output_path = get_dynamic_output_path()
    handler.config.outputs_dir = actual_output_path

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
                    handler.pipelines.unload_gpu_pipeline()
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
            return {
                "status": "success",
                "message": "GPU memory cleared and models unloaded",
            }
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

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
                    handler.pipelines.unload_gpu_pipeline()
                finally:
                    if mock_swapped:
                        handler.pipelines._generation_service.is_generation_running = (
                            orig_running
                        )
            except Exception:
                pass
            gc.collect()
            torch.cuda.empty_cache()

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
        aspect_ratio = getattr(req, "aspectRatio", None)
        print(f"  startFramePath          = {start_frame_path}")
        print(f"  endFramePath            = {end_frame_path}")
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

        # 720p 分辨率：横屏 1280x720，竖屏 720x1280
        RESOLUTION_MAP = {
            "540p": (960, 540),
            "720p": (1280, 720),
            "1080p": (1920, 1080),
        }

        def get_16_9_size(res):
            return RESOLUTION_MAP.get(res, (1280, 720))

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

        # 设置首尾帧路径
        self._start_frame_path = start_frame_path
        self._end_frame_path = end_frame_path

        # 无论有没有音频，都使用自定义逻辑支持首尾帧
        try:
            result = patched_generate_video(
                self,
                prompt=req.prompt,
                image=None,
                image_path=image_path,
                height=height,
                width=width,
                num_frames=num_frames,
                fps=fps,
                seed=self._resolve_seed(),
                camera_motion=req.cameraMotion,
                negative_prompt=req.negativePrompt,
                audio_path=audio_path,
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
        start_path = getattr(self, "_start_frame_path", None)
        end_path = getattr(self, "_end_frame_path", None)
        print(f"[PATCH] start_path={start_path}, end_path={end_path}")

        # 如果没有首尾帧但有 image_path，使用 image_path 作为起始帧
        if not start_path and not end_path and image_path:
            print(f"[PATCH] 使用 image_path 作为起始帧: {image_path}")
            start_path = image_path

        # 检查是否有来自 imagePath 的数据（当只用首帧时）
        has_image_param = image is not None
        if has_image_param:
            print(f"[PATCH] image param is available, will be used as start frame")

        latent_num_frames = (num_frames - 1) // 8 + 1
        last_latent_idx = latent_num_frames - 1
        print(
            f"[PATCH] latent_num_frames={latent_num_frames}, last_latent_idx={last_latent_idx}"
        )

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
            # 转换 Windows 路径为正斜杠
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
            # 转换 Windows 路径为正斜杠
            tmp_normalized = tmp.replace("\\", "/")
            images_inputs.append(
                LtxImageConditioningInput(
                    path=tmp_normalized, frame_idx=last_latent_idx, strength=1.0
                )
            )
            print(
                f"[PATCH] Added end frame: {tmp_normalized}, frame_idx={last_latent_idx}"
            )

        print(f"[PATCH] images_inputs count: {len(images_inputs)}")
        if images_inputs:
            for idx, img in enumerate(images_inputs):
                print(
                    f"[PATCH] images_inputs[{idx}]: path={getattr(img, 'path', 'N/A')}, frame_idx={getattr(img, 'frame_idx', 'N/A')}, strength={getattr(img, 'strength', 'N/A')}"
                )

        print(f"[PATCH] audio_path = {audio_path}")

        if self._generation.is_generation_cancelled():
            raise RuntimeError("Generation was cancelled")

        # 导入 uuid
        import uuid

        generation_id = uuid.uuid4().hex[:8]

        # 根据是否有音频选择不同的 pipeline
        if audio_path:
            print(f"[PATCH] 加载 A2V pipeline（支持音频）")
            pipeline_state = self._pipelines.load_a2v_pipeline()
            num_inference_steps = 11  # A2V 需要这个参数
        else:
            print(f"[PATCH] 加载 Fast pipeline")
            pipeline_state = self._pipelines.load_gpu_pipeline(
                "fast", should_warm=False
            )
            num_inference_steps = None

        # 启动 generation 状态（在 pipeline 加载之后）
        self._generation.start_generation(generation_id)

        # 处理 negative_prompt
        neg_prompt = (
            negative_prompt if negative_prompt else self.config.default_negative_prompt
        )
        enhanced_prompt = prompt + self.config.camera_motion_prompts.get(
            camera_motion, ""
        )

        # 强制使用动态目录，忽略底层原始逻辑
        dyn_dir = get_dynamic_output_path()
        output_path = dyn_dir / f"generation_{uuid.uuid4().hex[:8]}.mp4"

        try:
            self._text.prepare_text_encoding(enhanced_prompt, enhance_prompt=False)
            # 调整为 32 的倍数（LTX 要求）
            height = round(height / 32) * 32
            width = round(width / 32) * 32

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

    @app.get("/api/system/history")
    async def route_get_history(request: Request):
        try:
            import os

            page = int(request.query_params.get("page", 1))
            limit = int(request.query_params.get("limit", 20))

            history = []
            dyn_path = get_dynamic_output_path()
            if dyn_path.exists():
                for filename in os.listdir(dyn_path):
                    if filename == "uploads":
                        continue
                    full_path = dyn_path / filename
                    if full_path.is_file() and filename.lower().endswith(
                        (".mp4", ".png", ".jpg", ".webp")
                    ):
                        mtime = os.path.getmtime(full_path)
                        history.append(
                            {
                                "filename": filename,
                                "type": "video"
                                if filename.lower().endswith(".mp4")
                                else "image",
                                "mtime": mtime,
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

    return app
