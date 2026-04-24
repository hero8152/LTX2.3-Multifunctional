# LTX2.3-Multifunctional

Cloud image: https://studio.aigate.cc/images/1093173874974662656?channel=R6P1L7N3J

Limited availability—free 24-hour online trial: https://cf9a6e7269dd44748353463b2d871d41.region1.waas.aigate.cc/

Tutorial： https://youtu.be/uQIgVwDjzBg

Update Notes: The latest versions 1.0.3 and 1.0.4 are compatible. Starting from version 1.0.3, regardless of the graphics card configuration, the default calculation is based on CPU memory, which slows down graphics cards with high video memory. Therefore, a video memory setting has been added. Setting it to 0 will use all video memory (recommended 24GB or more video memory, 32GB or more RAM). Setting it to less than 24GB will use some RAM (recommended 10GB or more video memory, 64GB or more RAM).

---

April 22, 2026 Update:

Fixed stuttering issue during multi-frame generation.

Added multi-LoRA functionality.

Added TTS functionality. Create a new folder named "VoxCPM2" in the model directory, download the model: https://huggingface.co/openbmb/VoxCPM2/tree/main, and run "installTTS environment.txt" to install the TTS environment.

---

Updated April 3, 2026:

Official version 1.0.3 has been released, significantly reducing video memory usage. Now, graphics cards with 12GB or more of video memory can run the program. Our tests show that, in a 10-second 720p frame test, the maximum video memory usage is only 12GB!
Download Link: https://github.com/Lightricks/LTX-Desktop/releases/tag/v1.0.3

----


April 2, 2026 Update:

1. Added LoRA functionality (place LoRA in the `loras` folder within the model directory).（Quick test LoRa: https://civitai.com/models/2482513/ltx23）

2. Added model selection capability (currently testing quantization to reduce GPU memory usage; modifying the model does not currently lower the GPU memory requirement, pending future updates).

3. Added multi-frame insertion functionality, with two generation modes: Mode 1: Inserts multiple frames into a latent space to directly generate a long video. Mode 2: Generates many independent first and last frame segments, which are then stitched together to form a complete video.

-------


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
<img width="2129" height="1614" alt="微信图片_20260402170131_481_218" src="https://github.com/user-attachments/assets/dd0f1044-f66f-4785-89ab-e1717a041c8b" />
<img width="2121" height="1610" alt="微信图片_20260402171010_482_218" src="https://github.com/user-attachments/assets/a40877bc-3682-44e3-9602-05d3bbb5cb89" />
https://github.com/user-attachments/assets/b7399618-0963-4834-81b2-d737d05a41a0
https://github.com/user-attachments/assets/e3e13685-d802-4df4-87c9-518b79859fdf
https://github.com/user-attachments/assets/991a8370-63fd-414e-bf88-843a4469024a




