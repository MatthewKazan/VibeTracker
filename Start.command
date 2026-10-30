#!/bin/zsh
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null; then
  echo 'Python 3 is required. Install Python 3 from python.org.'
  read
  exit 1
fi
(sleep 1; open http://127.0.0.1:8765) &
python3 app.py
