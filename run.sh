#!/bin/zsh
# Guided run: demo -> calibrate -> record -> analyze. Just follow the prompts.
# The demo and calibration only run the first time.
cd "$(dirname "$0")"
G() { .venv/bin/python -m groove "$@"; }

if [[ ! -d takes/demo ]]; then
  echo "\n=== Demo: a fake drum recording (no mic needed) ==="
  G synth demo --rush 4 --snare-late 15 && G analyze demo --no-coach
  read "?Press Enter to continue to recording with your kit (or Ctrl+C to stop here)... "
fi

if [[ ! -f ~/.config/groove-tool/latency.json ]]; then
  echo "\n=== Calibrate (one time only) ==="
  echo "Take your headphones OFF and turn your speakers up. Stay quiet while it clicks."
  read "?Press Enter when ready... "
  G calibrate
fi

name="$(date +%Y-%m-%d_%H%M)"
echo "\n=== Record ($name) ==="
read "ts?Time signature, e.g. 4/4, 3/4, 6/8 (press Enter for 4/4): "; ts=${ts:-4/4}
if [[ "$ts" == */8 ]]; then
  read "bpm?Tempo in dotted quarters, two per bar in 6/8 (press Enter for 60): "; bpm=${bpm:-60}
else
  read "bpm?Tempo to play at (press Enter for 80): "; bpm=${bpm:-80}
fi
echo "Put your headphones ON. You'll hear a 1-bar count-in, then play 8 bars."
read "?Press Enter to start recording... "
G record $name --time $ts --bpm $bpm --bars 8

echo "\n=== Analyze ==="
if [[ -z "$ANTHROPIC_API_KEY" ]]; then
  read "key?Paste your Anthropic API key for coaching (or press Enter to skip): "
  [[ -n "$key" ]] && export ANTHROPIC_API_KEY=$key
fi
if [[ -n "$ANTHROPIC_API_KEY" ]]; then
  G analyze $name --goal "learning drums to join a band"
else
  G analyze $name --no-coach
fi
