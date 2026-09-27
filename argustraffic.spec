import glob
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

datas = [
    ('configs', 'configs'),
    ('src', 'src'),
    ('assets', 'assets'),
    ('yolov8n.pt', '.'),
    ('demo_traffic.mp4', '.'),
]

# Explicitly include torchvision extension binaries for Python 3.14+
import torchvision
tv_dir = os.path.dirname(torchvision.__file__)
for tv_bin in glob.glob(os.path.join(tv_dir, "*_stable.pyd")) + glob.glob(os.path.join(tv_dir, "*.dll")):
    datas.append((tv_bin, "torchvision"))

# Collect any ultralytics or web assets if present
datas += collect_data_files('ultralytics')
datas += collect_data_files('webview')

hiddenimports = [
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'fastapi',
    'pydantic',
    'pydantic_core',
    'websockets',
    'sqlite3',
    'webview',
    'webview.platforms.winforms',
    'yaml',
    'PIL',
    'torch',
    'torchvision',
    'ultralytics',
    'lap',
    'unittest',
    'src.perception',
    'src.api.app',
    'src.api.routes',
]
hiddenimports += collect_submodules('uvicorn')
hiddenimports += collect_submodules('src')
hiddenimports += collect_submodules('webview')

a = Analysis(
    ['desktop_app.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ArgusTraffic',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app_icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ArgusTraffic',
)
