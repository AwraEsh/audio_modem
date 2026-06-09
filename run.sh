#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3 first."
  exit 1
fi

if [ ! -d "$VENV" ]; then
  "$PYTHON_BIN" -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install --upgrade pip >/dev/null
"$VENV/bin/python" -m pip install -r "$ROOT/requirements.txt"

if [[ "$(uname -s)" == "Linux" ]]; then
  if ! "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import tkinter  # noqa: F401
import sounddevice  # noqa: F401
PY
  then
    echo ""
    echo "Some system dependencies may be missing."
    if command -v sudo >/dev/null 2>&1 && command -v apt-get >/dev/null 2>&1; then
      echo "Trying common Debian/Ubuntu packages..."
      sudo apt-get update
      sudo apt-get install -y python3-tk portaudio19-dev libportaudio2 ffmpeg
    else
      echo "Install these packages manually if needed: python3-tk, portaudio19-dev, libportaudio2, ffmpeg"
    fi
  fi
fi

"$VENV/bin/python" "$ROOT/launcher.py"
