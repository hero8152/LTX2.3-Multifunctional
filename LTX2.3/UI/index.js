// ─── Resizable panel drag logic ───────────────────────────────────────────────
(function() {
    const handle = document.getElementById('resize-handle');
    const viewer = document.getElementById('viewer-section');
    const library = document.getElementById('library-section');
    const workspace = document.querySelector('.workspace');
    let dragging = false, startY = 0, startVH = 0;

    handle.addEventListener('mousedown', (e) => {
        dragging = true;
        startY = e.clientY;
        startVH = viewer.getBoundingClientRect().height;
        document.body.style.cursor = 'row-resize';
        document.body.style.userSelect = 'none';
        handle.querySelector('div').style.background = 'var(--accent)';
        e.preventDefault();
    });
    document.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        const wsH = workspace.getBoundingClientRect().height;
        const delta = e.clientY - startY;
        let newVH = startVH + delta;
        // Clamp: viewer min 150px, library min 100px
        newVH = Math.max(150, Math.min(wsH - 100 - 5, newVH));
        viewer.style.flex = 'none';
        viewer.style.height = newVH + 'px';
        library.style.flex = '1';
    });
    document.addEventListener('mouseup', () => {
        if (dragging) {
            dragging = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            handle.querySelector('div').style.background = 'var(--border)';
        }
    });
    // Hover highlight
    handle.addEventListener('mouseenter', () => { handle.querySelector('div').style.background = 'var(--text-dim)'; });
    handle.addEventListener('mouseleave', () => { if (!dragging) handle.querySelector('div').style.background = 'var(--border)'; });
})();
// ──────────────────────────────────────────────────────────────────────────────






