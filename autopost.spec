# -*- mode: python ; coding: utf-8 -*-
# AutoPost v2 — PyInstaller ビルド設定

import os
import sys

block_cipher = None

# プロジェクトルート
ROOT = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    [os.path.join(ROOT, 'app.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'frontend'), 'frontend'),
        (os.path.join(ROOT, 'icon.ico'), '.'),
        (os.path.join(ROOT, 'backend', 'INBOX'), os.path.join('backend', 'INBOX')),
    ],
    hiddenimports=[
        'backend.api',
        'backend.logic',
        'backend.engagement',
        'backend.config_manager',
        'flask',
        'google.genai',
        'tweepy',
        'feedparser',
        'schedule',
        'requests',
        'bs4',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='AutoPost',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=os.path.join(ROOT, 'icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AutoPost',
)
