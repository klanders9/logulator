#!/usr/bin/env bash
# Installs GNOME desktop integration (icon + .desktop file) for logulator.
# Run this once after cloning; re-run if you move the repo.
# Works whether you run from source or have pip-installed inside a venv.
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

# Prefer the venv's installed console script; fall back to running main.py directly.
if [ -f "$REPO_DIR/.venv/bin/logulator" ]; then
    EXEC_CMD="$REPO_DIR/.venv/bin/logulator"
elif [ -f "$REPO_DIR/.venv/bin/python" ]; then
    EXEC_CMD="$REPO_DIR/.venv/bin/python $REPO_DIR/main.py"
else
    EXEC_CMD="python3 $REPO_DIR/main.py"
fi

mkdir -p ~/.local/share/applications
mkdir -p ~/.local/share/icons/hicolor/256x256/apps

cat > ~/.local/share/applications/logulator.desktop << EOF
[Desktop Entry]
Type=Application
Name=logulator
Comment=A cross-platform serial log viewer and analyzer.
Exec=$EXEC_CMD
Icon=$REPO_DIR/icon.png
StartupWMClass=logulator
Categories=Development;
Terminal=false
EOF

cp "$REPO_DIR/icon.png" ~/.local/share/icons/hicolor/256x256/apps/logulator.png

if command -v update-desktop-database &>/dev/null; then
    update-desktop-database ~/.local/share/applications
fi

echo "Installed:"
echo "  ~/.local/share/applications/logulator.desktop  (Exec=$EXEC_CMD)"
echo "  ~/.local/share/icons/hicolor/256x256/apps/logulator.png"
