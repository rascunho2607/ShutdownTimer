# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['ShutdownApp.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('icos', 'icos')  # inclui o ícone no build
    ],
    hiddenimports=[
        'customtkinter'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ShutdownTimer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon='icos/shutdown.ico',  # ícone do exe
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)