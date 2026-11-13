# PyInstaller — modo pasta (--onedir): as DLLs do Qt ficam substituíveis (LGPL)
# e o programa abre mais rápido do que no modo arquivo único.
# Uso: pyinstaller packaging/nexus_intel.spec --noconfirm

from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

ROOT = Path(SPECPATH).parent  # noqa: F821 (definido pelo PyInstaller)
SRC = ROOT / "src" / "nexus_intel"

datas = [
    (str(SRC / "infrastructure" / "db" / "migrations"), "nexus_intel/infrastructure/db/migrations"),
    (str(SRC / "ui" / "assets"), "nexus_intel/ui/assets"),
    # Processo de voz Kokoro: executado pelo Python do ambiente separado, precisa existir como arquivo.
    (str(SRC / "infrastructure" / "voice" / "kokoro_worker.py"), "nexus_intel/infrastructure/voice"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD_PARTY_LICENSES.md"), "."),
]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=collect_dynamic_libs("sqlcipher3"),
    datas=datas,
    hiddenimports=["sqlcipher3", "sqlcipher3.dbapi2", "PySide6.QtSvg"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtPdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
icon = ROOT / "packaging" / "nexus.ico"
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NexusIntel",
    console=False,
    icon=str(icon) if icon.exists() else None,
    version=str(ROOT / "packaging" / "version_info.txt") if (ROOT / "packaging" / "version_info.txt").exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="NexusIntel")  # noqa: F821