// 动态获取当前访问的域名或 IP，自动对齐 3000 端口
    const BASE = `http://${window.location.hostname}:3000`;
    
    let currentMode = 'image';
    let pollInterval = null;
    let isEnglish = false;

    function toggleLang() {
        isEnglish = !isEnglish;
        const lang = isEnglish ? 'en' : 'zh';
        
        document.querySelectorAll('[data-lang-zh]').forEach(el => {
            if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                el.placeholder = el.getAttribute('data-lang-' + lang) || el.placeholder;
            } else {
                el.textContent = el.getAttribute('data-lang-' + lang) || el.textContent;
            }
        });
        
        document.getElementById('langBtn').title = isEnglish ? '切换语言' : 'Toggle Language';
    }

    // 建议增加一个简单的调试日志，方便在控制台确认地址是否正确
    console.log("Connecting to Backend API at:", BASE);

    // 分辨率自动计算逻辑
    function updateResPreview() {
        const q = document.getElementById('vid-quality').value; // "1080", "720", "544"
        const r = document.getElementById('vid-ratio').value;
        
        let resLabel = q === "1080" ? "1080p" : q === "720" ? "720p" : "576p";
        
        let resDisplay;
        if (r === "16:9") {
            resDisplay = q === "1080" ? "1920x1080" : q === "720" ? "1280x720" : "1024x576";
        } else {
            resDisplay = q === "1080" ? "1080x1920" : q === "720" ? "720x1280" : "576x1024";
        }
        
        document.getElementById('res-preview').innerText = `最终发送规格: ${resLabel} (${resDisplay})`;
        return resLabel;
    }

    // 图片分辨率预览
    function updateImgResPreview() {
        const w = document.getElementById('img-w').value;
        const h = document.getElementById('img-h').value;
        document.getElementById('img-res-preview').innerText = `最终发送规格: ${w}x${h}`;
    }

    // 切换图片预设分辨率
    function applyImgPreset(val) {
        if (val === "custom") {
            document.getElementById('img-custom-res').style.display = 'flex';
        } else {
            const [w, h] = val.split('x');
            document.getElementById('img-w').value = w;
            document.getElementById('img-h').value = h;
            updateImgResPreview();
            // 隐藏自定义区域或保持显示供微调
            // document.getElementById('img-custom-res').style.display = 'none';
        }
    }



    // 处理帧图片上传
    async function handleFrameUpload(file, frameType) {
        if (!file) return;

        const preview = document.getElementById(`${frameType}-frame-preview`);
        const placeholder = document.getElementById(`${frameType}-frame-placeholder`);
        const clearOverlay = document.getElementById(`clear-${frameType}-frame-overlay`);

        const previewReader = new FileReader();
        previewReader.onload = (e) => {
            preview.src = e.target.result;
            preview.style.display = 'block';
            placeholder.style.display = 'none';
            clearOverlay.style.display = 'flex';
        };
        previewReader.readAsDataURL(file);

        const reader = new FileReader();
        reader.onload = async (e) => {
            const b64Data = e.target.result;
            addLog(`正在上传 ${frameType === 'start' ? '起始帧' : '结束帧'}: ${file.name}...`);
            try {
                const res = await fetch(`${BASE}/api/system/upload-image`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ image: b64Data, filename: file.name })
                });
                const data = await res.json();
                if (res.ok && data.path) {
                    document.getElementById(`${frameType}-frame-path`).value = data.path;
                    addLog(`✅ ${frameType === 'start' ? '起始帧' : '结束帧'}上传成功`);
                } else {
                    throw new Error(data.error || data.detail || "上传失败");
                }
            } catch (e) {
                addLog(`❌ 帧图片上传失败: ${e.message}`);
            }
        };
        reader.readAsDataURL(file);
    }

    function clearFrame(frameType) {
        document.getElementById(`${frameType}-frame-input`).value = "";
        document.getElementById(`${frameType}-frame-path`).value = "";
        document.getElementById(`${frameType}-frame-preview`).style.display = 'none';
        document.getElementById(`${frameType}-frame-preview`).src = "";
        document.getElementById(`${frameType}-frame-placeholder`).style.display = 'block';
        document.getElementById(`clear-${frameType}-frame-overlay`).style.display = 'none';
        addLog(`🧹 已清除${frameType === 'start' ? '起始帧' : '结束帧'}`);
    }

    // 处理图片上传
    async function handleImageUpload(file) {
        if (!file) return;
        
        // 预览图片
        const preview = document.getElementById('upload-preview');
        const placeholder = document.getElementById('upload-placeholder');
        const clearOverlay = document.getElementById('clear-img-overlay');
        
        const previewReader = new FileReader();
        preview.onload = () => {
            preview.style.display = 'block';
            placeholder.style.display = 'none';
            clearOverlay.style.display = 'flex';
        };
        previewReader.onload = (e) => preview.src = e.target.result;
        previewReader.readAsDataURL(file);

        // 使用 FileReader 转换为 Base64，绕过后端缺失 python-multipart 的问题
        const reader = new FileReader();
        reader.onload = async (e) => {
            const b64Data = e.target.result;
            addLog(`正在上传参考图: ${file.name}...`);
            try {
                const res = await fetch(`${BASE}/api/system/upload-image`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        image: b64Data,
                        filename: file.name
                    })
                });
                const data = await res.json();
                if (res.ok && data.path) {
                    document.getElementById('uploaded-img-path').value = data.path;
                    addLog(`✅ 参考图上传成功: ${file.name}`);
                } else {
                    const errMsg = data.error || data.detail || "上传失败";
                    throw new Error(typeof errMsg === 'string' ? errMsg : JSON.stringify(errMsg));
                }
            } catch (e) {
                addLog(`❌ 图片上传失败: ${e.message}`);
            }
        };
        reader.onerror = () => addLog("❌ 读取本地文件失败");
        reader.readAsDataURL(file);
    }

    function clearUploadedImage() {
        document.getElementById('vid-image-input').value = "";
        document.getElementById('uploaded-img-path').value = "";
        document.getElementById('upload-preview').style.display = 'none';
        document.getElementById('upload-preview').src = "";
        document.getElementById('upload-placeholder').style.display = 'block';
        document.getElementById('clear-img-overlay').style.display = 'none';
        addLog("🧹 已清除参考图");
    }

    // 处理音频上传
    async function handleAudioUpload(file) {
        if (!file) return;

        const placeholder = document.getElementById('audio-upload-placeholder');
        const statusDiv = document.getElementById('audio-upload-status');
        const filenameStatus = document.getElementById('audio-filename-status');
        const clearOverlay = document.getElementById('clear-audio-overlay');

        placeholder.style.display = 'none';
        filenameStatus.innerText = file.name;
        statusDiv.style.display = 'block';
        clearOverlay.style.display = 'flex';

        const reader = new FileReader();
        reader.onload = async (e) => {
            const b64Data = e.target.result;
            addLog(`正在上传音频: ${file.name}...`);
            try {
                // 复用图片上传接口，后端已支持任意文件类型
                const res = await fetch(`${BASE}/api/system/upload-image`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        image: b64Data,
                        filename: file.name
                    })
                });
                const data = await res.json();
                if (res.ok && data.path) {
                    document.getElementById('uploaded-audio-path').value = data.path;
                    addLog(`✅ 音频上传成功: ${file.name}`);
                } else {
                    const errMsg = data.error || data.detail || "上传失败";
                    throw new Error(typeof errMsg === 'string' ? errMsg : JSON.stringify(errMsg));
                }
            } catch (e) {
                addLog(`❌ 音频上传失败: ${e.message}`);
            }
        };
        reader.onerror = () => addLog("❌ 读取本地音频文件失败");
        reader.readAsDataURL(file);
    }

    function clearUploadedAudio() {
        document.getElementById('vid-audio-input').value = "";
        document.getElementById('uploaded-audio-path').value = "";
        document.getElementById('audio-upload-placeholder').style.display = 'block';
        document.getElementById('audio-upload-status').style.display = 'none';
        document.getElementById('clear-audio-overlay').style.display = 'none';
        addLog("🧹 已清除音频文件");
    }

    // 处理超分视频上传
    async function handleUpscaleVideoUpload(file) {
        if (!file) return;
        const placeholder = document.getElementById('upscale-placeholder');
        const statusDiv = document.getElementById('upscale-status');
        const filenameStatus = document.getElementById('upscale-filename');
        const clearOverlay = document.getElementById('clear-upscale-overlay');

        filenameStatus.innerText = file.name;
        placeholder.style.display = 'none';
        statusDiv.style.display = 'block';
        clearOverlay.style.display = 'flex';

        const reader = new FileReader();
        reader.onload = async (e) => {
            const b64Data = e.target.result;
            addLog(`正在上传待超分视频: ${file.name}...`);
            try {
                const res = await fetch(`${BASE}/api/system/upload-image`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ image: b64Data, filename: file.name })
                });
                const data = await res.json();
                if (res.ok && data.path) {
                    document.getElementById('upscale-video-path').value = data.path;
                    addLog(`✅ 视频上传成功`);
                } else {
                    throw new Error(data.error || "上传失败");
                }
            } catch (e) {
                addLog(`❌ 视频上传失败: ${e.message}`);
            }
        };
        reader.readAsDataURL(file);
    }

    function clearUpscaleVideo() {
        document.getElementById('upscale-video-input').value = "";
        document.getElementById('upscale-video-path').value = "";
        document.getElementById('upscale-placeholder').style.display = 'block';
        document.getElementById('upscale-status').style.display = 'none';
        document.getElementById('clear-upscale-overlay').style.display = 'none';
        addLog("🧹 已清除待超分视频");
    }

    // 初始化拖拽上传逻辑
    function initDragAndDrop() {
        const audioDropZone = document.getElementById('audio-drop-zone');
        const startFrameDropZone = document.getElementById('start-frame-drop-zone');
        const endFrameDropZone = document.getElementById('end-frame-drop-zone');
        const upscaleDropZone = document.getElementById('upscale-drop-zone');
        
        const zones = [audioDropZone, startFrameDropZone, endFrameDropZone, upscaleDropZone];

        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            zones.forEach(zone => {
                if (!zone) return;
                zone.addEventListener(eventName, (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                }, false);
            });
        });

        ['dragenter', 'dragover'].forEach(eventName => {
            zones.forEach(zone => {
                if (!zone) return;
                zone.addEventListener(eventName, () => zone.classList.add('dragover'), false);
            });
        });

        ['dragleave', 'drop'].forEach(eventName => {
            zones.forEach(zone => {
                if (!zone) return;
                zone.addEventListener(eventName, () => zone.classList.remove('dragover'), false);
            });
        });

        audioDropZone.addEventListener('drop', (e) => {
            const file = e.dataTransfer.files[0];
            if (file && file.type.startsWith('audio/')) handleAudioUpload(file);
        }, false);

        startFrameDropZone.addEventListener('drop', (e) => {
            const file = e.dataTransfer.files[0];
            if (file && file.type.startsWith('image/')) handleFrameUpload(file, 'start');
        }, false);

        endFrameDropZone.addEventListener('drop', (e) => {
            const file = e.dataTransfer.files[0];
            if (file && file.type.startsWith('image/')) handleFrameUpload(file, 'end');
        }, false);

        upscaleDropZone.addEventListener('drop', (e) => {
            const file = e.dataTransfer.files[0];
            if (file && file.type.startsWith('video/')) handleUpscaleVideoUpload(file);
        }, false);
    }

    let _isGeneratingFlag = false;

    // 系统状态轮询
    async function checkStatus() {
        try {
            const h = await fetch(`${BASE}/health`).then(r => r.json()).catch(() => ({status: "error"}));
            const g = await fetch(`${BASE}/api/gpu-info`).then(r => r.json()).catch(() => ({gpu_info: {}}));
            const p = await fetch(`${BASE}/api/generation/progress`).then(r => r.json()).catch(() => ({progress: 0}));
            const sysGpus = await fetch(`${BASE}/api/system/list-gpus`).then(r => r.json()).catch(() => ({gpus: []}));
            
            const activeGpu = (sysGpus.gpus || []).find(x => x.active) || (sysGpus.gpus || [])[0] || {};
            const gpuName = activeGpu.name || g.gpu_info?.name || "GPU";
            
            const s = document.getElementById('sys-status');
            const indicator = document.getElementById('sys-indicator');
            
            const isReady = h.status === "ok" || h.status === "ready" || h.models_loaded;
            const backendActive = (p && p.progress > 0);
            
            if (_isGeneratingFlag || backendActive) {
                s.innerText = `${gpuName}: 运算中...`;
                if(indicator) indicator.className = 'indicator-busy';
            } else {
                s.innerText = isReady ? `${gpuName}: 在线 / 就绪` : `${gpuName}: 启动中...`;
                if(indicator) indicator.className = isReady ? 'indicator-ready' : 'indicator-offline';
            }
            s.style.color = "var(--text-dim)";

            const vUsedMB = g.gpu_info?.vramUsed || 0;
            const vTotalMB = activeGpu.vram_mb || g.gpu_info?.vram || 32768; 
            const vUsedGB = vUsedMB / 1024;
            const vTotalGB = vTotalMB / 1024;
            
            document.getElementById('vram-fill').style.width = (vUsedMB / vTotalMB * 100) + "%";
            document.getElementById('vram-text').innerText = `${vUsedGB.toFixed(1)} / ${vTotalGB.toFixed(0)} GB`;
        } catch(e) { document.getElementById('sys-status').innerText = "未检测到后端 (Port 3000)"; }
    }
    setInterval(checkStatus, 1000); // 提升到 1 秒一次实时监控
    checkStatus();
    initDragAndDrop();
    listGpus(); // 初始化 GPU 列表
    getOutputDir(); // 获取当前的保存路径

    async function setOutputDir() {
        const dir = document.getElementById('global-out-dir').value.trim();
        try {
            const res = await fetch(`${BASE}/api/system/set-dir`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ directory: dir })
            });
            if (res.ok) {
                addLog(`✅ 存储路径更新成功! 当前路径: ${dir || '默认路径'}`);
                if (typeof fetchHistory === 'function') fetchHistory(currentHistoryPage);
            }
        } catch (e) {
            addLog(`❌ 设置路径时连接异常: ${e.message}`);
        }
    }

    async function browseOutputDir() {
        try {
            const res = await fetch(`${BASE}/api/system/browse-dir`);
            const data = await res.json();
            if (data.status === "success" && data.directory) {
                document.getElementById('global-out-dir').value = data.directory;
                // auto apply immediately
                setOutputDir();
                addLog(`📂 检测到新路径，已自动套用！`);
            } else if (data.error) {
                addLog(`❌ 内部系统权限拦截了弹窗: ${data.error}`);
            }
        } catch (e) {
            addLog(`❌ 无法调出文件夹浏览弹窗, 请直接复制粘贴绝对路径。`);
        }
    }

    async function getOutputDir() {
        try {
            const res = await fetch(`${BASE}/api/system/get-dir`);
            const data = await res.json();
            if (data.directory && data.directory.indexOf('LTXDesktop') === -1 && document.getElementById('global-out-dir')) {
                document.getElementById('global-out-dir').value = data.directory;
            }
        } catch (e) {}
    }

    function switchMode(m) {
        currentMode = m;
        document.getElementById('tab-image').classList.toggle('active', m === 'image');
        document.getElementById('tab-video').classList.toggle('active', m === 'video');
        document.getElementById('tab-upscale').classList.toggle('active', m === 'upscale');
        
        document.getElementById('image-opts').style.display = m === 'image' ? 'block' : 'none';
        document.getElementById('video-opts').style.display = m === 'video' ? 'block' : 'none';
        document.getElementById('upscale-opts').style.display = m === 'upscale' ? 'block' : 'none';
        
        // 如果切到图像模式，隐藏提示词框外的其他东西
        document.getElementById('prompt').placeholder = m === 'upscale' ? "输入画面增强引导词 (可选)..." : "在此输入视觉描述词 (Prompt)...";
    }

    function showGeneratingView() {
        if (!_isGeneratingFlag) return;
        const resImg = document.getElementById('res-img');
        const videoWrapper = document.getElementById('video-wrapper');
        if (resImg) resImg.style.display = "none";
        if (videoWrapper) videoWrapper.style.display = "none";
        if (player) {
            try { player.stop(); } catch(_) {}
        } else {
            const vid = document.getElementById('res-video');
            if (vid) { vid.pause(); vid.removeAttribute('src'); vid.load(); }
        }
        const loadingTxt = document.getElementById('loading-txt');
        if (loadingTxt) loadingTxt.style.display = "flex";
    }

    async function run() {
        // 防止重复点击（_isGeneratingFlag 比 btn.disabled 更可靠）
        if (_isGeneratingFlag) {
            addLog("⚠️ 当前正在生成中，请等待完成");
            return;
        }

        const btn = document.getElementById('mainBtn');
        const prompt = document.getElementById('prompt').value.trim();

        if (currentMode !== 'upscale' && !prompt) {
            addLog("⚠️ 请输入提示词后再开始渲染");
            return;
        }

        // 先设置标志 + 禁用按钮，然后用顶层 try/finally 保证一定能解锁
        _isGeneratingFlag = true;
        btn.disabled = true;

        try {
            // 安全地操作 UI 元素（改用 if 判空，防止 Plyr 接管后 getElementById 返回 null）
            const loader = document.getElementById('loading-txt');
            const resImg = document.getElementById('res-img');
            const resVideo = document.getElementById('res-video');

            if (loader) {
                loader.style.display = "flex";
                loader.style.flexDirection = "column";
                loader.style.alignItems = "center";
                loader.style.gap = "12px";
                loader.innerHTML = `
                    <div class="spinner" style="width:48px;height:48px;border-width:4px;color:var(--accent);"></div>
                    <div id="loader-step-text" style="font-size:13px;font-weight:700;color:var(--text-sub);">GPU 正在分配资源...</div>
                `;
            }
            if (resImg) resImg.style.display = "none";
            // 必须隐藏整个 video-wrapper（Plyr 外层容器），否则第二次生成时视频会与 spinner 叠加
            const videoWrapper = document.getElementById('video-wrapper');
            if (videoWrapper) videoWrapper.style.display = "none";
            if (player) { try { player.stop(); } catch(_) {} }
            else if (resVideo) { resVideo.pause?.(); resVideo.removeAttribute?.('src'); }

        checkStatus();

            // 重置后端状态锁（非关键，失败不影响主流程）
            try { await fetch(`${BASE}/api/system/reset-state`, { method: 'POST' }); } catch(_) {}

            startProgressPolling();

            // ---- 新增：在历史记录区插入「正在渲染」缩略图卡片 ----
            const historyContainer = document.getElementById('history-container');
            if (historyContainer) {
                const old = document.getElementById('current-loading-card');
                if (old) old.remove();
                const loadingCard = document.createElement('div');
                loadingCard.className = 'history-card loading-card';
                loadingCard.id = 'current-loading-card';
                loadingCard.onclick = showGeneratingView;
                loadingCard.innerHTML = `
                    <div class="spinner"></div>
                    <div id="loading-card-step" style="font-size:10px;color:var(--text-dim);margin-top:4px;">等待中...</div>
                `;
                historyContainer.prepend(loadingCard);
            }

            // ---- 构建请求 ----
            let endpoint, payload;
            if (currentMode === 'image') {
                const w = parseInt(document.getElementById('img-w').value);
                const h = parseInt(document.getElementById('img-h').value);
                endpoint = '/api/generate-image';
                payload = {
                    prompt, width: w, height: h,
                    numSteps: parseInt(document.getElementById('img-steps').value),
                    numImages: 1
                };
                addLog(`正在发起图像渲染: ${w}x${h}, Steps: ${payload.numSteps}`);

            } else if (currentMode === 'video') {
                const res = updateResPreview();
                const dur = parseFloat(document.getElementById('vid-duration').value);
                const fps = document.getElementById('vid-fps').value;
                if (dur > 20) addLog(`⚠️ 时长设定为 ${dur}s 极长，可能导致显存溢出或耗时较久。`);

                const audio = document.getElementById('vid-audio').checked ? "true" : "false";
                const audioPath = document.getElementById('uploaded-audio-path').value;
                const startFramePathValue = document.getElementById('start-frame-path').value;
                const endFramePathValue = document.getElementById('end-frame-path').value;

                let finalImagePath = null, finalStartFramePath = null, finalEndFramePath = null;
                if (startFramePathValue && endFramePathValue) {
                    finalStartFramePath = startFramePathValue;
                    finalEndFramePath = endFramePathValue;
                } else if (startFramePathValue) {
                    finalImagePath = startFramePathValue;
                }

                endpoint = '/api/generate';
                payload = {
                    prompt, resolution: res, model: "ltx-2",
                    cameraMotion: document.getElementById('vid-motion').value,
                    negativePrompt: "low quality, blurry, noisy, static noise, distorted",
                    duration: String(dur), fps, audio,
                    imagePath: finalImagePath,
                    audioPath: audioPath || null,
                    startFramePath: finalStartFramePath,
                    endFramePath: finalEndFramePath,
                    aspectRatio: document.getElementById('vid-ratio').value
                };
                addLog(`正在发起视频渲染: ${res}, 时长: ${dur}s, FPS: ${fps}, 音频: ${audio}, 参考图: ${finalImagePath ? '已加载' : '无'}, 参考音频: ${audioPath ? '已加载' : '无'}, 插帧: ${finalStartFramePath && finalEndFramePath ? '已加载' : '无'}, 镜头: ${payload.cameraMotion}`);

            } else if (currentMode === 'upscale') {
                const videoPath = document.getElementById('upscale-video-path').value;
                const targetRes = document.getElementById('upscale-res').value;
                if (!videoPath) throw new Error("请先上传待超分的视频");
                endpoint = '/api/system/upscale-video';
                payload = { video_path: videoPath, resolution: targetRes, prompt: "high quality, detailed, 4k", strength: 0.7 };
                addLog(`正在发起视频超分: 目标 ${targetRes}`);
            }

            // ---- 发送请求 ----
            const res = await fetch(BASE + endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (!res.ok) {
                const errMsg = data.error || data.detail || "API 拒绝了请求";
                throw new Error(typeof errMsg === 'string' ? errMsg : JSON.stringify(errMsg));
            }

            // ---- 显示结果 ----
            const rawPath = data.image_paths ? data.image_paths[0] : data.video_path;
            if (rawPath) {
                try { displayOutput(rawPath); } catch (dispErr) { addLog(`⚠️ 播放器显示异常: ${dispErr.message}`); }
            }

            // 强制刷新历史记录（不依赖 isLoadingHistory 标志，确保新生成的视频立即显示）
            setTimeout(() => {
                isLoadingHistory = false; // 强制重置状态
                if (typeof fetchHistory === 'function') fetchHistory(1);
            }, 500);

        } catch (e) {
            addLog(`❌ 渲染中断: ${e.message}`);
            const loader = document.getElementById('loading-txt');
            if (loader) loader.innerText = "渲染失败，请检查显存或参数";

        } finally {
            // ✅ 无论发生什么，这里一定执行，确保按钮永远可以再次点击
            _isGeneratingFlag = false;
            btn.disabled = false;
            stopProgressPolling();
            checkStatus();
            // 生成完毕后自动释放显存，降低 VRAM 压力（不 await 避免阻塞 UI 解锁）
            setTimeout(() => clearGpu(), 500);
        }
    }

    async function clearGpu() {
        const btn = document.getElementById('clearGpuBtn');
        btn.disabled = true;
        btn.innerText = "清理中...";
        try {
            const res = await fetch(`${BASE}/api/system/clear-gpu`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await res.json();
            if (res.ok) {
                addLog(`🧹 显存清理成功: ${data.message}`);
                // 立即触发状态刷新
                checkStatus();
                setTimeout(checkStatus, 1000); 
            } else {
                const errMsg = data.error || data.detail || "后端未实现此接口 (404)";
                throw new Error(errMsg);
            }
        } catch(e) {
            addLog(`❌ 清理显存失败: ${e.message}`);
        } finally {
            btn.disabled = false;
            btn.innerText = "释放显存";
        }
    }

    async function listGpus() {
        try {
            const res = await fetch(`${BASE}/api/system/list-gpus`);
            const data = await res.json();
            if (res.ok && data.gpus) {
                const selector = document.getElementById('gpu-selector');
                selector.innerHTML = data.gpus.map(g => 
                    `<option value="${g.id}" ${g.active ? 'selected' : ''}>GPU ${g.id}: ${g.name} (${g.vram})</option>`
                ).join('');
                
                // 更新当前显示的 GPU 名称
                const activeGpu = data.gpus.find(g => g.active);
                if (activeGpu) document.getElementById('gpu-name').innerText = activeGpu.name;
            }
        } catch (e) {
            console.error("Failed to list GPUs", e);
        }
    }

    async function switchGpu(id) {
        if (!id) return;
        addLog(`🔄 正在切换到 GPU ${id}...`);
        try {
            const res = await fetch(`${BASE}/api/system/switch-gpu`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ gpu_id: parseInt(id) })
            });
            const data = await res.json();
            if (res.ok) {
                addLog(`✅ 已成功切换到 GPU ${id}，模型将重新加载。`);
                listGpus(); // 重新获取列表以同步状态
                setTimeout(checkStatus, 1000);
            } else {
                throw new Error(data.error || "切换失败");
            }
        } catch (e) {
            addLog(`❌ GPU 切换失败: ${e.message}`);
        }
    }

    function startProgressPolling() {
        if (pollInterval) clearInterval(pollInterval);
        pollInterval = setInterval(async () => {
            try {
                const res = await fetch(`${BASE}/api/generation/progress`);
                const d = await res.json();
                if (d.progress > 0) {
                    const phaseMap = {
                        'loading_model': '加载权重',
                        'encoding_text': 'T5 编码',
                        'validating_request': '校验请求',
                        'uploading_audio': '上传音频',
                        'uploading_image': '上传图像',
                        'inference': 'AI 推理',
                        'downloading_output': '下载结果',
                        'complete': '完成'
                    };
                    const phaseStr = phaseMap[d.phase] || d.phase || '推理';

                    // 步骤格式：优先显示 current_step/total_steps，降级用百分比
                    let stepLabel;
                    if (d.current_step !== undefined && d.current_step !== null && d.total_steps) {
                        stepLabel = `${d.current_step}/${d.total_steps} 步`;
                    } else {
                        stepLabel = `${d.progress}%`;
                    }

                    document.getElementById('progress-fill').style.width = d.progress + "%";
                    // 更新主预览区的进度文字（内嵌子元素）
                    const loaderStep = document.getElementById('loader-step-text');
                    if (loaderStep) loaderStep.innerText = `GPU 运算中: ${stepLabel}  [ ${phaseStr} ]`;
                    else {
                        const loadingTxt = document.getElementById('loading-txt');
                        if (loadingTxt) loadingTxt.innerText = `GPU 运算中: ${stepLabel} [${phaseStr}]`;
                    }

                    // 同步更新历史缩略图卡片上的进度文字
                    const cardStep = document.getElementById('loading-card-step');
                    if (cardStep) cardStep.innerText = stepLabel;
                }
            } catch(e) {}
        }, 1000);
    }

    function stopProgressPolling() {
        clearInterval(pollInterval);
        pollInterval = null;
        document.getElementById('progress-fill').style.width = "0%";
        // 移除渲染中的卡片（生成已结束）
        const lc = document.getElementById('current-loading-card');
        if (lc) lc.remove();
    }

    function displayOutput(fileOrPath) {
        const img = document.getElementById('res-img');
        const vid = document.getElementById('res-video');
        const loader = document.getElementById('loading-txt');
        
        // 关键BUG修复：切换前强制清除并停止现有视频和声音，避免后台继续播放
        if(player) {
            player.stop();
        } else {
            vid.pause();
            vid.removeAttribute('src');
            vid.load();
        }
        
        let url = "";
        let fileName = fileOrPath;
        if (fileOrPath.indexOf('\\') !== -1 || fileOrPath.indexOf('/') !== -1) {
            url = `${BASE}/api/system/file?path=${encodeURIComponent(fileOrPath)}&t=${Date.now()}`;
            fileName = fileOrPath.split(/[\\/]/).pop();
        } else {
            const outInput = document.getElementById('global-out-dir');
            const globalDir = outInput ? outInput.value.replace(/\\/g, '/').replace(/\/$/, '') : "";
            if (globalDir && globalDir !== "") {
                url = `${BASE}/api/system/file?path=${encodeURIComponent(globalDir + '/' + fileOrPath)}&t=${Date.now()}`;
            } else {
                url = `${BASE}/outputs/${fileOrPath}?t=${Date.now()}`;
            }
        }

        loader.style.display = "none";
        if (currentMode === 'image') {
            img.src = url;
            img.style.display = "block";
            addLog(`✅ 图像渲染成功: ${fileName}`);
        } else {
            document.getElementById('video-wrapper').style.display = "flex";
            
            if(player) {
                player.source = {
                    type: 'video',
                    sources: [{ src: url, type: 'video/mp4' }]
                };
                player.play();
            } else {
                vid.src = url;
            }
            addLog(`✅ 视频渲染成功: ${fileName}`);
        }
    }



    function addLog(msg) {
        const log = document.getElementById('log');
        const time = new Date().toLocaleTimeString();
        log.innerHTML += `<div style="margin-bottom:5px"> <span style="color:var(--text-dim)">[${time}]</span> ${msg}</div>`;
        log.scrollTop = log.scrollHeight;
    }


