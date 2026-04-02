import os
import sys
import subprocess
import threading
import time
import socket
import logging
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# ============================================================
# 配置区 (动态路径适配与补丁挂载)
# ============================================================
def resolve_ltx_path():
    import glob, tempfile, subprocess
    sc_dir = os.path.join(os.getcwd(), "LTX_Shortcut")
    os.makedirs(sc_dir, exist_ok=True)
    lnk_files = glob.glob(os.path.join(sc_dir, "*.lnk"))
    if not lnk_files:
        print("\033[91m[ERROR] 未在 LTX_Shortcut 文件夹中找到快捷方式！\n请打开程序目录下的 LTX_Shortcut 文件夹，并将官方 LTX Desktop 的快捷方式复制进去后重试。\033[0m")
        sys.exit(1)
        
    lnk_path = lnk_files[0]
    # 使用 VBScript 解析快捷方式，兼容所有 Windows 系统
    vbs_code = f'''Set sh = CreateObject("WScript.Shell")\nSet obj = sh.CreateShortcut("{os.path.abspath(lnk_path)}")\nWScript.Echo obj.TargetPath'''
    fd, vbs_path = tempfile.mkstemp(suffix='.vbs')
    with os.fdopen(fd, 'w') as f:
        f.write(vbs_code)
    try:
        out = subprocess.check_output(['cscript', '//nologo', vbs_path], stderr=subprocess.STDOUT)
        target_exe = out.decode('ansi').strip()
    finally:
        os.remove(vbs_path)
        
    if not target_exe or not os.path.exists(target_exe):
        # 如果快捷方式解析失败，或者解析出来的是朋友电脑的路径（当前电脑不存在），自动全盘搜索默认路径
        default_paths = [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\LTX Desktop\LTX Desktop.exe"),
            r"C:\Program Files\LTX Desktop\LTX Desktop.exe",
            r"D:\Program Files\LTX Desktop\LTX Desktop.exe",
            r"E:\Program Files\LTX Desktop\LTX Desktop.exe"
        ]
        found = False
        for p in default_paths:
            if os.path.exists(p):
                target_exe = p
                print(f"\033[96m[INFO] 自动检测到 LTX 原版安装路径: {p}\033[0m")
                found = True
                break
        
        if not found:
            print(f"\033[91m[ERROR] 未能找到原版 LTX Desktop 的安装路径！\033[0m")
            print("请清理 LTX_Shortcut 文件夹，并将您当前电脑上真正的原版快捷方式重贴复制进去。")
            sys.exit(1)
        
    return os.path.dirname(target_exe)

USER_PROFILE = os.path.expanduser("~")
PYTHON_EXE = os.path.join(USER_PROFILE, r"AppData\Local\LTXDesktop\python\python.exe")
DATA_DIR = os.path.join(USER_PROFILE, r"AppData\Local\LTXDesktop")

# 1. 动态获取主安装路径
LTX_INSTALL_DIR = resolve_ltx_path()
BACKEND_DIR = os.path.join(LTX_INSTALL_DIR, r"resources\backend")
UI_FILE_NAME = "UI/index.html"

# 环境致命检测：如果官方 Python 还没解压释放，立刻强制中断整个程序
if not os.path.exists(PYTHON_EXE):
    print(f"\n\033[1;41m [致命错误] 您的电脑上尚未配置好 LTX 的官方渲染核心框架！ \033[0m")
    print(f"\033[93m此应用仅是 UI 图形控制台，必需依赖原版软件环境才能生成。在 ({PYTHON_EXE}) 未找到运行引擎。\n")
    print(">> 解决方案：\n1. 请先在您的电脑上正常安装【LTX Desktop 官方原版软件】。")
    print("2. 必需：双击打开运行一次原版软件！（运行后原版软件会在后台自动释放环境）")
    print("3. 把原版软件的快捷方式复制到本文档的 LTX_Shortcut 文件夹里面。")
    print("4. 全部完成后，再重新启动本 run.bat 脚本即可！\033[0m\n")
    os._exit(1)

# 2. 从目录读取改动过的 Python 文件 (热修复拦截器)
PATCHES_DIR = os.path.join(os.getcwd(), "patches")
os.makedirs(PATCHES_DIR, exist_ok=True)

# 3. 默认输出定向至程序根目录
LOCAL_OUTPUTS = os.path.join(os.getcwd(), "outputs")
os.makedirs(LOCAL_OUTPUTS, exist_ok=True)

# 强制注入自定义输出录至 LTX 缓存数据中
os.makedirs(DATA_DIR, exist_ok=True)
with open(os.path.join(DATA_DIR, "custom_dir.txt"), 'w', encoding='utf-8') as f:
    f.write(LOCAL_OUTPUTS)

os.environ["LTX_APP_DATA_DIR"] = DATA_DIR

# 将 patches 目录优先级提升，做到 Python 无损替换
os.environ["PYTHONPATH"] = f"{PATCHES_DIR};{BACKEND_DIR}"

def get_lan_ip():
    try:
        host_name = socket.gethostname()
        _, _, ip_list = socket.gethostbyname_ex(host_name)
        
        candidates = []
        for ip in ip_list:
            if ip.startswith("192.168."):
                return ip
            elif ip.startswith("10.") or (ip.startswith("172.") and 16 <= int(ip.split('.')[1]) <= 31):
                candidates.append(ip)
                
        if candidates:
            return candidates[0]
            
        # Fallback to the default socket routing approach if no obvious LAN IP found
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

