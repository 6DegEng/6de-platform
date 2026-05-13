# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the 6DE Company Platform Launcher.

Build with:
    pyinstaller launcher.spec --clean

Output: ``dist/6DE Platform.exe``  -- a single, console-less .exe (~1 MB).

Design notes
------------
* This .exe is a *launcher only*.  It does NOT bundle Streamlit, pandas,
  pythonnet, pywebview, or anything else from requirements.txt.  Those are
  loaded by the host Python interpreter the launcher discovers at runtime.
* That choice deliberately avoids the failure mode in the previous
  Calculator build (``RuntimeError: Failed to initialize Python.Runtime.dll``)
  -- the launcher has no native dependencies at all.
* ``console=False`` hides the cmd window on launch.  Errors are surfaced via
  a Windows MessageBox (see ``_show_error`` in launcher.py) and ``launcher.log``.
* ``upx=False`` keeps the build deterministic and avoids antivirus false
  positives that UPX-compressed PyInstaller builds sometimes trigger.
"""

block_cipher = None


a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Streamlit/data libs are loaded by the host Python, not bundled.
        # Excluding them shrinks the .exe and avoids hook fragility.
        'streamlit',
        'pandas',
        'numpy',
        'pyarrow',
        'openpyxl',
        'altair',
        'bcrypt',
        'yaml',
        'streamlit_authenticator',
        # Anything from the previous Calculator stack -- not needed here.
        'webview',
        'pythonnet',
        'clr',
        'clr_loader',
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
    name='6DE Platform',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # hide cmd window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='launcher.ico',   # uncomment once you drop an icon next to this spec
)
