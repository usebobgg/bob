#!/bin/bash
cd "$(dirname "$0")" || exit 1

BOLD=$(tput bold 2>/dev/null); DIM=$(tput dim 2>/dev/null); RESET=$(tput sgr0 2>/dev/null)
PYTHON_PAGE="https://www.python.org/downloads/"
SETUP_LOG="logs/setup.log"

say()  { printf '%s\n' "$1"; }
step() { printf '\n%s[%s of 4]%s %s\n' "$BOLD" "$1" "$RESET" "$2"; }
note() { printf '        %s%s%s\n' "$DIM" "$1" "$RESET"; }
stop() { printf '\n%s\n' "$1"; read -r -p "Press Enter to close this window. "; exit 1; }

clear
say "${BOLD}Bob - TikTok Antibot${RESET}"
say ""
say "This window sets Bob up and then starts it. Here is everything it does:"
say ""
say "  1. Checks that Python 3.11 or newer is on this computer."
say "  2. Makes a private folder called .venv inside this folder. Bob's parts go there,"
say "     so nothing else on your computer is changed."
say "  3. Downloads one library, curl_cffi, from pypi.org (the official Python library site)."
say "     It lets Bob talk to TikTok the way a normal browser does."
say "  4. Starts Bob and opens it in your browser. The address starts with http://127.0.0.1,"
say "     which means this computer. Bob is not on the internet and nobody else can open it."
say ""
say "Bob only ever connects to tiktok.com. Your login stays in this folder."
say "To remove Bob completely, delete this folder. The code is open: github.com/usebobgg/bob"

step 1 "Looking for Python"
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    PYTHON=$(command -v "$candidate")
    break
  fi
done

if [ -z "$PYTHON" ]; then
  note "Python 3.11 or newer was not found."

  if command -v brew >/dev/null 2>&1; then
    read -r -p "        Install it now with Homebrew? This runs: brew install python@3.12  [y/N] " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
      brew install python@3.12 || stop "Homebrew could not install Python. Install it from $PYTHON_PAGE and open this file again."
      PYTHON=$(command -v python3.12)
    fi
  fi

  if [ -z "$PYTHON" ]; then
    read -r -p "        Open the official Python download page in your browser? [Y/n] " answer
    [[ "$answer" =~ ^[Nn]$ ]] || open "$PYTHON_PAGE" 2>/dev/null || xdg-open "$PYTHON_PAGE" 2>/dev/null
    stop "Install Python from $PYTHON_PAGE, then open this file again."
  fi
fi
note "Found $("$PYTHON" --version) at $PYTHON"

step 2 "Preparing Bob's private folder (.venv)"
if [ -x ".venv/bin/python" ]; then
  note "Already there from last time."
else
  "$PYTHON" -m venv .venv || stop "Could not create the .venv folder here. Check that you are allowed to write to this folder."
  note "Created."
fi

step 3 "Installing what Bob needs"
if [ -f ".venv/.installed" ] && [ ! requirements.txt -nt ".venv/.installed" ]; then
  note "Already installed."
else
  note "Downloading from pypi.org: $(grep -v '^#' requirements.txt | sed 's/[<>=].*//' | tr '\n' ' ')"
  note "This takes about a minute the first time."
  mkdir -p logs
  if .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt > "$SETUP_LOG" 2>&1; then
    touch .venv/.installed
    note "Installed."
  else
    tail -5 "$SETUP_LOG"
    stop "The download failed. Check your internet connection and open this file again. Details are in $SETUP_LOG."
  fi
fi

step 4 "Starting Bob"
note "Your browser opens in a moment. Keep this window open while you use Bob."
note "To stop Bob, close this window or press Ctrl+C."
say ""
exec .venv/bin/python app.py
