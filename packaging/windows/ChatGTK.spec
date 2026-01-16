# PyInstaller spec for building a native Windows bundle using MSYS2 (UCRT64).
#
# Build:
#   python -m PyInstaller --noconfirm --clean packaging/windows/ChatGTK.spec
#
# Output:
#   dist/ChatGTK/ChatGTK.exe  (onedir)

from __future__ import annotations

import os
import importlib.util
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

def _find_repo_root(start_dir: Path) -> Path:
    cur = start_dir.resolve()
    for _ in range(8):
        if (cur / "src" / "ChatGTK.py").exists():
            return cur
        cur = cur.parent
    return start_dir.resolve()


# PyInstaller does not guarantee __file__ is set for spec execution.
_spec_dir = Path(globals().get("SPECPATH", os.getcwd())).resolve()
ROOT = _find_repo_root(_spec_dir)
SRC = ROOT / "src"
ENTRY_SCRIPT = SRC / "ChatGTK.py"

MINGW_PREFIX = Path(os.environ.get("MINGW_PREFIX", "/ucrt64"))


def _data_dir(src: Path, dest: str) -> list[tuple[str, str]]:
    if not src.exists():
        return []
    return [(str(src), dest)]


hiddenimports = []
hiddenimports += collect_submodules("realtime")
hiddenimports += collect_submodules("model_cards")
hiddenimports += collect_submodules("repositories")
hiddenimports += collect_submodules("services")
hiddenimports += collect_submodules("events")
hiddenimports += collect_submodules("settings")
hiddenimports += collect_submodules("ui")
hiddenimports += collect_submodules("memory")

datas: list[tuple[str, str]] = []
datas += _data_dir(SRC / "icon.png", "src")
datas += _data_dir(SRC / "preview", "src/preview")

gi_datas, gi_binaries, gi_hiddenimports = collect_all("gi")
datas += gi_datas
hiddenimports += gi_hiddenimports
hiddenimports += ["gi"]

# Bundle GTK runtime data from MSYS2 so the app runs outside MSYS2.
datas += _data_dir(MINGW_PREFIX / "share" / "glib-2.0" / "schemas", "share/glib-2.0/schemas")
datas += _data_dir(MINGW_PREFIX / "share" / "icons", "share/icons")
datas += _data_dir(MINGW_PREFIX / "share" / "gtksourceview-4", "share/gtksourceview-4")

# Bundle GObject introspection typelibs and gdk-pixbuf loaders.
datas += _data_dir(MINGW_PREFIX / "lib" / "girepository-1.0", "lib/girepository-1.0")
datas += _data_dir(MINGW_PREFIX / "lib" / "gdk-pixbuf-2.0", "lib/gdk-pixbuf-2.0")

binaries: list[tuple[str, str]] = []
bin_dir = MINGW_PREFIX / "bin"
bundle_all_dlls = os.environ.get("CHATGTK_WIN_BUNDLE_ALL_DLLS", "0") == "1"
if bin_dir.exists() and bundle_all_dlls:
    # Troubleshooting mode: huge, but likely to "just work".
    for dll in bin_dir.glob("*.dll"):
        binaries.append((str(dll), "."))
elif bin_dir.exists():
    # Default: bundle a curated set of DLLs required by GTK + GObject introspection + audio.
    # This keeps the distribution far smaller than copying all of /ucrt64/bin.
    dll_allowlist = {
        # Core GTK/GDK stack
        "gtk-3-0.dll",
        "gdk-3-0.dll",
        "gdk_pixbuf-2.0-0.dll",
        "glib-2.0-0.dll",
        "gobject-2.0-0.dll",
        "gio-2.0-0.dll",
        "gmodule-2.0-0.dll",
        "gthread-2.0-0.dll",
        "atk-1.0-0.dll",
        "pango-1.0-0.dll",
        "pangocairo-1.0-0.dll",
        "pangoft2-1.0-0.dll",
        "cairo-2.dll",
        "pixman-1-0.dll",
        "harfbuzz-0.dll",
        "freetype-6.dll",
        "fontconfig-1.dll",
        "libepoxy-0.dll",
        "libffi-8.dll",
        "pcre2-8-0.dll",
        "zlib1.dll",
        "libpng16-16.dll",
        "libjpeg-8.dll",
        "libtiff-6.dll",
        # Introspection
        "girepository-1.0-1.dll",
        # GtkSourceView
        "gtksourceview-4-0.dll",
        # Common runtime deps
        "libintl-8.dll",
        "iconv-2.dll",
        "libwinpthread-1.dll",
        # Audio
        "libportaudio-2.dll",
        "libsndfile-1.dll",
        "libogg-0.dll",
        "libvorbis-0.dll",
        "libvorbisenc-2.dll",
        "libFLAC-12.dll",
        "libopus-0.dll",
    }

    seen_bin = set()

    def _add_bin(path: Path) -> None:
        key = str(path).lower()
        if key in seen_bin:
            return
        seen_bin.add(key)
        binaries.append((str(path), "."))

    for dll_name in sorted(dll_allowlist):
        dll_path = bin_dir / dll_name
        if dll_path.exists():
            _add_bin(dll_path)

    # PortAudio/libsndfile naming varies across environments; include any matches to avoid
    # `OSError: PortAudio library not found` at runtime.
    for pattern in ("*portaudio*.dll", "*sndfile*.dll"):
        for dll_path in bin_dir.glob(pattern):
            if dll_path.exists():
                _add_bin(dll_path)

# Include gi dynamic libs (e.g. gi._gi).
binaries += gi_binaries

# MSYS2 may provide PyGObject's `gi` as a compiled module (gi.pyd) rather than a package.
# Ensure we bundle it by locating the import target directly.
gi_spec = importlib.util.find_spec("gi")
if gi_spec and gi_spec.origin:
    gi_origin = Path(gi_spec.origin)
    if gi_spec.submodule_search_locations:
        gi_pkg_dir = Path(list(gi_spec.submodule_search_locations)[0])
        # Add the package directory as a data folder. PyInstaller will copy it into dist.
        datas.append((str(gi_pkg_dir), "gi"))
    elif gi_origin.suffix.lower() in {".pyd", ".dll"}:
        binaries.append((str(gi_origin), "."))

a = Analysis(
    [str(ENTRY_SCRIPT)],
    pathex=[str(ROOT), str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[str(_spec_dir / "runtime_hook.py")],
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
    name="ChatGTK",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    # Windows requires .ico; leave unset to avoid build-time conversion dependency.
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ChatGTK",
)
