# PyInstaller: SentinelAI.exe (cartella), con server, app compilata e modello YOLOv8n ONNX.
from PyInstaller.utils.hooks import collect_submodules

hidden = (collect_submodules("uvicorn") + collect_submodules("websockets")
          + ["server", "session", "clips", "detection", "models", "telegram_bot", "auth_local", "docstore",
             "pystray._win32", "openpyxl"])

a = Analysis(
    ["sentinel_desktop.py"],
    pathex=["../backend"],
    datas=[("../frontend/build", "static"), ("../models/yolov8n.onnx", "models"),
           ("../frontend/public/icon-192.png", "."), ("VERSIONE", ".")],
    hiddenimports=hidden,
    excludes=["torch", "torchvision", "ultralytics", "motor", "pandas", "matplotlib", "tkinter",
              "imageio_ffmpeg", "IPython", "scipy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SentinelAI", console=False,
          icon="sentinel.ico", version="version.txt")
coll = COLLECT(exe, a.binaries, a.datas, name="SentinelAI")
