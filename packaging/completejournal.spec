# PyInstaller spec — builds the double-click desktop app for the current OS.
#   pyinstaller packaging/completejournal.spec --noconfirm
# Output: dist/CompleteJournal/ (Windows/Linux) or dist/Complete Journal.app (macOS)
import os
import sys
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # repo root, wherever we build from
sys.path.insert(0, ROOT)
PKG = os.path.join(ROOT, "completejournal")
# Data files listed explicitly: a silent miss here breaks the app at runtime.
datas = [
    (os.path.join(PKG, "schema.sql"), "completejournal"),
    (os.path.join(PKG, "web"), "completejournal/web"),
]
for src, _ in datas:
    if not os.path.exists(src):
        raise SystemExit(f"missing data file for the bundle: {src}")
hidden = (collect_submodules("completejournal")
          + collect_submodules("uvicorn")
          + ["tzdata"] * (sys.platform == "win32"))
# Optional components are bundled when present on the build machine.
# AI ships switched off: it does nothing until the user saves a key.
for optional in ("webview", "anthropic", "keyring"):
    try:
        __import__(optional)
        hidden += collect_submodules(optional)
    except ImportError:
        pass

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hidden,
    excludes=["pytest", "tkinter", "playwright", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="CompleteJournal",
    console=sys.platform.startswith("linux"),  # windowed app on Windows/macOS
)
coll = COLLECT(exe, a.binaries, a.datas, name="CompleteJournal")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Complete Journal.app", bundle_identifier="app.completejournal")