LAN_IP = get_lan_ip()

# ============================================================
# 服务启动逻辑
# ============================================================
def check_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def launch_backend():
    """启动核心引擎 - 监听 0.0.0.0 确保局域网可调"""
    if check_port_in_use(3000):
        print(f"\n\033[1;41m [致命错误] 3000 端口已被占用，无法启动核心引擎！ \033[0m")
        print("\033[93m>> 绝大多数情况下，这是因为【官方原版 LTX Desktop】正在您的电脑后台运行。\033[0m")
        print(">> 冲突会导致显存爆炸。请检查右下角系统托盘图标，右键完全退出官方软件。")
        print(">> 退出后重新双击 run.bat 启动本程序！\n")
        os._exit(1)

    print(f"\033[96m[CORE] 核心引擎正在启动...\033[0m")
    # 只开启重要级别的 Python 应用层日志，去除无用的 HTTP 刷屏
    import logging as _logging
    _logging.basicConfig(
        level=_logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True
    )
    
    # 构建绝对无损的环境拦截器：防止其他电脑被 cwd 劫持加载原版文件
    launcher_code = f"""
import sys
import os

patch_dir = r"{PATCHES_DIR}"
backend_dir = r"{BACKEND_DIR}"

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
"""
    launcher_path = os.path.join(PATCHES_DIR, "launcher.py")
    with open(launcher_path, "w", encoding="utf-8") as f:
        f.write(launcher_code)

    cmd = [PYTHON_EXE, launcher_path]
    env = os.environ.copy()
    result = subprocess.run(cmd, cwd=BACKEND_DIR, env=env)
    if result.returncode != 0:
        print(f"\n\033[1;41m [致命错误] 核心引擎异常崩溃退出！ (Exit Code: {result.returncode})\033[0m")
        print(">> 请检查上述终端报错信息。确认显卡驱动是否正常。")
        os._exit(1)

ui_app = FastAPI()
# 已移除存在安全隐患的静态资源挂载目录

@ui_app.get("/")
async def serve_index():
    return FileResponse(os.path.join(os.getcwd(), UI_FILE_NAME))

@ui_app.get("/index.css")
async def serve_css():
    return FileResponse(os.path.join(os.getcwd(), "UI/index.css"))

@ui_app.get("/index.js")
async def serve_js():
    return FileResponse(os.path.join(os.getcwd(), "UI/index.js"))


@ui_app.get("/i18n.js")
async def serve_i18n():
    return FileResponse(os.path.join(os.getcwd(), "UI/i18n.js"))


def launch_ui_server():
    print(f"\033[92m[UI] 工作站已就绪！\033[0m")
    print(f"\033[92m[LOCAL] 本机访问: http://127.0.0.1:4000\033[0m")
    print(f"\033[93m[WIFI]  局域网访问: http://{LAN_IP}:4000\033[0m")
    
    # 彻底压制 WinError 10054 (客户端强制断开) 的底层警告报错
    if sys.platform == 'win32':
        # Uvicorn 内部会拉起循环，所以只能通过底层 Logging Filter 拦截控制台噪音
        class UvicornAsyncioNoiseFilter(logging.Filter):
            """压掉客户端断开、Win Proactor 管道收尾等无害 asyncio 控制台刷屏。"""

            def filter(self, record):
                if record.name != "asyncio":
                    return True
                msg = record.getMessage()
                if "_call_connection_lost" in msg or "_ProactorBasePipeTransport" in msg:
                    return False
                if hasattr(record, "exc_info") and record.exc_info:
                    exc_type, exc_value, _ = record.exc_info
                    if isinstance(exc_value, ConnectionResetError) and getattr(
                        exc_value, "winerror", None
                    ) == 10054:
                        return False
                if "10054" in msg and "ConnectionResetError" in msg:
                    return False
                return True

        logging.getLogger("asyncio").addFilter(UvicornAsyncioNoiseFilter())
        
    uvicorn.run(ui_app, host="0.0.0.0", port=4000, log_level="warning", access_log=False)

if __name__ == "__main__":
    os.system('cls' if os.name == 'nt' else 'clear')
    print("\033[1;97;44m LTX-2 CINEMATIC WORKSTATION | NETWORK ENABLED \033[0m\n")
    
    threading.Thread(target=launch_backend, daemon=True).start()
    
    # 强制校验 3000 端口是否存活
    print("\033[93m[SYS] 正在等待内部核心 3000 端口启动...\033[0m")
    backend_ready = False
    for _ in range(30):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(('127.0.0.1', 3000)) == 0:
                    backend_ready = True
                    break
        except Exception:
            pass
        time.sleep(1)
        
    if backend_ready:
        print("\033[92m[SYS] 3000 端口已通过连通性握手验证！后端装载成功。\033[0m")
    else:
        print("\033[1;41m [崩坏警告] 等待 30 秒后，3000 端口依然无法连通！ \033[0m")
        print(">> Uvicorn 可能在后台陷入了死锁，或者被防火墙拦截，前端大概率将无法连接到后端！")
        print(">> 请检查上方是否有 Python 报错。\n")
        
    try:
        launch_ui_server()
    except KeyboardInterrupt:
        sys.exit(0)