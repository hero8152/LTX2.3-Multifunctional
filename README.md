# LTX2.3-Multifunctional
Functionality optimization based on LTX desktop version

This program mainly optimizes the desktop version of LTX, breaking the generation time limitations and lowering the barrier to use. It now only requires 24GB to run, whereas the desktop version needs 32GB.

Compared to the messy and complex workflows and error-prone nodes in the ComfyUI version, this one integrates all features, including image-to-video, text-to-video, start/end frames, lip-sync, video enhancement, and image generation.

No need to install any third-party software—just install the LTX desktop version and you’re good to go. It’s very simple and efficient.

Tutorial: https://youtu.be/rM_wUogtrOU

Desktop version software download address: https://ltx.io/ltx-desktop

It can be accessed via ComfyUI, node address: https://github.com/supart/ComfyUI_TY_LTX_Desktop_Bridge

-----------

1. 复制LTX桌面版的快捷方式到LTX_Shortcut

2. 运行run.bat

1. Copy the LTX desktop shortcut to LTX_Shortcut

2. Run run.bat
----


【问题描述 / Problem】
系统强制使用 FAL API 生成图片，即使本地有 GPU 可用。
System forces FAL API generation even when local GPU is available.

【原因 / Cause】
LTX 强制要求 GPU 有 31GB VRAM 才会使用本地显卡，低于此值会强制走 API 模式。
LTX requires 31GB VRAM to use local GPU. Below this, it forces API mode.


【修复方法 / Fix Method】


运行: API issues.bat.bat (以管理员身份)
Run: API issues.bat.bat (as Administrator)

----

【或者手动 / Or Manual】

1. 修改 VRAM 阈值 / Modify VRAM Threshold
   文件路径 / File: C:\Program Files\LTX Desktop\resources\backend\runtime_config\runtime_policy.py
   第16行 / Line 16:
   原 / Original: return vram_gb < 31
   改为 / Change:  return vram_gb < 6

2. 清空 API Key / Clear API Key
   文件路径 / File: C:\Users\<用户名>\AppData\Local\LTXDesktop\settings.json
   原 / Original: "fal_api_key": "xxxxx"
   改为 / Change:  "fal_api_key": ""

【说明 / Note】
- VRAM 阈值改为 6GB，意味着 6GB 及以上显存都会使用本地显卡
- VRAM threshold set to 6GB means 6GB+ VRAM will use local GPU
- 清空 fal_api_key 避免系统误判为已配置 API
- Clear fal_api_key to avoid system thinking API is configured
- 修改后重启程序即可生效
- Restart LTX Desktop after changes
================================================================================
