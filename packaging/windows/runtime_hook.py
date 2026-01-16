import os
import sys


def _set_env(key: str, value: str) -> None:
    if value and key not in os.environ:
        os.environ[key] = value


if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    base = sys._MEIPASS  # type: ignore[attr-defined]
    # Ensure bundled DLLs are discoverable.
    os.environ["PATH"] = base + os.pathsep + os.environ.get("PATH", "")

    # Ensure the bundled GTK runtime can locate its data files and schemas.
    share = os.path.join(base, "share")
    lib = os.path.join(base, "lib")

    _set_env("GTK_DATA_PREFIX", base)
    _set_env("XDG_DATA_DIRS", share)

    # GObject introspection typelibs bundled by the spec.
    gi_typelib_path = os.path.join(lib, "girepository-1.0")
    _set_env("GI_TYPELIB_PATH", gi_typelib_path)

    # gdk-pixbuf loader discovery.
    gdk_pixbuf_module_dir = os.path.join(lib, "gdk-pixbuf-2.0", "2.10.0", "loaders")
    gdk_pixbuf_module_file = os.path.join(lib, "gdk-pixbuf-2.0", "2.10.0", "loaders.cache")
    _set_env("GDK_PIXBUF_MODULEDIR", gdk_pixbuf_module_dir)
    _set_env("GDK_PIXBUF_MODULE_FILE", gdk_pixbuf_module_file)
