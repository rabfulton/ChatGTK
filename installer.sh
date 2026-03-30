#!/usr/bin/env bash
set -euo pipefail

# Simple curl|sh friendly installer for Linux.

REPO_URL="${CHATGTK_REPO_URL:-https://github.com/rabfulton/ChatGTK}"
BRANCH="${CHATGTK_BRANCH:-}"
INSTALL_DIR="${CHATGTK_INSTALL_DIR:-$HOME/.local/share/chatgtk}"
UPDATE_EXISTING="${CHATGTK_UPDATE:-0}"

log() {
  printf '%s\n' "$*"
}

fail() {
  printf '%s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

get_linux_runtime_hint() {
  local distro_id=""
  local distro_like=""

  if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    distro_id="${ID:-}"
    distro_like="${ID_LIKE:-}"
  fi

  case " ${distro_id} ${distro_like} " in
    *" debian "*|*" ubuntu "*)
      printf '%s\n' \
        "sudo apt install python3-venv python3-gi gir1.2-gtk-3.0 gir1.2-gtksource-4 libportaudio2"
      ;;
    *" arch "*|*" manjaro "*)
      printf '%s\n' \
        "sudo pacman -S python python-gobject gtk3 gtksourceview4 portaudio"
      ;;
    *" fedora "*|*" rhel "*|*" centos "*)
      printf '%s\n' \
        "sudo dnf install python3-gobject gtk3 gtksourceview4 portaudio"
      ;;
    *)
      printf '%s\n' \
        "Install your distro's GTK 3, GtkSourceView 4, PyGObject, and PortAudio runtime packages."
      ;;
  esac
}

ensure_linux_runtime_deps() {
  local check_cmd='import gi; gi.require_version("Gtk", "3.0"); gi.require_version("GtkSource", "4"); from gi.repository import Gtk, GtkSource'

  if python3 -c "$check_cmd" >/dev/null 2>&1; then
    return 0
  fi

  fail "$(cat <<EOF
ChatGTK needs the system GTK bindings on Linux, but python3 cannot import them.

Install the required runtime packages first, for example:
  $(get_linux_runtime_hint)

Then rerun this installer. The virtual environment is created with
--system-site-packages so it can reuse those distro-provided bindings.
EOF
)"
}

need_cmd git
need_cmd python3
ensure_linux_runtime_deps

if [ -d "$INSTALL_DIR" ] && [ "$UPDATE_EXISTING" != "1" ]; then
  log "Install directory exists; refreshing application files in $INSTALL_DIR"
elif [ -d "$INSTALL_DIR" ] && [ "$UPDATE_EXISTING" = "1" ]; then
  log "Updating install in $INSTALL_DIR"
fi

tmp_dir="$(mktemp -d)"
if [ -n "$BRANCH" ]; then
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$tmp_dir"
else
  git clone --depth 1 "$REPO_URL" "$tmp_dir"
fi

