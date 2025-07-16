# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Scribe CLI (Windows packaging)
"""

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Get the path to the source directory
src_path = os.path.join(os.getcwd(), 'src')

# Collect data files for torch and related packages (with error handling)
try:
    torch_data = collect_data_files('torch')
except Exception:
    torch_data = []

try:
    torchaudio_data = collect_data_files('torchaudio')
except Exception:
    torchaudio_data = []

try:
    faster_whisper_data = collect_data_files('faster_whisper')
except Exception:
    faster_whisper_data = []

try:
    sounddevice_data = collect_data_files('sounddevice')
except Exception:
    sounddevice_data = []

# Collect hidden imports
hidden_imports = [
    'torch',
    'torchaudio', 
    'faster_whisper',
    'sounddevice',
    'numpy',
    'click',
    'nvidia.cudnn',
    'ctranslate2',
    'tokenizers'
]

# Add torch submodules (with error handling)
try:
    hidden_imports.extend(collect_submodules('torch'))
except Exception:
    pass

try:
    hidden_imports.extend(collect_submodules('torchaudio'))
except Exception:
    pass

block_cipher = None

a = Analysis(
    ['src/scribe/main.py'],
    pathex=[src_path],
    binaries=[],
    datas=torch_data + torchaudio_data + faster_whisper_data + sounddevice_data,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyGObject',
        'gi',
        'gtk',
        'matplotlib',
        'IPython',
        'jupyter',
        'notebook'
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
    [],
    exclude_binaries=True,
    name='scribe-cli',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='scribe-cli',
)