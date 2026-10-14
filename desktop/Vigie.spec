# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:/Users/ASSIMTI/claude/memoire/Vigie/vigie/desktop/vigie_launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('C:/Users/ASSIMTI/claude/memoire/Vigie/vigie/desktop/ui', 'ui')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'numpy', 'torch', 'PIL', 'matplotlib', 'pandas', 'scipy', 'whisper', 'IPython', 'pytest', 'openai', 'anthropic', 'fastapi', 'uvicorn', 'cryptography', 'pygments'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Vigie',
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
    version='C:/Users/ASSIMTI/claude/memoire/Vigie/vigie/desktop/build/version.txt',
    icon=['C:/Users/ASSIMTI/claude/memoire/Vigie/vigie/desktop/assets/vigie-blue.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Vigie',
)
