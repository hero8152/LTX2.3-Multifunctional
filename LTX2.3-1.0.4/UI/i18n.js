/**
 * LTX UI i18n — 与根目录「中英文.html」思路类似，但独立脚本、避免坏 DOM/错误路径。
 * 仅维护文案映射；动态节点由 index.js 在语言切换后刷新。
 */
(function (global) {
    const STORAGE_KEY = 'ltx_ui_lang';

    const STR = {
        zh: {
            tabVideo: '视频生成',
            tabBatch: '智能多帧',
            tabUpscale: '视频增强',
            tabImage: '图像生成',
            promptLabel: '视觉描述词 (Prompt)',
            promptPlaceholder: '在此输入视觉描述词 (Prompt)...',
            promptPlaceholderUpscale: '输入画面增强引导词 (可选)...',
            clearVram: '释放显存',
            clearingVram: '清理中...',
            settingsTitle: '系统高级设置',
            langToggleAriaZh: '切换为 English',
            langToggleAriaEn: 'Switch to 中文',
            sysScanning: '正在扫描 GPU...',
            sysBusy: '运算中...',
            sysOnline: '在线 / 就绪',
            sysStarting: '启动中...',
            sysOffline: '未检测到后端 (Port 3000)',
            advancedSettings: '高级设置',
            deviceSelect: '工作设备选择',
            gpuDetecting: '正在检测 GPU...',
            outputPath: '输出与上传存储路径',
            outputPathPh: '例如: D:\\LTX_outputs',
            savePath: '保存路径',
            outputPathHint:
                '系统默认会在 C 盘保留输出文件。请输入新路径后点击保存按钮。',
            lowVram: '低显存优化',
            lowVramDesc:
                '尽量关闭 fast 超分、在加载管线后尝试 CPU 分层卸载（仅当引擎提供 Diffusers 式 API 才可能生效）。每次生成结束会卸载管线。说明：整模型常驻 GPU 时占用仍可能接近满配（例如约 24GB），要明显降占用需更短时长/更低分辨率或 FP8 等小权重。',
            vramLimitLabel: '可用最高显存上限 (GB, 0为全开优先显存)',
            vramLimitPh: '例如: 12 (0表示无限制)',
            saveLabel: '保存',
            modelLoraSettings: '模型与LoRA设置',
            modelFolder: '模型文件夹',
            modelFolderPh: '例如: F:\\LTX2.3\\models',
            loraFolder: 'LoRA文件夹',
            loraFolderPh: '例如: F:\\LTX2.3\\loras',
            loraFolderPath: 'LoRA 文件夹路径',
            loraFolderPathPlaceholder: '留空使用默认路径',
            saveScan: '保存并扫描',
            loraPlacementHintWithDir:
                '将 LoRA 文件放到默认模型目录: <code>{dir}</code>\\loras',
            basicEngine: '基础画面 / Basic EngineSpecs',
            qualityLevel: '清晰度级别',
            aspectRatio: '画幅比例',
            ratio169: '16:9 电影宽幅',
            ratio916: '9:16 移动竖屏',
            resPreviewPrefix: '最终发送规格',
            fpsLabel: '帧率 (FPS)',
            durationLabel: '时长 (秒)',
            cameraMotion: '镜头运动方式',
            motionStatic: 'Static (静止机位)',
            motionDollyIn: 'Dolly In (推近)',
            motionDollyOut: 'Dolly Out (拉远)',
            motionDollyLeft: 'Dolly Left (向左)',
            motionDollyRight: 'Dolly Right (向右)',
            motionJibUp: 'Jib Up (升臂)',
            motionJibDown: 'Jib Down (降臂)',
            motionFocus: 'Focus Shift (焦点)',
            audioGen: '生成 AI 环境音 (Audio Gen)',
            selectModel: '选择模型',
            selectLora: '选择 LoRA',
            defaultModel: '使用默认模型',
            noLora: '不使用 LoRA',
            loraStrength: 'LoRA 强度',
            genSource: '生成媒介 / Generation Source',
            startFrame: '起始帧 (首帧)',
            endFrame: '结束帧 (尾帧)',
            uploadStart: '上传首帧',
            uploadEnd: '上传尾帧 (可选)',
            refAudio: '参考音频 (A2V)',
            uploadAudio: '点击上传音频',
            sourceHint:
                '💡 若仅上传首帧 = 图生视频/音视频；若同时上传首尾帧 = 首尾插帧。',
            imgPreset: '预设分辨率 (Presets)',
            imgOptSquare: '1:1 Square (1024x1024)',
            imgOptLand: '16:9 Landscape (1280x720)',
            imgOptPort: '9:16 Portrait (720x1280)',
            imgOptCustom: 'Custom 自定义...',
            width: '宽度',
            height: '高度',
            samplingSteps: '采样步数 (Steps)',
            upscaleSource: '待超分视频 (Source)',
            upscaleUpload: '拖入低分辨率视频片段',
            targetRes: '目标分辨率',
            upscale1080: '1080P Full HD (2x)',
            upscale720: '720P HD',
            smartMultiFrameGroup: '智能多帧',
            workflowModeLabel: '工作流模式（点击切换）',
            wfSingle: '单次多关键帧',
            wfSegments: '分段拼接',
            uploadImages: '上传图片',
            uploadMulti1: '点击或拖入多张图片',
            uploadMulti2: '支持一次选多张，可多次添加',
            batchStripTitle: '已选图片 · 顺序 = 播放先后',
            batchStripHint: '在缩略图上按住拖动排序；松手落入虚线框位置',
            batchFfmpegHint:
                '💡 <strong>分段模式</strong>：2 张 = 1 段；3 张 = 2 段再拼接。<strong>单次模式</strong>：几张图就几个 latent 锚点，一条视频出片。<br>多段需 <code style="font-size:9px;">ffmpeg</code>：装好后加 PATH，或设环境变量 <code style="font-size:9px;">LTX_FFMPEG_PATH</code>，或在 <code style="font-size:9px;">%LOCALAPPDATA%\\LTXDesktop\\ffmpeg_path.txt</code> 第一行写 ffmpeg.exe 完整路径。',
            globalPromptLabel: '本页全局补充词（可选）',
            globalPromptPh: '与顶部主 Prompt 叠加；单次模式与分段模式均可用',
            bgmLabel: '成片配乐（可选，统一音轨）',
            bgmUploadHint: '上传一条完整 BGM（生成完成后会替换整段成片的音轨）',
            mainRender: '开始渲染',
            waitingTask: '等待分配渲染任务...',
            libHistory: '历史资产 / ASSETS',
            libLog: '系统日志 / LOGS',
            refresh: '刷新',
            logReady: '> LTX-2 Studio Ready. Expecting commands...',
            resizeHandleTitle: '拖动调整面板高度',
            batchNeedTwo: '💡 请上传至少2张图片',
            batchSegTitle: '视频片段设置（分段拼接）',
            batchSegClip: '片段',
            batchSegDuration: '时长',
            batchSegSec: '秒',
            batchSegPrompt: '片段提示词',
            batchSegPromptPh: '此片段的提示词，如：跳舞、吃饭...',
            batchKfPanelTitle: '单次多关键帧 · 时间轴',
            batchTotalDur: '总时长',
            batchTotalSec: '秒',
            batchPanelHint:
                '用「间隔」连接相邻关键帧：第 1 张固定在 0 s，最后一张在<strong>各间隔之和</strong>的终点。顶部总时长与每张的锚点时刻会随间隔即时刷新。因后端按<strong>整数秒</strong>建序列，实际请求里的整段时长为合计秒数<strong>向上取整</strong>（至少 2），略长于小数合计时属正常。镜头与 FPS 仍用左侧「视频生成」。',
            batchKfTitle: '关键帧',
            batchStrength: '引导强度',
            batchGapTitle: '间隔',
            batchSec: '秒',
            batchAnchorStart: '片头',
            batchAnchorEnd: '片尾',
            batchThumbDrag: '按住拖动排序',
            batchThumbRemove: '删除',
            batchAddMore: '＋ 继续添加',
            batchGapInputTitle: '上一关键帧到下一关键帧的时长（秒）；总时长 = 各间隔之和',
            batchStrengthTitle: '与 Comfy guide strength 类似，中间帧可调低（如 0.2）减轻闪烁',
            batchTotalPillTitle: '等于下方各「间隔」之和，无需单独填写',
            defaultPath: '默认路径',
            phase_loading_model: '加载权重',
            phase_encoding_text: 'T5 编码',
            phase_validating_request: '校验请求',
            phase_uploading_audio: '上传音频',
            phase_uploading_image: '上传图像',
            phase_inference: 'AI 推理',
            phase_downloading_output: '下载结果',
            phase_complete: '完成',
            gpuBusyPrefix: 'GPU 运算中',
            progressStepUnit: '步',
            loaderGpuAlloc: 'GPU 正在分配资源...',
            warnGenerating: '⚠️ 当前正在生成中，请等待完成',
            warnBatchPrompt: '⚠️ 智能多帧请至少填写：顶部主提示词、本页全局补充词或某一「片段提示词」',
            warnNeedPrompt: '⚠️ 请输入提示词后再开始渲染',
            warnVideoLong: '⚠️ 时长设定为 {n}s 极长，可能导致显存溢出或耗时较久。',
            errUpscaleNoVideo: '请先上传待超分的视频',
            errBatchMinImages: '请上传至少2张图片',
            errSingleKfPrompt: '单次多关键帧请至少填写顶部主提示词或本页全局补充词',
            loraNoneLabel: '无',
            modelDefaultLabel: '默认',
        },
        en: {
            tabVideo: 'Video',
            tabBatch: 'Multi-frame',
            tabUpscale: 'Upscale',
            tabImage: 'Image',
            promptLabel: 'Prompt',
            promptPlaceholder: 'Describe the scene...',
            promptPlaceholderUpscale: 'Optional guidance for enhancement...',
            clearVram: 'Clear VRAM',
            clearingVram: 'Clearing...',
            settingsTitle: 'Advanced settings',
            langToggleAriaZh: 'Switch to English',
            langToggleAriaEn: 'Switch to Chinese',
            sysScanning: 'Scanning GPU...',
            sysBusy: 'Busy...',
            sysOnline: 'Online / Ready',
            sysStarting: 'Starting...',
            sysOffline: 'Backend offline (port 3000)',
            advancedSettings: 'Advanced',
            deviceSelect: 'GPU device',
            gpuDetecting: 'Detecting GPU...',
            outputPath: 'Output & upload folder',
            outputPathPh: 'e.g. D:\\LTX_outputs',
            savePath: 'Save path',
            outputPathHint:
                'Outputs default to C: drive. Enter a folder and click Save.',
            lowVram: 'Low-VRAM mode',
            lowVramDesc:
                'Tries to reduce VRAM (engine-dependent). Shorter duration / lower resolution helps more.',
            vramLimitLabel: 'Max VRAM Limit (GB, 0 for unlimited)',
            vramLimitPh: 'e.g. 12 (0 for unlimited)',
            saveLabel: 'Save',
            modelLoraSettings: 'Model & LoRA folders',
            modelFolder: 'Models folder',
            modelFolderPh: 'e.g. F:\\LTX2.3\\models',
            loraFolder: 'LoRAs folder',
            loraFolderPh: 'e.g. F:\\LTX2.3\\loras',
            loraFolderPath: 'LoRA folder path',
            loraFolderPathPlaceholder: 'Leave empty for default path',
            saveScan: 'Save & scan',
            loraHint: 'Put .safetensors / .ckpt LoRAs here, then refresh lists.',
            basicEngine: 'Basic / Engine',
            qualityLevel: 'Quality',
            aspectRatio: 'Aspect ratio',
            ratio169: '16:9 widescreen',
            ratio916: '9:16 portrait',
            resPreviewPrefix: 'Output',
            fpsLabel: 'FPS',
            durationLabel: 'Duration (s)',
            cameraMotion: 'Camera motion',
            motionStatic: 'Static',
            motionDollyIn: 'Dolly in',
            motionDollyOut: 'Dolly out',
            motionDollyLeft: 'Dolly left',
            motionDollyRight: 'Dolly right',
            motionJibUp: 'Jib up',
            motionJibDown: 'Jib down',
            motionFocus: 'Focus shift',
            audioGen: 'AI ambient audio',
            selectModel: 'Model',
            selectLora: 'LoRA',
            defaultModel: 'Default model',
            noLora: 'No LoRA',
            loraStrength: 'LoRA strength',
            genSource: 'Source media',
            startFrame: 'Start frame',
            endFrame: 'End frame (optional)',
            uploadStart: 'Upload start',
            uploadEnd: 'Upload end (opt.)',
            refAudio: 'Reference audio (A2V)',
            uploadAudio: 'Upload audio',
            sourceHint:
                '💡 Start only = I2V / A2V; start + end = interpolation.',
            imgPreset: 'Resolution presets',
            imgOptSquare: '1:1 (1024×1024)',
            imgOptLand: '16:9 (1280×720)',
            imgOptPort: '9:16 (720×1280)',
            imgOptCustom: 'Custom...',
            width: 'Width',
            height: 'Height',
            samplingSteps: 'Steps',
            upscaleSource: 'Source video',
            upscaleUpload: 'Drop low-res video',
            targetRes: 'Target resolution',
            upscale1080: '1080p Full HD (2×)',
            upscale720: '720p HD',
            smartMultiFrameGroup: 'Smart multi-frame',
            workflowModeLabel: 'Workflow',
            wfSingle: 'Single pass',
            wfSegments: 'Segments',
            uploadImages: 'Upload images',
            uploadMulti1: 'Click or drop multiple images',
            uploadMulti2: 'Multi-select OK; add more anytime.',
            batchStripTitle: 'Order = playback',
            batchStripHint: 'Drag thumbnails to reorder.',
            batchFfmpegHint:
                '💡 <strong>Segments</strong>: 2 images → 1 clip; 3 → 2 clips stitched. <strong>Single</strong>: N images → N latent anchors, one video.<br>Stitching needs <code style="font-size:9px;">ffmpeg</code> on PATH, or <code style="font-size:9px;">LTX_FFMPEG_PATH</code>, or <code style="font-size:9px;">%LOCALAPPDATA%\\LTXDesktop\\ffmpeg_path.txt</code> with full path to ffmpeg.exe.',
            globalPromptLabel: 'Extra prompt (optional)',
            globalPromptPh: 'Appended to main prompt for both modes.',
            bgmLabel: 'Full-length BGM (optional)',
            bgmUploadHint: 'Replaces final mix audio after generation.',
            mainRender: 'Render',
            waitingTask: 'Waiting for task...',
            libHistory: 'Assets',
            libLog: 'Logs',
            refresh: 'Refresh',
            logReady: '> LTX-2 Studio ready.',
            resizeHandleTitle: 'Drag to resize panel',
            batchNeedTwo: '💡 Upload at least 2 images',
            batchSegTitle: 'Segment settings',
            batchSegClip: 'Clip',
            batchSegDuration: 'Duration',
            batchSegSec: 's',
            batchSegPrompt: 'Prompt',
            batchSegPromptPh: 'e.g. dancing, walking...',
            batchKfPanelTitle: 'Single pass · timeline',
            batchTotalDur: 'Total',
            batchTotalSec: 's',
            batchPanelHint:
                'Use gaps between keyframes: first at 0s, last at the sum of gaps. Totals update live. Backend uses whole seconds (ceil, min 2). Motion & FPS use the Video panel.',
            batchKfTitle: 'Keyframe',
            batchStrength: 'Strength',
            batchGapTitle: 'Gap',
            batchSec: 's',
            batchAnchorStart: 'start',
            batchAnchorEnd: 'end',
            batchThumbDrag: 'Drag to reorder',
            batchThumbRemove: 'Remove',
            batchAddMore: '+ Add more',
            batchGapInputTitle: 'Seconds between keyframes; total = sum of gaps',
            batchStrengthTitle: 'Guide strength (lower on middle keys may reduce flicker)',
            batchTotalPillTitle: 'Equals the sum of gaps below',
            defaultPath: 'default',
            phase_loading_model: 'Loading weights',
            phase_encoding_text: 'T5 encode',
            phase_validating_request: 'Validating',
            phase_uploading_audio: 'Uploading audio',
            phase_uploading_image: 'Uploading image',
            phase_inference: 'Inference',
            phase_downloading_output: 'Downloading',
            phase_complete: 'Done',
            gpuBusyPrefix: 'GPU',
            progressStepUnit: 'steps',
            loaderGpuAlloc: 'Allocating GPU...',
            warnGenerating: '⚠️ Already generating, please wait.',
            warnBatchPrompt: '⚠️ Enter main prompt, page extra prompt, or a segment prompt.',
            warnNeedPrompt: '⚠️ Enter a prompt first.',
            warnVideoLong: '⚠️ Duration {n}s is very long; may OOM or take a long time.',
            errUpscaleNoVideo: 'Upload a video to upscale first.',
            errBatchMinImages: 'Upload at least 2 images.',
            errSingleKfNeedPrompt: 'Enter main or page extra prompt for single-pass keyframes.',
            loraNoneLabel: 'none',
            modelDefaultLabel: 'default',
            loraPlacementHintWithDir:
                'Place LoRAs into the default models directory: <code>{dir}</code>\\loras',
        },
    };

    function getLang() {
        return localStorage.getItem(STORAGE_KEY) === 'en' ? 'en' : 'zh';
    }

    function setLang(lang) {
        const L = lang === 'en' ? 'en' : 'zh';
        localStorage.setItem(STORAGE_KEY, L);
        document.documentElement.lang = L === 'en' ? 'en' : 'zh-CN';
        try {
            applyI18n();
        } catch (err) {
            console.error('[i18n] applyI18n failed:', err);
        }
        updateLangButton();
        if (typeof global.onUiLanguageChanged === 'function') {
            try {
                global.onUiLanguageChanged();
            } catch (e) {
                console.warn('onUiLanguageChanged', e);
            }
        }
    }

    function t(key) {
        const L = getLang();
        const table = STR[L] || STR.zh;
        if (Object.prototype.hasOwnProperty.call(table, key)) return table[key];
        if (Object.prototype.hasOwnProperty.call(STR.zh, key)) return STR.zh[key];
        return key;
    }

    function applyI18n(root) {
        root = root || document;
        root.querySelectorAll('[data-i18n]').forEach(function (el) {
            var key = el.getAttribute('data-i18n');
            if (!key) return;
            if (el.tagName === 'OPTION') {
                el.textContent = t(key);
            } else {
                el.textContent = t(key);
            }
        });
        root.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
            var key = el.getAttribute('data-i18n-placeholder');
            if (key) el.placeholder = t(key);
        });
        root.querySelectorAll('[data-i18n-title]').forEach(function (el) {
            var key = el.getAttribute('data-i18n-title');
            if (key) el.title = t(key);
        });
        root.querySelectorAll('[data-i18n-html]').forEach(function (el) {
            var key = el.getAttribute('data-i18n-html');
            if (key) el.innerHTML = t(key);
        });
        root.querySelectorAll('[data-i18n-value]').forEach(function (el) {
            var key = el.getAttribute('data-i18n-value');
            if (key && (el.tagName === 'INPUT' || el.tagName === 'BUTTON')) {
                el.value = t(key);
            }
        });
    }

    function updateLangButton() {
        var btn = document.getElementById('lang-toggle-btn');
        if (!btn) return;
        btn.textContent = getLang() === 'zh' ? 'EN' : '中';
        btn.setAttribute(
            'aria-label',
            getLang() === 'zh' ? t('langToggleAriaZh') : t('langToggleAriaEn')
        );
        btn.classList.toggle('active', getLang() === 'en');
    }

    function toggleUiLanguage() {
        try {
            setLang(getLang() === 'zh' ? 'en' : 'zh');
        } catch (err) {
            console.error('[i18n] toggleUiLanguage failed:', err);
        }
    }

    /** 避免 CSP 拦截内联 onclick；确保按钮一定能触发 */
    function bindLangToggleButton() {
        var btn = document.getElementById('lang-toggle-btn');
        if (!btn || btn.dataset.i18nBound === '1') return;
        btn.dataset.i18nBound = '1';
        btn.removeAttribute('onclick');
        btn.addEventListener('click', function (ev) {
            ev.preventDefault();
            toggleUiLanguage();
        });
    }

    function boot() {
        document.documentElement.lang = getLang() === 'en' ? 'en' : 'zh-CN';
        try {
            applyI18n();
        } catch (err) {
            console.error('[i18n] applyI18n failed:', err);
        }
        updateLangButton();
        bindLangToggleButton();
    }

    global.getUiLang = getLang;
    global.setUiLang = setLang;
    global.t = t;
    global.applyI18n = applyI18n;
    global.toggleUiLanguage = toggleUiLanguage;
    global.updateLangToggleButton = updateLangButton;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})(typeof window !== 'undefined' ? window : global);
