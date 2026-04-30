### RH Online Use of Standard Version LTX2.3:
[RH Online LTX2.3 Standard Version](https://www.runninghub.ai/post/2030340655863570434?inviteCode=rh-v1331)

### Local Plugin Version Online Mirror (Registration gives computation voucher):
[Local Plugin Version](https://studio.aigate.cc/images/1093173874974662656?channel=R6P1L7N3J)

### Video Tutorial:
[Video Tutorial](https://youtu.be/rQOjHtzONpE)

### GitHub Project Address:
[GitHub Project](https://github.com/hero8152/LTX2.3-Multifunctional/tree/main)

---

### Model Directory:
Root directory:
  - dpt-hybrid-midas folder
  - gemma-3-12b-it-qat-q4_0-unquantized folder
  - loras folder
  - VoxCPM2 folder
  - Z-Image-Turbo folder
  - dw-ll_ucoco_384_bs5.torchscript.pt
  - yolox_l.torchscript.pt
  - LTX2.3-22B_IC-LoRA-Cameraman_v1_10500.safetensors
  - ltx-2.3-22b-distilled-fp8.safetensors
  - ltx-2.3-spatial-upscaler-x2-1.0.safetensors

### Software Download Link:
[Download LTX2.3](https://github.com/Lightricks/LTX-Desktop/releases/tag/v1.0.4)

### fp8 Model Link:
[fp8 Model](https://huggingface.co/Lightricks/LTX-2.3-fp8/blob/main/ltx-2.3-22b-distilled-fp8.safetensors)

### Camera Control Model Link:
[Camera Control Model](https://huggingface.co/Cseti/LTX2.3-22B_IC-LoRA-Cameraman_v1/blob/a4445ddc3f72374adbf218df29906e475b68bcb1/LTX2.3-22B_IC-LoRA-Cameraman_v1_10500.safetensors)

### Migration Control Model Links:
- [dw-ll_ucoco_384_bs5](https://huggingface.co/hr16/DWPose-TorchScript-BatchSize5/blob/main/dw-ll_ucoco_384_bs5.torchscript.pt)
- [yolox_l.torchscript](https://huggingface.co/hr16/yolox-onnx/blob/main/yolox_l.torchscript.pt)
- [dpt-hybrid-midas](https://huggingface.co/Intel/dpt-hybrid-midas/tree/main)
### TTS Link: 
- [VoxCPM2](https://huggingface.co/openbmb/VoxCPM2/tree/main)

---

### Software Feature Introduction (These features are not available in the desktop version):
1. Switch between multiple GPUs, with queue functionality supported.
2. Set the maximum memory limit based on your own GPU memory to prevent overflow; for memories over 24GB, you can set it to 0, which means no memory limitation.
3. Switch to fp8 models, which I personally find to have better performance.
4. Mount multiple loras.
5. Lock seed functionality, and the generated videos will carry all relevant information for future reuse.
   - Key point: If a good result is achieved with a specific seed, you can lock it and fine-tune the prompt or lora strength to improve the results further.
6. As long as there’s enough GPU memory, you can generate longer videos instead of being restricted by the desktop version's 1080p 5-second limit.
7. First and last frame functionality.
8. Intelligent multi-frame functionality.
9. Action migration (including pose/depth/line control), camera movement migration, and video redrawing.
10. TTS voice generation and voice cloning functionality.
11. It can be accessed via ComfyUI, node address: https://github.com/supart/ComfyUI_TY_LTX_Desktop_Bridge

<img width="2129" height="1614" alt="微信图片_20260402170131_481_218" src="https://github.com/user-attachments/assets/dd0f1044-f66f-4785-89ab-e1717a041c8b" />
<img width="2121" height="1610" alt="微信图片_20260402171010_482_218" src="https://github.com/user-attachments/assets/a40877bc-3682-44e3-9602-05d3bbb5cb89" />





