#!/bin/bash
# One-time setup on the GPU machine (Ubuntu). Safe to run again.
#   - creates .venv and installs the studio
#   - links the `studio` command into ~/.local/bin
#   - writes the two systemd *user* units (no [Install] section: nothing starts at boot,
#     `studio start` / `studio stop` control them)
# Usage: scripts/install.sh [path/to/ComfyUI]      (default: ~/ComfyUI)
set -euo pipefail

REPO="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
COMFY="$(readlink -f "${1:-$HOME/ComfyUI}")"
UNITS="$HOME/.config/systemd/user"

command -v ffmpeg >/dev/null || { echo "ffmpeg not found: sudo apt install ffmpeg"; exit 1; }
[ -f "$COMFY/main.py" ] || echo "warning: no ComfyUI at $COMFY (pass its path as the first argument)"
COMFY_PY="$COMFY/venv/bin/python"
[ -x "$COMFY_PY" ] || COMFY_PY="$(command -v python3)"

echo "== venv"
cd "$REPO"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[dev]"

echo "== studio command"
chmod +x bin/studio
mkdir -p "$HOME/.local/bin"
ln -sf "$REPO/bin/studio" "$HOME/.local/bin/studio"

echo "== systemd user units"
mkdir -p "$UNITS" logs
for f in deploy/systemd/*.service.in; do
  out="$UNITS/$(basename "${f%.in}")"
  sed -e "s#@REPO@#$REPO#g" -e "s#@COMFY@#$COMFY#g" -e "s#@COMFY_PY@#$COMFY_PY#g" "$f" > "$out"
  echo "   $out"
done
systemctl --user daemon-reload
# keep user services alive after you log out of SSH
loginctl enable-linger "$USER" 2>/dev/null || echo "   (run 'sudo loginctl enable-linger $USER' so renders survive logging out)"

if [ "$COMFY" != "$HOME/ComfyUI" ]; then
  sed -i "s#^  comfyui_root: .*#  comfyui_root: $COMFY#" config.yaml
fi

echo "== tests"
.venv/bin/python -m pytest -q | tail -1

cat <<EOF

Installed. Next:
  1. Put the ComfyUI models, custom nodes and voices in place (see README.md "Requirements").
  2. Build or copy a character library into assets/characters/library/ (optional, for dialogue scenes).
  3. studio start      then drop a script into $REPO/inbox/
EOF
