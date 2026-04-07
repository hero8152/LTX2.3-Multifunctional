
import sys
import os

patch_dir = r"C:\Users\1-xuanran\Desktop\ltx-TEST-1.0.3\patches"
backend_dir = r"C:\Program Files\LTX Desktop\resources\backend"

# 防御性清除：强行剥离所有的默认 backend_dir 引用
sys.path = [p for p in sys.path if p and os.path.normpath(p) != os.path.normpath(backend_dir)]
sys.path = [p for p in sys.path if p and p != "." and p != ""]

# 绝对插队注入：优先搜索 PATCHES_DIR
sys.path.insert(0, patch_dir)
sys.path.insert(1, backend_dir)

import uvicorn
from ltx2_server import app

if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=3000, log_level="info", access_log=False)
