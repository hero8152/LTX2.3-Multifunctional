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

    function _t(k) {
        return typeof window.t === 'function' ? window.t(k) : k;
    }
    
    let currentMode = 'image';
    let pollInterval = null;
    let availableLoras = [];
    let player = null;
    let audioPlayer = null;

    // 建议增加一个简单的调试日志，方便在控制台确认地址是否正确
    console.log("Connecting to Backend API at:", BASE);

    // LoRA 扫描功能
    async function scanLoras() {
        try {
            const url = `${BASE}/api/loras`;
            console.log("Scanning LoRA from:", url);
            const res = await fetch(url);
            const data = await res.json().catch(() => ({}));
            console.log("LoRA response:", res.status, data);
            if (!res.ok) {
                const msg = data.message || data.error || res.statusText;
                addLog(`❌ LoRA 扫描失败 (${res.status}): ${msg}`);
                availableLoras = [];
                updateLoraDropdown();
                updateBatchLoraDropdown();
                return;
            }
            availableLoras = data.loras || [];
            updateLoraDropdown();
            updateBatchLoraDropdown();
            if (data.loras_dir) {
                const hintEl = document.getElementById('lora-placement-hint');
                if (hintEl) {
                    const tpl = _t('loraPlacementHintWithDir');
                    hintEl.innerHTML = tpl.replace(
                        '{dir}',
                        escapeHtmlAttr(data.models_dir || data.loras_dir)
                    );
                }
            }
            if (availableLoras.length > 0) {
                addLog(`📂 已扫描到 ${availableLoras.length} 个 LoRA: ${availableLoras.map(l => l.name).join(', ')}`);
            }
        } catch (e) {
            console.log("LoRA scan error:", e);
            addLog(`❌ LoRA 扫描异常: ${e.message || e}`);
        }
    }

    window.addLoraSelection = function(containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const wrapper = document.createElement('div');
        wrapper.className = 'lora-entry';
        wrapper.style.display = 'flex';
        wrapper.style.flexDirection = 'column';
        wrapper.style.gap = '4px';
        wrapper.style.padding = '8px';
        wrapper.style.background = 'rgba(255,255,255,0.03)';
        wrapper.style.borderRadius = '6px';
        wrapper.style.border = '1px solid var(--border)';

        const row1 = document.createElement('div');
        row1.style.display = 'flex';
        row1.style.gap = '8px';
        row1.style.alignItems = 'center';

        const select = document.createElement('select');
        select.className = 'lora-select';
        select.style.flex = '1';
        select.innerHTML = '<option value="">' + _t('noLora') + '</option>';
        availableLoras.forEach(lora => {
            const opt = document.createElement('option');
            opt.value = lora.path;
            opt.textContent = lora.name;
            select.appendChild(opt);
        });

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.title = '移除';
        removeBtn.innerHTML = '×';
        removeBtn.style.background = 'none';
        removeBtn.style.border = 'none';
        removeBtn.style.color = 'var(--text-dim)';
        removeBtn.style.cursor = 'pointer';
        removeBtn.style.fontSize = '18px';
        removeBtn.style.padding = '0 6px';
        removeBtn.onclick = () => { wrapper.remove(); };

        row1.appendChild(select);
        row1.appendChild(removeBtn);

        const strengthContainer = document.createElement('div');
        strengthContainer.className = 'lora-strength-container';
        strengthContainer.style.display = 'none';
        strengthContainer.style.alignItems = 'center';
        strengthContainer.style.gap = '8px';
        strengthContainer.style.marginTop = '4px';

        const strLabel = document.createElement('label');
        strLabel.textContent = _t('loraStrength') || 'LoRA 强度';
        strLabel.style.margin = '0';
        strLabel.style.whiteSpace = 'nowrap';
        strLabel.style.fontSize = '11px';

        const strInput = document.createElement('input');
        strInput.type = 'range';
        strInput.className = 'lora-strength';
        strInput.min = '0.1';
        strInput.max = '2.0';
        strInput.step = '0.1';
        strInput.value = '1.0';
        strInput.style.flex = '1';
        strInput.style.margin = '0';

        const strVal = document.createElement('span');
        strVal.className = 'lora-strength-val';
        strVal.textContent = '1.0';
        strVal.style.fontSize = '11px';
        strVal.style.color = 'var(--accent)';
        strVal.style.width = '24px';
        strVal.style.textAlign = 'right';

        strInput.oninput = () => { strVal.textContent = strInput.value; };

        strengthContainer.appendChild(strLabel);
        strengthContainer.appendChild(strInput);
        strengthContainer.appendChild(strVal);

        wrapper.appendChild(row1);
        wrapper.appendChild(strengthContainer);

        select.onchange = () => {
            strengthContainer.style.display = select.value ? 'flex' : 'none';
        };

        container.appendChild(wrapper);
    };

    function updateLoraDropdown() {
        const selects = document.querySelectorAll('#loras-container .lora-select');
        selects.forEach(select => {
            const currentVal = select.value;
            select.innerHTML = '<option value="">' + _t('noLora') + '</option>';
            availableLoras.forEach(lora => {
                const opt = document.createElement('option');
                opt.value = lora.path;
                opt.textContent = lora.name;
                select.appendChild(opt);
            });
            select.value = currentVal;
        });
        if (document.getElementById('loras-container') && document.getElementById('loras-container').children.length === 0) {
            window.addLoraSelection('loras-container');
        }
    }

    window.updateLoraStrength = function() {};

    function updateBatchLoraDropdown() {
        const selects = document.querySelectorAll('#batch-loras-container .lora-select');
        selects.forEach(select => {
            const currentVal = select.value;
            select.innerHTML = '<option value="">' + _t('noLora') + '</option>';
            availableLoras.forEach(lora => {
                const opt = document.createElement('option');
                opt.value = lora.path;
                opt.textContent = lora.name;
                select.appendChild(opt);
            });
            select.value = currentVal;
        });
        if (document.getElementById('batch-loras-container') && document.getElementById('batch-loras-container').children.length === 0) {
            window.addLoraSelection('batch-loras-container');
        }
    }
    
    window.updateBatchLoraStrength = function() {};

    // 页面加载时更新批量模式的下拉框
    function initBatchDropdowns() {
        updateBatchLoraDropdown();
    }

    // 已移除：模型/LoRA 目录自定义与浏览（保持后端默认路径扫描）

    // 页面加载时扫描 LoRA（模型选择入口暂时隐藏，后端保留待后续调试）
    (function() {
        ['vid-quality', 'batch-quality'].forEach((id) => {
            const sel = document.getElementById(id);
            if (sel && sel.value === '544') sel.value = '540';
        });
        
        setTimeout(() => {
            scanLoras();
            initBatchDropdowns();
        }, 1500);
    })();

    // 分辨率自动计算逻辑
    function updateResPreview() {
        const q = document.getElementById('vid-quality').value; // "1080", "720", "540"
        const r = document.getElementById('vid-ratio').value;
        
        // 核心修复：后端解析器期待 "1080p", "720p", "540p" 这种标签格式
        let resLabel = q === "1080" ? "1080p" : q === "720" ? "720p" : "540p";
        
        /* 与后端一致：宽高均为 64 的倍数（LTX 内核要求） */
        let resDisplay;
        if (r === "16:9") {
            resDisplay = q === "1080" ? "1920x1088" : q === "720" ? "1280x704" : "1024x576";
        } else {
            resDisplay = q === "1080" ? "1088x1920" : q === "720" ? "704x1280" : "576x1024";
        }
        
        document.getElementById('res-preview').innerText = `${_t('resPreviewPrefix')}: ${resLabel} (${resDisplay})`;
        return resLabel;
    }

    // 图片分辨率预览
    function updateImgResPreview() {
        const w = document.getElementById('img-w').value;
        const h = document.getElementById('img-h').value;
        document.getElementById('img-res-preview').innerText = `${_t('resPreviewPrefix')}: ${w}x${h}`;
    }

    // 批量模式分辨率预览
    function updateBatchResPreview() {
        const q = document.getElementById('batch-quality').value;
        const r = document.getElementById('batch-ratio').value;
        let resLabel = q === "1080" ? "1080p" : q === "720" ? "720p" : "540p";
        let resDisplay;
        if (r === "16:9") {
            resDisplay = q === "1080" ? "1920x1088" : q === "720" ? "1280x704" : "1024x576";
        } else {
            resDisplay = q === "1080" ? "1088x1920" : q === "720" ? "704x1280" : "576x1024";
        }
        document.getElementById('batch-res-preview').innerText = `${_t('resPreviewPrefix')}: ${resLabel} (${resDisplay})`;
        return resLabel;
    }

    // 批量模式 LoRA 强度切换
    function updateBatchLoraStrength() {
        const select = document.getElementById('batch-lora');
        const container = document.getElementById('batch-lora-strength-container');
        if (select && container) {
            container.style.display = select.value ? 'flex' : 'none';
        }
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

    async function uploadBase64File(file, logLabel) {
        const b64Data = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = (e) => resolve(e.target.result);
            reader.onerror = () => reject(new Error("读取本地文件失败"));
            reader.readAsDataURL(file);
        });
        addLog(`正在上传${logLabel}: ${file.name}...`);
        const res = await fetch(`${BASE}/api/system/upload-image`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: b64Data, filename: file.name })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.path) {
            const errMsg = data.error || data.detail || "上传失败";
            throw new Error(typeof errMsg === 'string' ? errMsg : JSON.stringify(errMsg));
        }
        return data.path;
    }

    window.handleMotionVideoUpload = async function(file) {
        if (!file) return;
        try {
            const path = await uploadBase64File(file, '参考动作视频');
            document.getElementById('motion-video-path').value = path;
            document.getElementById('motion-video-placeholder').style.display = 'none';
            document.getElementById('motion-video-status').style.display = 'block';
            document.getElementById('motion-video-name').textContent = file.name;
            document.getElementById('clear-motion-video-overlay').style.display = 'flex';
            addLog(`✅ 参考动作视频上传成功: ${file.name}`);
        } catch (e) {
            addLog(`❌ 参考动作视频上传失败: ${e.message}`);
        }
    };

    window.clearMotionVideo = function() {
        document.getElementById('motion-video-input').value = "";
        document.getElementById('motion-video-path').value = "";
        document.getElementById('motion-video-placeholder').style.display = 'block';
        document.getElementById('motion-video-status').style.display = 'none';
        document.getElementById('motion-video-name').textContent = "";
        document.getElementById('clear-motion-video-overlay').style.display = 'none';
        addLog("🧹 已清除参考动作视频");
    };

    window.handleMotionImageUpload = async function(file) {
        if (!file) return;
        const preview = document.getElementById('motion-image-preview');
        const placeholder = document.getElementById('motion-image-placeholder');
        const clearOverlay = document.getElementById('clear-motion-image-overlay');
        const reader = new FileReader();
        reader.onload = (e) => {
            preview.src = e.target.result;
            preview.style.display = 'block';
            placeholder.style.display = 'none';
            clearOverlay.style.display = 'flex';
        };
        reader.readAsDataURL(file);
        try {
            const path = await uploadBase64File(file, '目标主体图');
            document.getElementById('motion-image-path').value = path;
            addLog(`✅ 目标主体图上传成功: ${file.name}`);
        } catch (e) {
            addLog(`❌ 目标主体图上传失败: ${e.message}`);
        }
    };

    window.clearMotionImage = function() {
        document.getElementById('motion-image-input').value = "";
        document.getElementById('motion-image-path').value = "";
        document.getElementById('motion-image-preview').style.display = 'none';
        document.getElementById('motion-image-preview').src = "";
        document.getElementById('motion-image-placeholder').style.display = 'block';
        document.getElementById('clear-motion-image-overlay').style.display = 'none';
        addLog("🧹 已清除目标主体图");
    };

    // 初始化拖拽上传逻辑
    function initDragAndDrop() {
        const audioDropZone = document.getElementById('audio-drop-zone');
        const startFrameDropZone = document.getElementById('start-frame-drop-zone');
        const endFrameDropZone = document.getElementById('end-frame-drop-zone');
        const batchImagesDropZone = document.getElementById('batch-images-drop-zone');
        const motionVideoDropZone = document.getElementById('motion-video-drop-zone');
        const motionImageDropZone = document.getElementById('motion-image-drop-zone');
        const ttsRefDropZone = document.getElementById('tts-ref-drop');
        
        const zones = [audioDropZone, startFrameDropZone, endFrameDropZone, batchImagesDropZone, motionVideoDropZone, motionImageDropZone, ttsRefDropZone].filter(z => z);

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

        // 批量图片拖拽上传
        if (batchImagesDropZone) {
            batchImagesDropZone.addEventListener('drop', (e) => {
                e.preventDefault();
                e.stopPropagation();
                batchImagesDropZone.classList.remove('dragover');
                const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
                if (files.length > 0) handleBatchImagesUpload(files);
            }, false);
        }

        if (motionVideoDropZone) {
            motionVideoDropZone.addEventListener('drop', (e) => {
                const file = e.dataTransfer.files[0];
                if (file && (file.type.startsWith('video/') || /\.(mp4|mov|webm|mkv|avi)$/i.test(file.name))) {
                    window.handleMotionVideoUpload(file);
                }
            }, false);
        }

        if (motionImageDropZone) {
            motionImageDropZone.addEventListener('drop', (e) => {
                const file = e.dataTransfer.files[0];
                if (file && file.type.startsWith('image/')) {
                    window.handleMotionImageUpload(file);
                }
            }, false);
        }

        if (ttsRefDropZone) {
            ttsRefDropZone.addEventListener('drop', (e) => {
                const file = e.dataTransfer.files[0];
                if (file && (file.type.startsWith('audio/') || file.name.endsWith('.wav') || file.name.endsWith('.mp3'))) {
                    handleTtsRefUpload(file);
                }
            }, false);
        }
    }

    // 批量图片上传处理
    let batchImages = [];
    /** 单次多关键帧：按 path 记引导强度；按帧索引记每张图占用秒数 */
    const batchKfStrengthByPath = {};
    const batchKfSegDurByIndex = {};

    function escapeHtmlAttr(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/</g, '&lt;');
    }

    function defaultKeyframeStrengthForIndex(i, n) {
        if (n <= 2) return '1';
        if (i === 0) return '0.62';
        if (i === n - 1) return '1';
        return '0.42';
    }

    function captureBatchKfTimelineFromDom() {
        batchImages.forEach((img, i) => {
            if (!img.path) return;
            const sEl = document.getElementById(`batch-kf-strength-${i}`);
            if (sEl) batchKfStrengthByPath[img.path] = sEl.value.trim();
        });
        const n = batchImages.length;
        for (let j = 0; j < n; j++) {
            const el = document.getElementById(`batch-kf-seg-dur-${j}`);
            if (el) batchKfSegDurByIndex[j] = el.value.trim();
        }
    }

    /** 读取每帧占用时长（秒），非法则回退为 minSeg */
    function readBatchKfFrameSeconds(n, minSeg) {
        const secs = [];
        for (let j = 0; j < n; j++) {
            let v = parseFloat(document.getElementById(`batch-kf-seg-dur-${j}`)?.value);
            if (!Number.isFinite(v) || v < minSeg) v = minSeg;
            secs.push(v);
        }
        return secs;
    }

    function updateBatchKfTimelineDerivedUI() {
        if (!batchWorkflowIsSingle() || batchImages.length < 2) return;
        const n = batchImages.length;
        const minSeg = 0.1;
        const frameSecs = readBatchKfFrameSeconds(n, minSeg);
        let t = 0;
        for (let i = 0; i < n; i++) {
            const label = document.getElementById(`batch-kf-anchor-label-${i}`);
            if (!label) continue;
            if (i === 0) {
                label.textContent = `0.0 s · ${_t('batchAnchorStart')}`;
            } else {
                t += frameSecs[i - 1];
                label.textContent =
                    i === n - 1
                        ? `${t.toFixed(1)} s · ${_t('batchAnchorLast')}`
                        : `${t.toFixed(1)} s`;
            }
        }
        const totalEl = document.getElementById('batch-kf-total-seconds');
        if (totalEl) {
            const sum = frameSecs.reduce((a, b) => a + b, 0);
            totalEl.textContent = sum.toFixed(1);
        }
    }
    async function handleBatchImagesUpload(files, append = true) {
        if (!files || files.length === 0) return;
        addLog(`正在上传 ${files.length} 张图片...`);

        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            const reader = new FileReader();

            const imgData = await new Promise((resolve) => {
                reader.onload = async (e) => {
                    const b64Data = e.target.result;
                    try {
                        const res = await fetch(`${BASE}/api/system/upload-image`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ image: b64Data, filename: file.name })
                        });
                        const data = await res.json();
                        if (res.ok && data.path) {
                            resolve({ name: file.name, path: data.path, preview: e.target.result });
                        } else {
                            resolve(null);
                        }
                    } catch (e) {
                        resolve(null);
                    }
                };
                reader.readAsDataURL(file);
            });

            if (imgData) {
                batchImages.push(imgData);
                addLog(`✅ 图片 ${i + 1}/${files.length} 上传成功: ${file.name}`);
            }
        }

        renderBatchImages();
        updateBatchSegments();
    }

    async function handleBatchBackgroundAudioUpload(file) {
        if (!file) return;
        const ph = document.getElementById('batch-audio-placeholder');
        const st = document.getElementById('batch-audio-status');
        const overlay = document.getElementById('clear-batch-audio-overlay');
        const reader = new FileReader();
        reader.onload = async (e) => {
            const b64Data = e.target.result;
            addLog(`正在上传成片配乐: ${file.name}...`);
            try {
                const res = await fetch(`${BASE}/api/system/upload-image`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ image: b64Data, filename: file.name })
                });
                const data = await res.json();
                if (res.ok && data.path) {
                    const hid = document.getElementById('batch-background-audio-path');
                    if (hid) hid.value = data.path;
                    if (ph) ph.style.display = 'none';
                    if (st) {
                        st.style.display = 'block';
                        st.textContent = '✓ ' + file.name;
                    }
                    if (overlay) overlay.style.display = 'flex';
                    addLog('✅ 成片配乐已上传（将覆盖各片段自带音轨）');
                } else {
                    addLog(`❌ 配乐上传失败: ${data.error || '未知错误'}`);
                }
            } catch (err) {
                addLog(`❌ 配乐上传失败: ${err.message}`);
            }
        };
        reader.onerror = () => addLog('❌ 读取音频文件失败');
        reader.readAsDataURL(file);
    }

    function clearBatchBackgroundAudio() {
        const hid = document.getElementById('batch-background-audio-path');
        const inp = document.getElementById('batch-audio-input');
        if (hid) hid.value = '';
        if (inp) inp.value = '';
        const ph = document.getElementById('batch-audio-placeholder');
        const st = document.getElementById('batch-audio-status');
        const overlay = document.getElementById('clear-batch-audio-overlay');
        if (ph) ph.style.display = 'block';
        if (st) {
            st.style.display = 'none';
            st.textContent = '';
        }
        if (overlay) overlay.style.display = 'none';
        addLog('🧹 已清除成片配乐');
    }

    function syncBatchDropZoneChrome() {
        const dropZone = document.getElementById('batch-images-drop-zone');
        const placeholder = document.getElementById('batch-images-placeholder');
        const stripWrap = document.getElementById('batch-thumb-strip-wrap');
        if (batchImages.length === 0) {
            if (dropZone) {
                dropZone.classList.remove('has-images');
                const mini = dropZone.querySelector('.upload-placeholder-mini');
                if (mini) mini.remove();
            }
            if (placeholder) placeholder.style.display = 'block';
            if (stripWrap) stripWrap.style.display = 'none';
            return;
        }
        if (placeholder) placeholder.style.display = 'none';
        if (dropZone) dropZone.classList.add('has-images');
        if (stripWrap) stripWrap.style.display = 'block';
        if (dropZone && !dropZone.querySelector('.upload-placeholder-mini')) {
            const mini = document.createElement('div');
            mini.className = 'upload-placeholder-mini';
            mini.innerHTML = '<span>' + _t('batchAddMore') + '</span>';
            dropZone.appendChild(mini);
        }
    }

    let batchDragPlaceholderEl = null;
    let batchPointerState = null;
    let batchPendingPhX = null;
    let batchPhMoveRaf = null;

    function batchRemoveFloatingGhost() {
        document.querySelectorAll('.batch-thumb-floating-ghost').forEach((n) => n.remove());
    }

    function batchCancelPhMoveRaf() {
        if (batchPhMoveRaf != null) {
            cancelAnimationFrame(batchPhMoveRaf);
            batchPhMoveRaf = null;
        }
        batchPendingPhX = null;
    }

    function batchEnsurePlaceholder() {
        if (batchDragPlaceholderEl && batchDragPlaceholderEl.isConnected) return batchDragPlaceholderEl;
        const el = document.createElement('div');
        el.className = 'batch-thumb-drop-slot';
        el.setAttribute('aria-hidden', 'true');
        batchDragPlaceholderEl = el;
        return el;
    }

    function batchRemovePlaceholder() {
        if (batchDragPlaceholderEl && batchDragPlaceholderEl.parentNode) {
            batchDragPlaceholderEl.parentNode.removeChild(batchDragPlaceholderEl);
        }
    }

    function batchComputeInsertIndex(container, placeholder) {
        let t = 0;
        for (const child of container.children) {
            if (child === placeholder) return t;
            if (child.classList && child.classList.contains('batch-image-wrapper')) {
                if (!child.classList.contains('batch-thumb--source')) t++;
            }
        }
        return t;
    }

    function batchMovePlaceholderFromPoint(container, clientX) {
        const ph = batchEnsurePlaceholder();
        const wrappers = [...container.querySelectorAll('.batch-image-wrapper')];
        let insertBefore = null;
        for (const w of wrappers) {
            if (w.classList.contains('batch-thumb--source')) continue;
            const r = w.getBoundingClientRect();
            if (clientX < r.left + r.width / 2) {
                insertBefore = w;
                break;
            }
        }
        if (insertBefore === null) {
            const vis = wrappers.filter((w) => !w.classList.contains('batch-thumb--source'));
            const last = vis[vis.length - 1];
            if (last) {
                if (last.nextSibling) {
                    container.insertBefore(ph, last.nextSibling);
                } else {
                    container.appendChild(ph);
                }
            } else {
                container.appendChild(ph);
            }
        } else {
            container.insertBefore(ph, insertBefore);
        }
    }

    function batchFlushPlaceholderMove() {
        batchPhMoveRaf = null;
        if (!batchPointerState || batchPendingPhX == null) return;
        batchMovePlaceholderFromPoint(batchPointerState.container, batchPendingPhX);
    }

    function handleBatchPointerMove(e) {
        if (!batchPointerState) return;
        e.preventDefault();
        const st = batchPointerState;
        st.ghostTX = e.clientX - st.offsetX;
        st.ghostTY = e.clientY - st.offsetY;
        batchPendingPhX = e.clientX;
        if (batchPhMoveRaf == null) {
            batchPhMoveRaf = requestAnimationFrame(batchFlushPlaceholderMove);
        }
    }

    function batchGhostFrame() {
        const st = batchPointerState;
        if (!st || !st.ghostEl || !st.ghostEl.isConnected) {
            return;
        }
        const t = 0.42;
        st.ghostCX += (st.ghostTX - st.ghostCX) * t;
        st.ghostCY += (st.ghostTY - st.ghostCY) * t;
        st.ghostEl.style.transform =
            `translate3d(${st.ghostCX}px,${st.ghostCY}px,0) scale(1.06) rotate(-1deg)`;
        st.ghostRaf = requestAnimationFrame(batchGhostFrame);
    }

    function batchStartGhostLoop() {
        const st = batchPointerState;
        if (!st || !st.ghostEl) return;
        if (st.ghostRaf != null) cancelAnimationFrame(st.ghostRaf);
        st.ghostRaf = requestAnimationFrame(batchGhostFrame);
    }

    function batchEndPointerDrag(e) {
        if (!batchPointerState) return;
        if (e.pointerId !== batchPointerState.pointerId) return;
        const st = batchPointerState;

        batchCancelPhMoveRaf();
        if (st.ghostRaf != null) {
            cancelAnimationFrame(st.ghostRaf);
            st.ghostRaf = null;
        }
        if (st.ghostEl && st.ghostEl.parentNode) {
            st.ghostEl.remove();
        }
        batchPointerState = null;

        document.removeEventListener('pointermove', handleBatchPointerMove);
        document.removeEventListener('pointerup', batchEndPointerDrag);
        document.removeEventListener('pointercancel', batchEndPointerDrag);

        try {
            if (st.wrapperEl) st.wrapperEl.releasePointerCapture(st.pointerId);
        } catch (_) {}

        const { fromIndex, container, wrapperEl } = st;
        container.classList.remove('is-batch-settling');
        if (!batchDragPlaceholderEl || !batchDragPlaceholderEl.parentNode) {
            if (wrapperEl) wrapperEl.classList.remove('batch-thumb--source');
            renderBatchImages();
            updateBatchSegments();
            return;
        }
        const to = batchComputeInsertIndex(container, batchDragPlaceholderEl);
        batchRemovePlaceholder();
        if (wrapperEl) wrapperEl.classList.remove('batch-thumb--source');

        if (fromIndex !== to && fromIndex >= 0 && to >= 0) {
            const [item] = batchImages.splice(fromIndex, 1);
            batchImages.splice(to, 0, item);
            updateBatchSegments();
        }
        renderBatchImages();
    }

    function handleBatchPointerDown(e) {
        if (batchPointerState) return;
        if (e.button !== 0) return;
        if (e.target.closest && e.target.closest('.batch-thumb-remove')) return;

        const wrapper = e.currentTarget;
        const container = document.getElementById('batch-images-container');
        if (!container) return;

        e.preventDefault();
        e.stopPropagation();

        const fromIndex = parseInt(wrapper.dataset.index, 10);
        if (Number.isNaN(fromIndex)) return;

        const rect = wrapper.getBoundingClientRect();
        const offsetX = e.clientX - rect.left;
        const offsetY = e.clientY - rect.top;
        const startLeft = rect.left;
        const startTop = rect.top;

        const ghost = document.createElement('div');
        ghost.className = 'batch-thumb-floating-ghost';
        const gImg = document.createElement('img');
        const srcImg = wrapper.querySelector('img');
        gImg.src = srcImg ? srcImg.src : '';
        gImg.alt = '';
        ghost.appendChild(gImg);
        document.body.appendChild(ghost);

        batchPointerState = {
            fromIndex,
            pointerId: e.pointerId,
            wrapperEl: wrapper,
            container,
            ghostEl: ghost,
            offsetX,
            offsetY,
            ghostTX: e.clientX - offsetX,
            ghostTY: e.clientY - offsetY,
            ghostCX: startLeft,
            ghostCY: startTop,
            ghostRaf: null
        };

        ghost.style.transform =
            `translate3d(${startLeft}px,${startTop}px,0) scale(1.06) rotate(-1deg)`;

        container.classList.add('is-batch-settling');
        wrapper.classList.add('batch-thumb--source');
        const ph = batchEnsurePlaceholder();
        container.insertBefore(ph, wrapper.nextSibling);
        /* 不在 pointerdown 立刻重算槽位；双 rAF 后再恢复邻居 transition，保证先完成本帧布局再动画 */
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                container.classList.remove('is-batch-settling');
            });
        });

        batchStartGhostLoop();

        document.addEventListener('pointermove', handleBatchPointerMove, { passive: false });
        document.addEventListener('pointerup', batchEndPointerDrag);
        document.addEventListener('pointercancel', batchEndPointerDrag);

        try {
            wrapper.setPointerCapture(e.pointerId);
        } catch (_) {}
    }

    function removeBatchImage(index) {
        if (index < 0 || index >= batchImages.length) return;
        batchImages.splice(index, 1);
        renderBatchImages();
        updateBatchSegments();
    }

    // 横向缩略图：Pointer 拖动排序（避免 HTML5 DnD 在 WebView/部分浏览器失效）
    function renderBatchImages() {
        const container = document.getElementById('batch-images-container');
        if (!container) return;

        syncBatchDropZoneChrome();
        batchRemovePlaceholder();
        batchCancelPhMoveRaf();
        batchRemoveFloatingGhost();
        batchPointerState = null;
        container.classList.remove('is-batch-settling');
        container.innerHTML = '';

        batchImages.forEach((img, index) => {
            const wrapper = document.createElement('div');
            wrapper.className = 'batch-image-wrapper';
            wrapper.dataset.index = String(index);
            wrapper.title = _t('batchThumbDrag');

            const imgWrap = document.createElement('div');
            imgWrap.className = 'batch-thumb-img-wrap';
            const im = document.createElement('img');
            im.className = 'batch-thumb-img';
            im.src = img.preview;
            im.alt = img.name || '';
            im.draggable = false;
            imgWrap.appendChild(im);

            const del = document.createElement('button');
            del.type = 'button';
            del.className = 'batch-thumb-remove';
            del.title = _t('batchThumbRemove');
            del.setAttribute('aria-label', _t('batchThumbRemove'));
            del.textContent = '×';
            del.addEventListener('pointerdown', (ev) => ev.stopPropagation());
            del.addEventListener('click', (ev) => {
                ev.stopPropagation();
                removeBatchImage(index);
            });

            wrapper.appendChild(imgWrap);
            wrapper.appendChild(del);

            wrapper.addEventListener('pointerdown', handleBatchPointerDown);

            container.appendChild(wrapper);
        });
    }

    function batchWorkflowIsSingle() {
        const r = document.querySelector('input[name="batch-workflow"]:checked');
        return !!(r && r.value === 'single');
    }

    function onBatchWorkflowChange() {
        updateBatchSegments();
    }

    // 更新片段设置 UI（分段模式）或单次多关键帧设置
    function updateBatchSegments() {
        const container = document.getElementById('batch-segments-container');
        if (!container) return;
        
        if (batchImages.length < 2) {
            container.innerHTML =
                '<div style="color: var(--text-dim); font-size: 11px;">' +
                escapeHtmlAttr(_t('batchNeedTwo')) +
                '</div>';
            return;
        }

        if (batchWorkflowIsSingle()) {
            if (batchImages.length >= 2) captureBatchKfTimelineFromDom();
            const n = batchImages.length;
            const defaultTotal = 8;
            const defaultSeg =
                n > 0 ? (defaultTotal / n).toFixed(1) : '4';
            let blocks = '';
            batchImages.forEach((img, i) => {
                const path = img.path || '';
                const stDef = defaultKeyframeStrengthForIndex(i, n);
                const stStored = batchKfStrengthByPath[path];
                const stVal = stStored !== undefined && stStored !== ''
                    ? escapeHtmlAttr(stStored)
                    : stDef;
                const prev = escapeHtmlAttr(img.preview || '');
                const sdStored = batchKfSegDurByIndex[i];
                const segVal =
                    sdStored !== undefined && sdStored !== ''
                        ? escapeHtmlAttr(sdStored)
                        : defaultSeg;
                blocks += `
                <div class="batch-kf-kcard">
                    <div class="batch-kf-kcard-head">
                        <img class="batch-kf-kthumb" src="${prev}" alt="">
                        <div class="batch-kf-kcard-titles">
                            <span class="batch-kf-ktitle">${escapeHtmlAttr(_t('batchKfTitle'))} ${i + 1} / ${n}</span>
                            <span class="batch-kf-anchor" id="batch-kf-anchor-label-${i}">—</span>
                        </div>
                    </div>
                    <div class="batch-kf-kcard-ctrl">
                        <label class="batch-kf-klabel">${escapeHtmlAttr(_t('batchStrength'))}
                            <input type="number" id="batch-kf-strength-${i}" value="${stVal}" min="0.1" max="1" step="0.01"
                                title="${escapeHtmlAttr(_t('batchStrengthTitle'))}">
                        </label>
                        <label class="batch-kf-klabel">${escapeHtmlAttr(_t('batchFrameDuration'))}
                            <input type="number" class="batch-kf-seg-input" id="batch-kf-seg-dur-${i}"
                                value="${segVal}" min="0.1" max="120" step="0.1"
                                title="${escapeHtmlAttr(_t('batchFrameDurationTitle'))}"
                                oninput="updateBatchKfTimelineDerivedUI()">
                            <span class="batch-kf-gap-unit">${escapeHtmlAttr(_t('batchSec'))}</span>
                        </label>
                    </div>
                </div>`;
            });
            container.innerHTML = `
                <div class="batch-kf-panel" id="batch-kf-timeline-root">
                    <div class="batch-kf-panel-hd">
                        <div class="batch-kf-panel-title">${escapeHtmlAttr(_t('batchKfPanelTitle'))}</div>
                        <div class="batch-kf-total-pill" title="${escapeHtmlAttr(_t('batchTotalPillTitle'))}">
                            ${escapeHtmlAttr(_t('batchTotalDur'))} <strong id="batch-kf-total-seconds">—</strong> <span class="batch-kf-total-unit">${escapeHtmlAttr(_t('batchTotalSec'))}</span>
                        </div>
                    </div>
                    <p class="batch-kf-panel-hint">${escapeHtmlAttr(_t('batchPanelHint'))}</p>
                    <div class="batch-kf-timeline-col">
                        ${blocks}
                    </div>
                </div>`;
            updateBatchKfTimelineDerivedUI();
            return;
        }
        
        let html =
            '<div style="font-size: 12px; font-weight: bold; margin-bottom: 10px;">' +
            escapeHtmlAttr(_t('batchSegTitle')) +
            '</div>';
        
        for (let i = 0; i < batchImages.length - 1; i++) {
            const segPh = escapeHtmlAttr(_t('batchSegPromptPh'));
            html += `
                <div style="background: var(--item); border-radius: 8px; padding: 10px; margin-bottom: 10px; border: 1px solid var(--border);">
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <img src="${batchImages[i].preview}" style="width: 40px; height: 40px; border-radius: 4px; object-fit: cover;">
                            <span style="color: var(--accent);">→</span>
                            <img src="${batchImages[i + 1].preview}" style="width: 40px; height: 40px; border-radius: 4px; object-fit: cover;">
                            <span style="font-size: 11px; color: var(--text-dim);">${escapeHtmlAttr(_t('batchSegClip'))} ${i + 1}</span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 6px;">
                            <label style="font-size: 10px; color: var(--text-dim);">${escapeHtmlAttr(_t('batchSegDuration'))}</label>
                            <input type="number" id="batch-segment-duration-${i}" value="5" min="1" max="30" step="1" style="width: 50px; padding: 4px; font-size: 11px;">
                            <span style="font-size: 10px; color: var(--text-dim);">${escapeHtmlAttr(_t('batchSegSec'))}</span>
                        </div>
                    </div>
                    <div>
                        <label style="font-size: 10px;">${escapeHtmlAttr(_t('batchSegPrompt'))}</label>
                        <textarea id="batch-segment-prompt-${i}" placeholder="${segPh}" style="width: 100%; height: 60px; padding: 6px; font-size: 11px; box-sizing: border-box; resize: vertical;"></textarea>
                    </div>
                </div>
            `;
        }
        
        container.innerHTML = html;
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
                s.innerText = `${gpuName}: ${_t('sysBusy')}`;
                if(indicator) indicator.className = 'indicator-busy';
            } else {
                s.innerText = isReady ? `${gpuName}: ${_t('sysOnline')}` : `${gpuName}: ${_t('sysStarting')}`;
                if(indicator) indicator.className = isReady ? 'indicator-ready' : 'indicator-offline';
            }
            s.style.color = "var(--text-dim)";

            const vUsedMB = g.gpu_info?.vramUsed || 0;
            const vTotalMB = activeGpu.vram_mb || g.gpu_info?.vram || 32768; 
            const vUsedGB = vUsedMB / 1024;
            const vTotalGB = vTotalMB / 1024;
            
            document.getElementById('vram-fill').style.width = (vUsedMB / vTotalMB * 100) + "%";
            document.getElementById('vram-text').innerText = `${vUsedGB.toFixed(1)} / ${vTotalGB.toFixed(0)} GB`;
        } catch(e) { document.getElementById('sys-status').innerText = _t('sysOffline'); }
    }
    setInterval(checkStatus, 1000); // 提升到 1 秒一次实时监控
    checkStatus();
    initDragAndDrop();
    listGpus(); // 初始化 GPU 列表
    // 已移除：输出目录自定义（保持后端默认路径）

    updateResPreview();
    updateBatchResPreview();
    updateImgResPreview();
    refreshPromptPlaceholder();

    window.onUiLanguageChanged = function () {
        updateResPreview();
        updateBatchResPreview();
        updateImgResPreview();
        refreshPromptPlaceholder();
        if (typeof currentMode !== 'undefined' && currentMode === 'batch') {
            updateBatchSegments();
        }
        if (typeof currentMode !== 'undefined' && currentMode === 'tts') {
            checkTtsStatus();
        }
        updateLoraDropdown();
        updateBatchLoraDropdown();
    };

    async function setOutputDir() {
        const dir = document.getElementById('global-out-dir').value.trim();
        localStorage.setItem('output_dir', dir);
        try {
            const res = await fetch(`${BASE}/api/system/set-dir`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ directory: dir })
            });
            if (res.ok) {
                addLog(`✅ 存储路径更新成功! 当前路径: ${dir || _t('defaultPath')}`);
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

    async function saveLoraDir() {
        const input = document.getElementById('lora-dir-input');
        const status = document.getElementById('lora-dir-status');
        if (!input || !status) return;
        
        const loraDir = input.value.trim();
        try {
            const res = await fetch(`${BASE}/api/lora-dir`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ loraDir: loraDir })
            });
            const data = await res.json();
            if (data && data.status === 'ok') {
                status.textContent = '✓ 已保存';
                status.style.color = '#4caf50';
                setTimeout(() => { status.textContent = ''; }, 3000);
            } else {
                status.textContent = '✗ 保存失败: ' + (data.message || JSON.stringify(data));
                status.style.color = '#f44336';
            }
        } catch (e) {
            status.textContent = '✗ 保存失败: ' + e.message;
            status.style.color = '#f44336';
        }
    }

    async function loadLoraDir() {
        try {
            const res = await fetch(`${BASE}/api/lora-dir`);
            const data = await res.json();
            if (data && document.getElementById('lora-dir-input')) {
                document.getElementById('lora-dir-input').value = data.loraDir || '';
            }
        } catch (e) {}
    }

    function switchMode(m) {
        currentMode = m;
        document.getElementById('tab-image').classList.toggle('active', m === 'image');
        document.getElementById('tab-video').classList.toggle('active', m === 'video');
        document.getElementById('tab-batch').classList.toggle('active', m === 'batch');
        const tabMotion = document.getElementById('tab-motion');
        if (tabMotion) tabMotion.classList.toggle('active', m === 'motion');
        const tabTts = document.getElementById('tab-tts');
        if (tabTts) tabTts.classList.toggle('active', m === 'tts');

        document.getElementById('image-opts').style.display = m === 'image' ? 'block' : 'none';
        document.getElementById('video-opts').style.display = m === 'video' ? 'block' : 'none';
        document.getElementById('batch-opts').style.display = m === 'batch' ? 'block' : 'none';
        const motionOpts = document.getElementById('motion-opts');
        if (motionOpts) motionOpts.style.display = m === 'motion' ? 'block' : 'none';
        const ttsOpts = document.getElementById('tts-opts');
        if (ttsOpts) ttsOpts.style.display = m === 'tts' ? 'block' : 'none';

        // 主按钮：TTS 模式下隐藏（TTS 有自己的生成按钮）
        const mainBtn = document.getElementById('mainBtn');
        if (mainBtn) mainBtn.closest('div').style.display = m === 'tts' ? 'none' : '';

        // 视觉提示词：TTS 模式下隐藏（因为 TTS 有自己的输入框）
        const pc = document.getElementById('prompt-container');
        if (pc) pc.style.display = m === 'tts' ? 'none' : '';

        // 移除 TTS 模式下的上方分割线
        const mainTabsSection = document.getElementById('main-tabs-section');
        if (mainTabsSection) {
            mainTabsSection.style.borderBottom = m === 'tts' ? 'none' : '';
            mainTabsSection.style.paddingBottom = m === 'tts' ? '0' : '';
        }

        if (m === 'batch') updateBatchSegments();
        if (m === 'tts') checkTtsStatus();
        refreshPromptPlaceholder();
    }

    function refreshPromptPlaceholder() {
        const pe = document.getElementById('prompt');
        if (!pe) return;
        pe.placeholder =
            currentMode === 'tts' ? '切换到 TTS 模式时此框不参与生成' :
            _t('promptPlaceholder');
    }

    // ─── TTS 语音合成 ──────────────────────────────────────────────────────────
    let _ttsRefB64 = null; // 存放参考音频的 base64 内容

    window.onTtsModeChange = function() {
        const mode = document.getElementById('tts-mode').value;
        const refSec = document.getElementById('tts-ref-section');
        const ultSec = document.getElementById('tts-ultimate-section');
        if (refSec) refSec.style.display = (mode === 'clone' || mode === 'ultimate_clone') ? 'block' : 'none';
        if (ultSec) ultSec.style.display = mode === 'ultimate_clone' ? 'block' : 'none';
    };

    window.handleTtsRefUpload = async function(file) {
        if (!file) return;
        const placeholder = document.getElementById('tts-ref-placeholder');
        const statusEl = document.getElementById('tts-ref-status');
        const clearBtn = document.getElementById('tts-ref-clear');
        addLog(`正在读取参考音频: ${file.name}...`);
        const reader = new FileReader();
        reader.onload = async (e) => {
            const b64 = e.target.result;
            _ttsRefB64 = b64.includes(',') ? b64.split(',')[1] : b64;
            if (placeholder) placeholder.style.display = 'none';
            if (statusEl) { statusEl.style.display = 'block'; statusEl.textContent = '✅ ' + file.name; }
            if (clearBtn) clearBtn.style.display = 'flex';
            addLog(`✅ 参考音频已加载: ${file.name}`);
        };
        reader.readAsDataURL(file);
    };

    window.clearTtsRef = function() {
        _ttsRefB64 = null;
        const fi = document.getElementById('tts-ref-input');
        if (fi) fi.value = '';
        const placeholder = document.getElementById('tts-ref-placeholder');
        const statusEl = document.getElementById('tts-ref-status');
        const clearBtn = document.getElementById('tts-ref-clear');
        if (placeholder) placeholder.style.display = 'block';
        if (statusEl) { statusEl.style.display = 'none'; statusEl.textContent = ''; }
        if (clearBtn) clearBtn.style.display = 'none';
        addLog('🧹 已清除参考音频');
    };

    async function checkTtsStatus() {
        const bar = document.getElementById('tts-status-bar');
        if (!bar) return;
        try {
            const res = await fetch(`${BASE}/api/tts/status`);
            const data = await res.json();
            if (data.available) {
                bar.style.color = 'var(--accent)';
                bar.style.borderColor = 'var(--accent)';
                bar.textContent = _t('ttsStatusReady') + data.model_dir;
            } else if (!data.voxcpm_installed) {
                bar.style.color = '#f87171';
                bar.textContent = _t('ttsStatusNoPkq');
            } else if (!data.model_dir_exists) {
                bar.style.color = '#f87171';
                bar.textContent = _t('ttsStatusNoDir') + data.model_dir;
            } else {
                bar.style.color = 'var(--text-dim)';
                bar.textContent = _t('ttsStatusNotAvail');
            }
        } catch (e) {
            bar.style.color = '#f87171';
            bar.textContent = _t('ttsStatusConnErr') + e.message;
        }
    }

    window.runTts = async function() {
        const text = (document.getElementById('tts-text')?.value || '').trim();
        if (!text) { addLog(_t('ttsErrNoText')); return; }

        const mode = document.getElementById('tts-mode')?.value || 'text_only';
        const cfg = parseFloat(document.getElementById('tts-cfg')?.value || 2.0);
        const steps = parseInt(document.getElementById('tts-steps')?.value || 10);
        const promptText = document.getElementById('tts-prompt-text')?.value || '';

        if ((mode === 'clone' || mode === 'ultimate_clone') && !_ttsRefB64) {
            addLog(_t('ttsErrNoRef'));
            return;
        }

        const btn = document.getElementById('tts-gen-btn');
        if (btn) { btn.disabled = true; btn.textContent = _t('ttsGenBusy'); }
        const resultSec = document.getElementById('tts-result-section');
        if (resultSec) resultSec.style.display = 'none';

        addLog(`🎙️ TTS: Mode=${mode}, Length=${text.length}`);

        try {
            const payload = {
                text,
                mode,
                cfg_value: cfg,
                inference_timesteps: steps,
                reference_wav: _ttsRefB64 || null,
                prompt_wav: (mode === 'ultimate_clone' && _ttsRefB64) ? _ttsRefB64 : null,
                prompt_text: promptText || null,
            };

            const res = await fetch(`${BASE}/api/tts/generate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();

            if (!res.ok || data.status !== 'complete') {
                throw new Error(data.error || 'Generation failed');
            }

            const audioUrl = `${BASE}${data.audio_url}`;
            const player = document.getElementById('tts-audio-player');
            const dlLink = document.getElementById('tts-download-link');

            // 播放音频
            if (player) { player.src = audioUrl; player.load(); }
            // 直接下载音频，不跳转页面
            if (dlLink) {
                try {
                    const resp = await fetch(audioUrl);
                    const blob = await resp.blob();
                    const blobUrl = URL.createObjectURL(blob);
                    dlLink.href = blobUrl;
                    dlLink.download = data.audio_path || 'tts_output.wav';
                    // 不再自动触发点击下载
                    // dlLink.click();
                } catch (e) {
                    // 若下载失败，回退到直接链接方式
                    dlLink.href = audioUrl;
                    dlLink.download = data.audio_path || 'tts_output.wav';
                }
            }
            if (resultSec) resultSec.style.display = 'block';

            addLog(`✅ TTS: ${data.audio_path} (${data.sample_rate} Hz)`);

            // 刷新历史记录
            setTimeout(() => { isLoadingHistory = false; if (typeof fetchHistory === 'function') fetchHistory(1); }, 500);

        } catch (e) {
            addLog(`❌ TTS Error: ${e.message}`);
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = _t('ttsGenBtn'); }
        }
    };
    // ──────────────────────────────────────────────────────────────────────────

    function showGeneratingView() {
        if (!_isGeneratingFlag) return;
        const resImg = document.getElementById('res-img');
        const videoWrapper = document.getElementById('video-wrapper');
        const audioWrapper = document.getElementById('audio-wrapper');
        if (resImg) resImg.style.display = "none";
        if (videoWrapper) videoWrapper.style.display = "none";
        if (audioWrapper) audioWrapper.style.display = "none";
        if (player) {
            try { player.stop(); } catch(_) {}
        } else {
            const vid = document.getElementById('res-video');
            if (vid) { vid.pause(); vid.removeAttribute('src'); vid.load(); }
        }
        const audio = document.getElementById('res-audio');
        if (audioPlayer) { try { audioPlayer.stop(); } catch(_) {} }
        if (audio) { audio.pause(); audio.removeAttribute('src'); audio.load(); }
        const loadingTxt = document.getElementById('loading-txt');
        if (loadingTxt) loadingTxt.style.display = "flex";
    }

    async function run() {
        // 防止重复点击（_isGeneratingFlag 比 btn.disabled 更可靠）
        if (_isGeneratingFlag) {
            addLog(_t('warnGenerating'));
            return;
        }

        const btn = document.getElementById('mainBtn');
        const promptEl = document.getElementById('prompt');
        const prompt = promptEl ? promptEl.value.trim() : '';

        function batchHasUsablePrompt() {
            if (prompt) return true;
            if (typeof batchWorkflowIsSingle === 'function' && batchWorkflowIsSingle()) {
                return false;
            }
            if (batchImages.length < 2) return false;
            for (let i = 0; i < batchImages.length - 1; i++) {
                if (document.getElementById(`batch-segment-prompt-${i}`)?.value?.trim()) return true;
            }
            return false;
        }

        if (currentMode === 'batch') {
            if (!batchHasUsablePrompt()) {
                addLog(_t('warnBatchPrompt'));
                return;
            }
        } else if (currentMode !== 'motion' && !prompt) {
            addLog(_t('warnNeedPrompt'));
            return;
        }

        if (!btn) {
            console.error('mainBtn not found');
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
                    <div id="loader-step-text" style="font-size:13px;font-weight:700;color:var(--text-sub);">${escapeHtmlAttr(_t('loaderGpuAlloc'))}</div>
                `;
            }
            if (resImg) resImg.style.display = "none";
            // 必须隐藏整个 video-wrapper（Plyr 外层容器），否则第二次生成时视频会与 spinner 叠加
            const videoWrapper = document.getElementById('video-wrapper');
            if (videoWrapper) videoWrapper.style.display = "none";
            const audioWrapper = document.getElementById('audio-wrapper');
            if (audioWrapper) audioWrapper.style.display = "none";
            if (player) { try { player.stop(); } catch(_) {} }
            else if (resVideo) { resVideo.pause?.(); resVideo.removeAttribute?.('src'); }
            if (audioPlayer) { try { audioPlayer.stop(); } catch(_) {} }

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
                if (dur > 20) addLog(_t('warnVideoLong').replace('{n}', String(dur)));

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
                const loraPaths = [];
                const loraStrengths = [];
                document.querySelectorAll('#loras-container .lora-entry').forEach(entry => {
                    const sel = entry.querySelector('.lora-select');
                    const strIn = entry.querySelector('.lora-strength');
                    if (sel && sel.value) {
                        loraPaths.push(sel.value);
                        loraStrengths.push(strIn ? parseFloat(strIn.value) : 1.0);
                    }
                });

                const effectiveLoraPaths = loraPaths;
                const effectiveLoraStrengths = loraStrengths;
                const loraPath = effectiveLoraPaths[0] || null;
                const loraStrength = effectiveLoraStrengths[0] || 1.0;

                payload = {
                    prompt, resolution: res, model: "ltx-2",
                    cameraMotion: document.getElementById('vid-motion').value,
                    negativePrompt: "low quality, blurry, noisy, static noise, distorted",
                    duration: String(dur), fps, audio,
                    imagePath: finalImagePath,
                    audioPath: audioPath || null,
                    startFramePath: finalStartFramePath,
                    endFramePath: finalEndFramePath,
                    aspectRatio: document.getElementById('vid-ratio').value,
                    loraPath: loraPath,
                    loraStrength: loraStrength,
                    loraPaths: effectiveLoraPaths.length > 0 ? effectiveLoraPaths : null,
                    loraStrengths: effectiveLoraStrengths.length > 0 ? effectiveLoraStrengths : null,
                };
                
                let loraLog = _t('loraNoneLabel');
                if (effectiveLoraPaths.length > 0) {
                    loraLog = effectiveLoraPaths.map(p => p.split(/[/\\]/).pop()).join(', ');
                }
                addLog(`正在发起视频渲染: ${res}, 时长: ${dur}s, FPS: ${fps}, LoRA: ${loraLog}`);

            } else if (currentMode === 'motion') {
                const videoPath = document.getElementById('motion-video-path')?.value || '';
                const imagePath = document.getElementById('motion-image-path')?.value || '';
                if (!videoPath) {
                    throw new Error('请先上传参考动作视频');
                }
                if (!imagePath) {
                    throw new Error('请先上传目标主体图');
                }
                const conditioningType = document.getElementById('motion-conditioning-type')?.value || 'canny';
                let strength = parseFloat(document.getElementById('motion-strength')?.value || '0.5');
                if (!Number.isFinite(strength)) strength = 0.5;
                strength = Math.max(0.1, Math.min(2.0, strength));
                const motionPrompt = prompt || 'A high quality video of the target subject following the reference motion, coherent movement, stable identity, clean details';
                endpoint = '/api/ic-lora/generate';
                payload = {
                    video_path: videoPath,
                    conditioning_type: conditioningType,
                    prompt: motionPrompt,
                    conditioning_strength: strength,
                    num_inference_steps: 30,
                    cfg_guidance_scale: 1.0,
                    negative_prompt: "low quality, blurry, noisy, static noise, distorted",
                    images: [{ path: imagePath, frame: 0, strength: 1.0 }]
                };
                if (!prompt) addLog('动作迁移未填写提示词，已使用默认动作迁移提示词');
                addLog(`正在发起动作迁移: ${conditioningType}, 控制强度 ${strength}`);

            } else if (currentMode === 'batch') {
                const res = updateBatchResPreview();
                const loraPaths = [];
                const loraStrengths = [];
                document.querySelectorAll('#batch-loras-container .lora-entry').forEach(entry => {
                    const sel = entry.querySelector('.lora-select');
                    const strIn = entry.querySelector('.lora-strength');
                    if (sel && sel.value) {
                        loraPaths.push(sel.value);
                        loraStrengths.push(strIn ? parseFloat(strIn.value) : 1.0);
                    }
                });
                
                const effectiveLoraPaths = loraPaths;
                const effectiveLoraStrengths = loraStrengths;
                const loraPath = effectiveLoraPaths[0] || null;
                const loraStrength = effectiveLoraStrengths[0] || 1.0;
                
                if (batchImages.length < 2) {
                    throw new Error(_t('errBatchMinImages'));
                }

                if (batchWorkflowIsSingle()) {
                    captureBatchKfTimelineFromDom();
                    const fps = document.getElementById('vid-fps').value;
                    const nKf = batchImages.length;
                    const minSeg = 0.1;
                    const frameDurs = [];
                    for (let j = 0; j < nKf; j++) {
                        let v = parseFloat(document.getElementById(`batch-kf-seg-dur-${j}`)?.value);
                        if (!Number.isFinite(v) || v < minSeg) v = minSeg;
                        frameDurs.push(v);
                    }
                    const sumSec = frameDurs.reduce((a, b) => a + b, 0);
                    const dur = Math.max(2, Math.ceil(sumSec - 1e-9));
                    const times = [0];
                    let acc = 0;
                    for (let j = 0; j < nKf - 1; j++) {
                        acc += frameDurs[j];
                        times.push(acc);
                    }
                    const combinedPrompt = prompt.trim();
                    if (!combinedPrompt) {
                        throw new Error(_t('errSingleKfPrompt'));
                    }
                    const strengths = [];
                    for (let i = 0; i < nKf; i++) {
                        const sEl = document.getElementById(`batch-kf-strength-${i}`);
                        let sv = parseFloat(sEl?.value);
                        if (!Number.isFinite(sv)) {
                            sv = parseFloat(defaultKeyframeStrengthForIndex(i, nKf));
                        }
                        if (!Number.isFinite(sv)) sv = 1;
                        sv = Math.max(0.1, Math.min(1.0, sv));
                        strengths.push(sv);
                    }
                    endpoint = '/api/generate';
                    payload = {
                        prompt: combinedPrompt,
                        resolution: res,
                        model: "ltx-2",
                        cameraMotion: document.getElementById('vid-motion').value,
                        negativePrompt: "low quality, blurry, noisy, static noise, distorted",
                        duration: String(dur),
                        fps,
                        audio: "false",
                        imagePath: null,
                        audioPath: null,
                        startFramePath: null,
                        endFramePath: null,
                        keyframePaths: batchImages.map((b) => b.path),
                        keyframeStrengths: strengths,
                        keyframeTimes: times,
                        aspectRatio: document.getElementById('batch-ratio').value,
                        loraPath: loraPath,
                        loraStrength: loraStrength,
                        loraPaths: effectiveLoraPaths.length > 0 ? effectiveLoraPaths : null,
                        loraStrengths: effectiveLoraStrengths.length > 0 ? effectiveLoraStrengths : null,
                    };
                    addLog(
                        `单次多关键帧: ${nKf} 帧时长合计 ${sumSec.toFixed(1)}s → 请求时长 ${dur}s, ${res}, FPS ${fps}`
                    );
                } else {
                    const segments = [];
                    for (let i = 0; i < batchImages.length - 1; i++) {
                        const duration = parseFloat(document.getElementById(`batch-segment-duration-${i}`)?.value || 5);
                        const segmentPrompt = document.getElementById(`batch-segment-prompt-${i}`)?.value || '';
                        const segParts = [prompt.trim(), segmentPrompt.trim()].filter(Boolean);
                        const combinedSegPrompt = segParts.join(', ');
                        segments.push({
                            startImage: batchImages[i].path,
                            endImage: batchImages[i + 1].path,
                            duration: duration,
                            prompt: combinedSegPrompt
                        });
                    }

                    endpoint = '/api/generate-batch';
                    const bgAudioEl = document.getElementById('batch-background-audio-path');
                    const backgroundAudioPath = (bgAudioEl && bgAudioEl.value) ? bgAudioEl.value.trim() : null;
                    payload = {
                        segments: segments,
                        resolution: res,
                        model: "ltx-2",
                        aspectRatio: document.getElementById('batch-ratio').value,
                        loraPath: loraPath,
                        loraStrength: loraStrength,
                        loraPaths: effectiveLoraPaths.length > 0 ? effectiveLoraPaths : null,
                        loraStrengths: effectiveLoraStrengths.length > 0 ? effectiveLoraStrengths : null,
                        negativePrompt: "low quality, blurry, noisy, static noise, distorted",
                        backgroundAudioPath: backgroundAudioPath || null
                    };
                    addLog(`分段拼接: ${segments.length} 段, ${res}${backgroundAudioPath ? '，含统一配乐' : ''}`);
                }
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
            const errText = e && e.message ? e.message : String(e);
            addLog(`❌ 渲染中断: ${errText}`);
            const loader = document.getElementById('loading-txt');
            if (loader) {
                loader.style.display = 'flex';
                loader.textContent = '';
                const span = document.createElement('span');
                span.style.cssText = 'color:var(--text-sub);font-size:13px;padding:12px;text-align:center;';
                span.textContent = `渲染失败：${errText}`;
                loader.appendChild(span);
            }

        } finally {
            // ✅ 无论发生什么，这里一定执行，确保按钮永远可以再次点击
            _isGeneratingFlag = false;
            btn.disabled = false;
            stopProgressPolling();
            checkStatus();
            // 生成完毕后自动释放显存（不 await 避免阻塞 UI 解锁）
            setTimeout(() => { clearGpu(); }, 500);
        }
    }

    async function clearGpu() {
        const btn = document.getElementById('clearGpuBtn');
        btn.disabled = true;
        btn.innerText = _t('clearingVram');
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
            btn.innerText = _t('clearVram');
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
                    const ph = String(d.phase || 'inference');
                    const phaseKey = 'phase_' + ph;
                    let phaseStr = _t(phaseKey);
                    if (phaseStr === phaseKey) phaseStr = ph;

                    let stepLabel;
                    if (d.current_step !== undefined && d.current_step !== null && d.total_steps) {
                        stepLabel = `${d.current_step}/${d.total_steps} ${_t('progressStepUnit')}`;
                    } else {
                        stepLabel = `${d.progress}%`;
                    }

                    document.getElementById('progress-fill').style.width = d.progress + "%";
                    const loaderStep = document.getElementById('loader-step-text');
                    const busyLine = `${_t('gpuBusyPrefix')}: ${stepLabel} [${phaseStr}]`;
                    if (loaderStep) loaderStep.innerText = busyLine;
                    else {
                        const loadingTxt = document.getElementById('loading-txt');
                        if (loadingTxt) loadingTxt.innerText = busyLine;
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

    function getAudioMime(filename) {
        const ext = String(filename || '').split('.').pop().toLowerCase();
        const map = { wav: 'audio/wav', mp3: 'audio/mpeg', flac: 'audio/flac', ogg: 'audio/ogg', m4a: 'audio/mp4', aac: 'audio/aac' };
        return map[ext] || 'audio/wav';
    }

    window.toggleAudioPreviewPlayback = function() {
        const audio = document.getElementById('res-audio');
        if (audioPlayer) {
            if (audioPlayer.playing) {
                audioPlayer.pause();
                return;
            }
            const playPromise = audioPlayer.play();
            if (playPromise && typeof playPromise.catch === 'function') {
                playPromise.catch(() => {});
            }
            return;
        }
        if (!audio) return;
        if (audio.paused) {
            const playPromise = audio.play();
            if (playPromise && typeof playPromise.catch === 'function') {
                playPromise.catch(() => {});
            }
        } else {
            audio.pause();
        }
    };

    function initAudioPreviewToggle() {
        const art = document.getElementById('audio-preview-art');
        if (!art || art.dataset.toggleBound === '1') return;
        art.dataset.toggleBound = '1';
        art.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            window.toggleAudioPreviewPlayback();
        });
        art.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter' && e.key !== ' ') return;
            e.preventDefault();
            window.toggleAudioPreviewPlayback();
        });
    }

    function displayOutput(fileOrPath, outputType = null) {
        const img = document.getElementById('res-img');
        const vid = document.getElementById('res-video');
        const audio = document.getElementById('res-audio');
        const audioWrapper = document.getElementById('audio-wrapper');
        const audioTitle = document.getElementById('audio-preview-title');
        const loader = document.getElementById('loading-txt');
        const videoWrapper = document.getElementById('video-wrapper');
        const effectiveType = outputType || currentMode;

        if (img) img.style.display = "none";
        if (videoWrapper) videoWrapper.style.display = "none";
        if (audioWrapper) audioWrapper.style.display = "none";
        
        // 关键BUG修复：切换前强制清除并停止现有视频和声音，避免后台继续播放
        if(player) {
            player.stop();
        } else {
            vid.pause();
            vid.removeAttribute('src');
            vid.load();
        }
        if (audio) {
            audio.pause();
            audio.removeAttribute('src');
            audio.load();
        }
        if (audioPlayer) {
            try { audioPlayer.stop(); } catch(_) {}
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
        if (effectiveType === 'audio') {
            if (audioTitle) audioTitle.textContent = fileName;
            if (audioWrapper) audioWrapper.style.display = "flex";
            if (audioPlayer) {
                audioPlayer.source = {
                    type: 'audio',
                    sources: [{ src: url, type: getAudioMime(fileName) }]
                };
                const playPromise = audioPlayer.play();
                if (playPromise && typeof playPromise.catch === 'function') {
                    playPromise.catch(() => {});
                }
            } else if (audio) {
                audio.src = url;
                audio.load();
                const playPromise = audio.play();
                if (playPromise && typeof playPromise.catch === 'function') {
                    playPromise.catch(() => {});
                }
            }
            addLog(`✅ 音频加载成功: ${fileName}`);
        } else if (effectiveType === 'image') {
            img.src = url;
            img.style.display = "block";
            addLog(`✅ 图像渲染成功: ${fileName}`);
        } else {
            if (videoWrapper) videoWrapper.style.display = "flex";
            
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
        if (!log) {
            console.log('[LTX]', msg);
            return;
        }
        const time = new Date().toLocaleTimeString();
        log.innerHTML += `<div style="margin-bottom:5px"> <span style="color:var(--text-dim)">[${time}]</span> ${msg}</div>`;
        log.scrollTop = log.scrollHeight;
    }


// Force switch to video mode on load
window.addEventListener('DOMContentLoaded', () => switchMode('video'));


    
    
    
    
    
    
    
    
    
    
    let currentHistoryPage = 1;
    let isLoadingHistory = false;
    /** 与上次成功渲染一致时，silent 轮询跳过整表 innerHTML，避免缩略图周期性重新加载 */
    let _historyListFingerprint = '';

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

            const validHistory = (data.history || []).filter(item => item && item.filename);
            const fingerprint = validHistory.length === 0
                ? '__empty__'
                : validHistory.map(h => `${h.type}|${h.filename}`).join('\0');

            if (silent && fingerprint === _historyListFingerprint) {
                return;
            }

            const container = document.getElementById('history-container');
            if (!container) {
                return;
            }

            let loadingCardHtml = "";
            const lc = document.getElementById('current-loading-card');
            if (lc && _isGeneratingFlag) {
                loadingCardHtml = lc.outerHTML;
            }

            if (validHistory.length === 0) {
                container.innerHTML = loadingCardHtml;
                const newLcEmpty = document.getElementById('current-loading-card');
                if (newLcEmpty) newLcEmpty.onclick = showGeneratingView;
                _historyListFingerprint = fingerprint;
                return;
            }

            container.innerHTML = loadingCardHtml;

            const outInput = document.getElementById('global-out-dir');
            const globalDir = outInput ? outInput.value.replace(/\\/g, '/').replace(/\/$/, '') : "";

            const cardsHtml = validHistory.map((item, index) => {
                    const url = (globalDir && globalDir !== "") 
                        ? `${BASE}/api/system/file?path=${encodeURIComponent(globalDir + '/' + item.filename)}` 
                        : `${BASE}/outputs/${item.filename}`;
                        
                    const safeFilename = item.filename.replace(/'/g, "\\'").replace(/"/g, '\\"');
                    const media = item.type === 'video'
                        ? `<video data-src="${url}" class="lazy-load history-thumb-media" muted preload="none" playsinline style="pointer-events: none; object-fit: cover; width: 100%; height: 100%;"></video>`
                        : item.type === 'audio'
                            ? `<div class="history-audio-thumb"><div class="history-audio-icon">♪</div><div>${escapeHtmlAttr(item.filename)}</div></div>`
                            : `<img data-src="${url}" class="lazy-load history-thumb-media" alt="" style="object-fit: cover; width: 100%; height: 100%;">`;
                    const typeBadge = item.type === 'video' ? '🎬 VID' : item.type === 'audio' ? '♪ AUD' : '🎨 IMG';
                    return `<div class="history-card" onclick="displayHistoryOutput('${safeFilename}', '${item.type}')">
                                <div class="history-type-badge">${typeBadge}</div>
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
            _historyListFingerprint = fingerprint;
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
                let revealed = false;
                let thumbRevealTimer;
                const revealThumb = () => {
                    if (revealed) return;
                    revealed = true;
                    if (thumbRevealTimer) clearTimeout(thumbRevealTimer);
                    media.classList.add('history-thumb-ready');
                };
                thumbRevealTimer = setTimeout(revealThumb, 4000);

                if (media.tagName === 'VIDEO') {
                    const revealVideoThumb = () => {
                        media.pause();
                        revealThumb();
                    };
                    media.addEventListener('loadedmetadata', () => {
                        const duration = Number.isFinite(media.duration) ? media.duration : 0;
                        const targetTime = Math.max(0.08, Math.min(1.2, duration > 0 ? duration * 0.18 : 0.5));
                        try {
                            media.currentTime = targetTime;
                        } catch (_) {
                            revealVideoThumb();
                        }
                    }, { once: true });
                    media.addEventListener('seeked', revealVideoThumb, { once: true });
                    media.addEventListener('loadeddata', () => {
                        if (media.currentTime > 0.04) revealVideoThumb();
                    }, { once: true });
                    media.addEventListener('error', revealThumb, { once: true });
                } else {
                    media.addEventListener('load', revealThumb, { once: true });
                    media.addEventListener('error', revealThumb, { once: true });
                }

                media.src = src;
                media.classList.remove('lazy-load');

                if (media.tagName === 'VIDEO') {
                    media.preload = 'auto';
                    media.load();
                } else if (media.complete && media.naturalWidth > 0) {
                    revealThumb();
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
        const audioWrapper = document.getElementById('audio-wrapper');
        if (audioWrapper) audioWrapper.style.display = 'none';
        displayOutput(file, type);
    }
    
    window.addEventListener('DOMContentLoaded', () => {
        initAudioPreviewToggle();
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
            audioPlayer = new Plyr('#res-audio', {
                controls: [
                    'play', 'progress', 'current-time',
                    'mute', 'volume'
                ],
                settings: []
            });
        }
        
        // Fetch current directory context to show in UI
        fetch(`${BASE}/api/system/get-dir`)
            .then((res) => res.json())
            .then((data) => {
                if (data && data.directory) {
                    const outInput = document.getElementById('global-out-dir');
                    if (outInput) outInput.value = data.directory;
                }
            })
            .catch((e) => console.error(e))
            .finally(() => {
                /* 先同步输出目录再拉历史，避免短时间内两次 fetchHistory 整表重绘导致缩略图闪两下 */
                switchLibTab('history');
            });

        // Load LoRA dir from settings
        loadLoraDir();

        let historyRefreshInterval = null;
        function startHistoryAutoRefresh() {
            if (historyRefreshInterval) return;
            historyRefreshInterval = setInterval(() => {
                const hc = document.getElementById('history-container');
                if (hc && hc.offsetParent !== null && !_isGeneratingFlag) {
                    fetchHistory(1, true);
                }
            }, 5000);
        }
        startHistoryAutoRefresh();
    });


async function saveVramLimit() {
    const lim = document.getElementById("vram-limit-input").value;
    const status = document.getElementById("vram-limit-status");
    status.textContent = "保存中...";
    try {
        const res = await fetch(`${BASE}/api/vram-limit`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ vramLimit: lim })
        });
        const d = await res.json();
        if (d.status === 'ok') {
            status.textContent = "保存成功";
            status.style.color = '#4caf50';
        } else throw new Error(d.message || "Unknown error");
    } catch (e) {
        status.textContent = e.message;
        status.style.color = '#f44336';
    }
}
async function fetchVramLimit() {
    try {
        const res = await fetch(`${BASE}/api/vram-limit`);
        const d = await res.json();
        if (d.vramLimit !== undefined && d.vramLimit !== null) {
            document.getElementById("vram-limit-input").value = d.vramLimit;
        }
    } catch (e) {}
}
try { fetchVramLimit(); } catch(e) {}