install_app_files() {
  local src_dir="$1"
  local dest_dir="$2"

  copy_optional_wav_dir() {
    local dir_name="$1"
    local -a wav_files=()

    mkdir -p "$dest_dir/src/$dir_name"
    if [ -d "$src_dir/src/$dir_name" ]; then
      shopt -s nullglob
      wav_files=("$src_dir/src/$dir_name/"*.wav)
      shopt -u nullglob
      if [ ${#wav_files[@]} -gt 0 ]; then
        install -m 644 "${wav_files[@]}" "$dest_dir/src/$dir_name/"
      fi
    fi
  }

  mkdir -p "$dest_dir/src"

  install -m 644 "$src_dir/src/ChatGTK.py" "$dest_dir/src/ChatGTK.py"
  install -m 644 "$src_dir/src/config.py" "$dest_dir/src/config.py"
  install -m 644 "$src_dir/src/ai_providers.py" "$dest_dir/src/ai_providers.py"
  install -m 644 "$src_dir/src/controller.py" "$dest_dir/src/controller.py"
  install -m 644 "$src_dir/src/conversation.py" "$dest_dir/src/conversation.py"
  install -m 644 "$src_dir/src/dialogs.py" "$dest_dir/src/dialogs.py"
  install -m 644 "$src_dir/src/gtk_utils.py" "$dest_dir/src/gtk_utils.py"
  install -m 644 "$src_dir/src/latex_utils.py" "$dest_dir/src/latex_utils.py"
  install -m 644 "$src_dir/src/markup_utils.py" "$dest_dir/src/markup_utils.py"
  install -m 644 "$src_dir/src/message_renderer.py" "$dest_dir/src/message_renderer.py"
  install -m 644 "$src_dir/src/tools.py" "$dest_dir/src/tools.py"
  install -m 644 "$src_dir/src/utils.py" "$dest_dir/src/utils.py"
  install -m 644 "$src_dir/src/__init__.py" "$dest_dir/src/__init__.py"

  mkdir -p "$dest_dir/src/model_cards"
  install -m 644 "$src_dir/src/model_cards/"*.py "$dest_dir/src/model_cards/"

  mkdir -p "$dest_dir/src/repositories"
  install -m 644 "$src_dir/src/repositories/"*.py "$dest_dir/src/repositories/"

  mkdir -p "$dest_dir/src/services"
  install -m 644 "$src_dir/src/services/"*.py "$dest_dir/src/services/"

  mkdir -p "$dest_dir/src/events"
  install -m 644 "$src_dir/src/events/"*.py "$dest_dir/src/events/"

  mkdir -p "$dest_dir/src/settings"
  install -m 644 "$src_dir/src/settings/"*.py "$dest_dir/src/settings/"

  mkdir -p "$dest_dir/src/ui"
  install -m 644 "$src_dir/src/ui/"*.py "$dest_dir/src/ui/"

  mkdir -p "$dest_dir/src/realtime"
  if [ -d "$src_dir/src/realtime" ]; then
    install -m 644 "$src_dir/src/realtime/"*.py "$dest_dir/src/realtime/" 2>/dev/null || true
  fi

  mkdir -p "$dest_dir/src/memory"
  if [ -d "$src_dir/src/memory" ]; then
    install -m 644 "$src_dir/src/memory/"*.py "$dest_dir/src/memory/" 2>/dev/null || true
  fi

  install -m 644 "$src_dir/src/icon.png" "$dest_dir/src/icon.png"

  copy_optional_wav_dir "preview"
  copy_optional_wav_dir "gemini_preview"
  copy_optional_wav_dir "xai_preview"

  install -m 644 "$src_dir/requirements.txt" "$dest_dir/requirements.txt"
}

install_app_files "$tmp_dir" "$INSTALL_DIR"

log "Creating virtual environment"
python3 -m venv --system-site-packages "$INSTALL_DIR/.venv"

log "Installing Python dependencies"
"$INSTALL_DIR/.venv/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
"$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip
"$INSTALL_DIR/.venv/bin/python" -m pip install -r "$INSTALL_DIR/requirements.txt"
"$INSTALL_DIR/.venv/bin/python" -c \
  'import gi; gi.require_version("Gtk", "3.0"); gi.require_version("GtkSource", "4"); from gi.repository import Gtk, GtkSource' \
  >/dev/null 2>&1 || fail "The virtual environment could not see the system GTK bindings."

rm -rf "$tmp_dir"

log "Creating launcher script"
cat << 'EOF' > "$INSTALL_DIR/chatgtk-launcher.sh"
#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/src/ChatGTK.py"
EOF
chmod +x "$INSTALL_DIR/chatgtk-launcher.sh"

log "Creating desktop entry"
XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
mkdir -p "$XDG_DATA_HOME/applications"
cat << EOF > "$XDG_DATA_HOME/applications/chatgtk.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=ChatGTK
Comment=OpenAI Chat Client with GTK interface
Exec=$INSTALL_DIR/chatgtk-launcher.sh
Icon=$INSTALL_DIR/src/icon.png
Categories=Network;Chat;AI;
Terminal=false
StartupNotify=true
Keywords=chat;ai;gpt;openai;
EOF

if command -v update-desktop-database >/dev/null 2>&1; then
  log "Updating desktop database"
  update-desktop-database "$XDG_DATA_HOME/applications" >/dev/null 2>&1 || true
fi

cat << 'EOM'

ChatGTK installed.

Next steps:
  1) Set at least one API key in your environment or configure them inside the application, for example:
       export OPENAI_API_KEY="sk-..."
  2) Launch the app from the terminal or via your GUI:
       ~/.local/share/chatgtk/chatgtk-launcher.sh

Notes:
  - For LaTeX math rendering, install `texlive` and `dvipng` using your distributions package manager.
  - For music control of your local media files, install `beets` and `playerctl`.
EOM
