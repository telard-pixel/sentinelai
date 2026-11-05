"""Crea version.txt (dati di versione dell'exe) e sentinel.ico dall'icona dell'app."""
import sys
from PIL import Image

v = (sys.argv[1] if len(sys.argv) > 1 else "1.0.0").lstrip("v")
parts = [int(x) if x.isdigit() else 0 for x in (v.split("-")[0].split(".") + ["0"] * 4)[:4]]
Image.open("../frontend/public/icon-512.png").save("sentinel.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
t = tuple(parts)
open("version.txt", "w", encoding="utf-8").write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('041004b0', [
    StringStruct('CompanyName', 'Roberto'), StringStruct('FileDescription', 'SentinelAI Vision Guard'),
    StringStruct('FileVersion', '{v}'), StringStruct('ProductName', 'SentinelAI'), StringStruct('ProductVersion', '{v}'),
    StringStruct('OriginalFilename', 'SentinelAI.exe')])]), VarFileInfo([VarStruct('Translation', [0x0410, 1200])])])
""")
open("VERSIONE", "w", encoding="utf-8").write(v)
print("versione", v, t)
