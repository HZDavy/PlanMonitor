# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['coding_plan_monitor.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'numpy', 'pandas', 'scipy', 'PIL',
        'tkinter', 'test', 'unittest', 'pytest',
        'PyQt5.QtNetwork', 'PyQt5.QtWebEngineCore', 'PyQt5.QtWebEngineWidgets',
        'PyQt5.QtWebChannel', 'PyQt5.QtMultimedia', 'PyQt5.QtSql',
        'PyQt5.QtTest', 'PyQt5.QtBluetooth', 'PyQt5.QtSerialPort',
        'PyQt5.QtNfc', 'PyQt5.QtPositioning', 'PyQt5.QtSensors',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PlanMonitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                 # GUI 模式，运行时无黑色 cmd 窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='release/app.ico',         # 自定义应用图标 (圆角矩形深底 + 火山方舟 logo, multi-size ICO)
    manifest='app.manifest',       # 声明 PerMonitorV2 DPI 感知, 避免 Windows bitmap 拉伸
)