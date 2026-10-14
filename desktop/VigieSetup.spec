# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:/Users/ASSIMTI/claude/memoire/Vigie/vigie/desktop/installer/setup_main.py'],
    pathex=[],
    binaries=[],
    datas=[('C:/Users/ASSIMTI/claude/memoire/Vigie/vigie/desktop/build/vigie-app.zip', '.'), ('C:/Users/ASSIMTI/claude/memoire/Vigie/vigie/desktop/build/VERSION', '.'), ('C:/Users/ASSIMTI/claude/memoire/Vigie/vigie/desktop/vigie_desktop', 'vigie_desktop')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['webview', 'tkinter', 'numpy', 'torch', 'PIL', 'matplotlib', 'pandas', 'scipy', 'whisper', 'IPython', 'pytest', 'openai', 'anthropic', 'fastapi', 'uvicorn', 'cryptography', 'pygments'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VigieSetup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='C:/Users/ASSIMTI/claude/memoire/Vigie/vigie/desktop/build/version.txt',
    icon=['C:/Users/ASSIMTI/claude/memoire/Vigie/vigie/desktop/assets/vigie-blue.ico'],
)
