# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Oscilloscope Screenshot Tool
Builds a single-file Windows executable
"""

import sys
from pathlib import Path

block_cipher = None

# Get the directory containing this spec file
spec_dir = Path(SPECPATH)

a = Analysis(
    ['main_gui.py'],
    pathex=[str(spec_dir)],
    binaries=[],
    datas=[
        ('style.qss', '.'),  # Include stylesheet
        ('oscilloscope_control.py', '.'),  # Include control module
    ],
    hiddenimports=[
        'pyvisa',
        'pyvisa.resources',
        'pyvisa.resources.messagebased',
        'pyvisa.errors',
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.sip',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'cv2',
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
    name='OscilloscopeScreenshotTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add icon path here if you have one: icon='icon.ico'
    version=None,
)
