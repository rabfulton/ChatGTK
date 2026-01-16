#!/usr/bin/env bash
set -euo pipefail

# Build a native Windows (onedir) bundle using MSYS2 UCRT64.
#
# Usage (in "MSYS2 UCRT64" shell, from repo root):
#   ./scripts/windows/build_exe.sh
#
# Troubleshooting (huge bundle):
#   CHATGTK_WIN_BUNDLE_ALL_DLLS=1 ./scripts/windows/build_exe.sh

python - <<'PY'
import sys

required = ["gi", "numpy", "sounddevice", "soundfile", "openai"]
missing = []
print("python:", sys.executable)
for name in required:
    try:
        mod = __import__(name)
        path = getattr(mod, "__file__", "(built-in)")
        print(f"ok: {name} -> {path}")
    except Exception as e:
        print(f"missing: {name}: {e}")
        missing.append(name)

if missing:
    print("\nMissing required runtime modules; install via pacman in MSYS2 UCRT64, for example:")
    print("  pacman -S --needed mingw-w64-ucrt-x86_64-python-gobject mingw-w64-ucrt-x86_64-python-numpy")
    raise SystemExit(2)
PY

rm -rf dist build
python -m PyInstaller --noconfirm --clean packaging/windows/ChatGTK.spec
