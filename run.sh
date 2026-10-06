#!/bin/zsh
# Guided run: demo -> calibrate -> record -> analyze. Just follow the prompts.
# The demo and calibration only run the first time.
cd "$(dirname "$0")"
G() { .venv/bin/python -m groove "$@"; }

if [[ ! -d demo_groove ]]; then
  echo "\n=== Demo: a fake drum recording (no mic needed) ==="
  G synth demo.wav --rush 4 --snare-late 15 && G analyze demo.wav --no-coach
  read "?Press Enter to continue to recording with your kit (or Ctrl+C to stop here)... "
fi

if [[ ! -f ~/.config/groove-tool/latency.json ]]; then
  echo "\n=== Calibrate (one time only) ==="
  echo "Take your headphones OFF and turn your speakers up. Stay quiet while it clicks."
  read "?Press Enter when ready... "
  G calibrate
fi

name="take_$(date +%Y-%m-%d_%H%M)"
echo "\n=== Record ($name) ==="
read "bpm?Tempo to play at (press Enter for 80): "; bpm=${bpm:-80}
echo "Put your headphones ON. You'll hear 4 count-in clicks, then play 8 bars."
read "?Press Enter to start recording... "
G record $name.wav --bpm $bpm --bars 8

echo "\n=== Analyze ==="
if [[ -z "$ANTHROPIC_API_KEY" ]]; then
  read "key?Paste your Anthropic API key for coaching (or press Enter to skip): "
  [[ -n "$key" ]] && export ANTHROPIC_API_KEY=$key
fi
if [[ -n "$ANTHROPIC_API_KEY" ]]; then
  G analyze $name.wav --goal "learning drums to join a band"
else
  G analyze $name.wav --no-coach
fi
