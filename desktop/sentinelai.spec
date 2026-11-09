# PyInstaller: SentinelAI.exe (cartella), con server, app compilata e modello YOLO11s ONNX.
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

# OpenVINO (1.0.15): tutte le DLL (togliere i lettori TensorFlow/PyTorch/Paddle fa chiudere l'exe: import openvino li carica)
openvino_libs = collect_dynamic_libs("openvino")

hidden = (collect_submodules("uvicorn") + collect_submodules("websockets")
          + ["server", "session", "clips", "detection", "models", "telegram_bot", "auth_local", "docstore", "aggiornamento", "risorse",
             "pystray._win32", "openpyxl", "imageio_ffmpeg", "tzdata", "zoneinfo",
             "webview.platforms.winforms", "webview.platforms.edgechromium", "clr",
             "openvino", "openvino.runtime", "onnxruntime", "winreg"])

a = Analysis(
    ["sentinel_desktop.py"],
    pathex=["../backend"],
    datas=[("../frontend/build", "static"), ("../models/yolo11s.onnx", "models"),
           ("../frontend/public/icon-192.png", "."), ("VERSIONE", "."),
           ("../backend/chiave_pubblica.pem", ".")]
          + collect_data_files("imageio_ffmpeg", includes=["binaries/*"]) + collect_data_files("tzdata")
          + collect_data_files("webview")
          + collect_data_files("openvino", excludes=["**/tools/**", "**/*.pyi"]),
    # 1.0.15: OpenVINO (DLL del motore e dei plugin CPU/GPU, plugins.xml)
    binaries=collect_dynamic_libs("webview") + openvino_libs + collect_dynamic_libs("onnxruntime"),
    hiddenimports=hidden,
    excludes=["torch", "torchvision", "ultralytics", "motor", "pandas", "matplotlib", "tkinter",
              "IPython", "scipy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SentinelAI", console=False,
          icon="sentinel.ico", version="version.txt")
coll = COLLECT(exe, a.binaries, a.datas, name="SentinelAI")
