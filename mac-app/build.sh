#!/bin/zsh
# Build "Drum Groove.app" from the AppleScript and install it in ~/Applications.
# Run again after moving the repo, so the app points at the right folder.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
tool="$(dirname "$here")"
src="$(mktemp -t drumgroove).applescript"
sed "s|TOOL_DIR|$tool|" "$here/Drum Groove.applescript" > "$src"
mkdir -p ~/Applications
rm -rf ~/Applications/"Drum Groove.app"
osacompile -o ~/Applications/"Drum Groove.app" "$src"
rm -f "$src"
echo "Installed ~/Applications/Drum Groove.app (uses $tool)"