// Force switch to video mode on load
window.addEventListener('DOMContentLoaded', () => switchMode('video'));


    
    
    
    
    
    
    
    
    
    
    let isLoadingHistory = false;

    function switchLibTab(tab) {
        document.getElementById('log-container').style.display = tab === 'log' ? 'flex' : 'none';
        const hw = document.getElementById('history-wrapper');
        if (hw) hw.style.display = tab === 'history' ? 'block' : 'none';
        
        document.getElementById('tab-log').style.color = tab === 'log' ? 'var(--accent)' : 'var(--text-dim)';
        document.getElementById('tab-log').style.borderColor = tab === 'log' ? 'var(--accent)' : 'transparent';
        
        document.getElementById('tab-history').style.color = tab === 'history' ? 'var(--accent)' : 'var(--text-dim)';
        document.getElementById('tab-history').style.borderColor = tab === 'history' ? 'var(--accent)' : 'transparent';
        
        if (tab === 'history') {
            fetchHistory();
        }
    }

    async function fetchHistory(isFirstLoad = false, silent = false) {
        if (isLoadingHistory) return;
        isLoadingHistory = true;
        
        try {
            // 加载所有历史，不分页
            const res = await fetch(`${BASE}/api/system/history?page=1&limit=10000`);
            if (!res.ok) {
                isLoadingHistory = false;
                return;
            }
            const data = await res.json();
            
            if (data.history && data.history.length > 0) {
                const container = document.getElementById('history-container');
                
                // 清空容器
                let loadingCardHtml = "";
                const lc = document.getElementById('current-loading-card');
                if (lc && _isGeneratingFlag) {
                    loadingCardHtml = lc.outerHTML;
                }
                container.innerHTML = loadingCardHtml;

                const outInput = document.getElementById('global-out-dir');
                const globalDir = outInput ? outInput.value.replace(/\\/g, '/').replace(/\/$/, '') : "";
                
                // 过滤无效数据
                const validHistory = data.history.filter(item => item && item.filename);
                
                const cardsHtml = validHistory.map((item, index) => {
                    const url = (globalDir && globalDir !== "") 
                        ? `${BASE}/api/system/file?path=${encodeURIComponent(globalDir + '/' + item.filename)}` 
                        : `${BASE}/outputs/${item.filename}`;
                        
                    const safeFilename = item.filename.replace(/'/g, "\\'").replace(/"/g, '\\"');
                    const media = item.type === 'video' 
                        ? `<video data-src="${url}#t=0.001" class="lazy-load" muted loop preload="none" onmouseover="if(this.readyState >= 2) this.play()" onmouseout="this.pause()" style="pointer-events: none; object-fit: cover; width: 100%; height: 100%;"></video>` 
                        : `<img data-src="${url}" class="lazy-load" style="object-fit: cover; width: 100%; height: 100%;">`;
                    return `<div class="history-card" onclick="displayHistoryOutput('${safeFilename}', '${item.type}')">
                                <div class="history-type-badge">${item.type === 'video' ? '🎬 VID' : '🎨 IMG'}</div>
                                <button class="history-delete-btn" onclick="event.stopPropagation(); deleteHistoryItem('${safeFilename}', '${item.type}', this)">✕</button>
                                ${media}
                            </div>`;
                }).join('');

                container.insertAdjacentHTML('beforeend', cardsHtml);

                // 重新绑定loading card点击事件
                const newLc = document.getElementById('current-loading-card');
                if (newLc) newLc.onclick = showGeneratingView;
                
                // 加载可见的图片
                loadVisibleImages();
            }
        } catch(e) {
            console.error("Failed to load history", e);
        } finally {
            isLoadingHistory = false;
        }
    }
    
    async function deleteHistoryItem(filename, type, btn) {
        if (!confirm(`确定要删除 "${filename}" 吗？`)) return;
        
        try {
            const res = await fetch(`${BASE}/api/system/delete-file`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({filename: filename, type: type})
            });
            
            if (res.ok) {
                // 删除成功后移除元素
                const card = btn.closest('.history-card');
                if (card) {
                    card.remove();
                }
            } else {
                alert('删除失败');
            }
        } catch(e) {
            console.error('Delete failed', e);
            alert('删除失败');
        }
    }

    function loadVisibleImages() {
        const hw = document.getElementById('history-wrapper');
        if (!hw) return;
        
        const lazyMedias = document.querySelectorAll('#history-container .lazy-load');
        
        // 每次只加载3个媒体元素（图片或视频）
        let loadedCount = 0;
        lazyMedias.forEach(media => {
            if (loadedCount >= 3) return;
            
            const src = media.dataset.src;
            if (!src) return;
            
            // 检查是否在可见区域附近
            const rect = media.getBoundingClientRect();
            const containerRect = hw.getBoundingClientRect();
            
            if (rect.top < containerRect.bottom + 300 && rect.bottom > containerRect.top - 100) {
                media.src = src;
                media.classList.remove('lazy-load');
                
                // 视频需要额外设置 preload
                if (media.tagName === 'VIDEO') {
                    media.preload = 'metadata';
                }
                
                loadedCount++;
            }
        });
        
        // 继续检查直到没有更多媒体需要加载
        if (loadedCount > 0) {
            setTimeout(loadVisibleImages, 100);
        }
    }

    // 监听history-wrapper的滚动事件来懒加载
    function initHistoryScrollListener() {
        const hw = document.getElementById('history-wrapper');
        if (!hw) return;
        
        let scrollTimeout;
        hw.addEventListener('scroll', () => {
            if (scrollTimeout) clearTimeout(scrollTimeout);
            scrollTimeout = setTimeout(() => {
                loadVisibleImages();
            }, 100);
        });
    }

    // 页面加载时初始化滚动监听
    window.addEventListener('DOMContentLoaded', () => {
        setTimeout(initHistoryScrollListener, 500);
    });

    function displayHistoryOutput(file, type) {
        document.getElementById('res-img').style.display = 'none';
        document.getElementById('video-wrapper').style.display = 'none';

        const mode = type === 'video' ? 'video' : 'image';
        switchMode(mode);
        displayOutput(file);
    }
    
    window.addEventListener('DOMContentLoaded', () => {
        // Initialize Plyr Custom Video Component
        if(window.Plyr) {
            player = new Plyr('#res-video', {
                controls: [
                    'play-large', 'play', 'progress', 'current-time', 
                    'mute', 'volume', 'fullscreen'
                ],
                settings: [],
                loop: { active: true },
                autoplay: true
            });
        }
        
        // Fetch current directory context to show in UI
        fetch(`${BASE}/api/system/get-dir`)
            .then(res => res.json())
            .then(data => {
                if(data && data.directory) {
                    const outInput = document.getElementById('global-out-dir');
                    if (outInput) outInput.value = data.directory;
                }
            }).catch(e => console.error(e));

        setTimeout(() => fetchHistory(1), 500);
        
        let historyRefreshInterval = null;
        function startHistoryAutoRefresh() {
            if (historyRefreshInterval) return;
            historyRefreshInterval = setInterval(() => {
                if (document.getElementById('history-container').style.display === 'flex' && !_isGeneratingFlag) {
                    fetchHistory(1, true);
                }
            }, 5000);
        }
        startHistoryAutoRefresh();
        switchLibTab('history');
    });