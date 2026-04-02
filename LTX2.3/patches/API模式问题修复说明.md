# LTX 本地显卡模式修复

## 问题描述
系统强制使用 FAL API 生成图片，即使本地有 GPU 可用。

## 原因
LTX 强制要求 GPU 有 31GB VRAM 才会使用本地显卡，低于此值会强制走 API 模式。

## 修复方法

### 方法一：自动替换（推荐）
运行程序后，patches 目录中的文件会自动替换原版文件。

### 方法二：手动替换

#### 1. 修改 VRAM 阈值
- **原文件**: `C:\Program Files\LTX Desktop\resources\backend\runtime_config\runtime_policy.py`
- **找到** (第16行):
  ```python
  return vram_gb < 31
  ```
- **改为**:
  ```python
  return vram_gb < 6
  ```

#### 2. 清空无效 API Key
- **原文件**: `C:\Users\Administrator\AppData\Local\LTXDesktop\settings.json`
- **找到**:
  ```json
  "fal_api_key": "12123",
  ```
- **改为**:
  ```json
  "fal_api_key": "",
  ```

## 说明
- VRAM 阈值改为 6GB，意味着 6GB 及以上显存都会使用本地显卡
- 清空 fal_api_key 避免系统误判为已配置 API
- 修改后重启程序即可生效
