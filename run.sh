#!/bin/zsh
# Guided run: pick how to get your playing in, then follow the prompts.
# One-time steps (demo, calibration, kit teaching) are skipped once done.
cd "$(dirname "$0")"
G() { .venv/bin/python -m groove "$@"; }

if [[ ! -d takes/example ]]; then
  echo "\n=== Example: a fake drum recording (no mic needed) ==="
  G synth example --rush 4 --snare-late 15 && G analyze example --no-coach --no-open
fi

echo "\nHow do you want to do this take?"
echo "  1) Record now with this computer's mic"
echo "  2) Analyze a recording file (e.g. a Voice Memo from your phone)"
echo "  3) Record an e-kit connected by USB (MIDI)"
read "mode?Choose 1, 2 or 3 (Enter for 1): "; mode=${mode:-1}

read "ts?Time signature, e.g. 4/4, 3/4, 6/8 (Enter for 4/4): "; ts=${ts:-4/4}
if [[ "$ts" == */8 ]]; then
  tempo_q="Tempo in dotted quarters, two per bar in 6/8"
else
  tempo_q="Tempo"
fi

if [[ "$mode" == 2 ]]; then
  echo "\nDrag the recording from Finder into this window, then press Enter."
  read "file?File: "
  file="${file## }"; file="${file%% }"; file="${file#[\'\"]}"; file="${file%[\'\"]}"
  if [[ ! -f "$file" ]]; then echo "Couldn't find that file: $file"; exit 1; fi
  read "bpm?$tempo_q you played at, if you know it (Enter to let it work it out): "
  read "kit?Kit profile to use, e.g. phone (Enter for the default): "
  take=("$file")
  opts=(--time "$ts")
  [[ -n "$bpm" ]] && opts+=(--bpm "$bpm")
  [[ -n "$kit" ]] && opts+=(--kit "$kit")
else
  if [[ "$mode" == 1 ]]; then
    if [[ ! -f ~/.config/groove-tool/latency.json ]]; then
      echo "\n=== Calibrate (one time only) ==="
      echo "Take your headphones OFF and turn your speakers up. Stay quiet while it clicks."
      read "?Press Enter when ready... "
      G calibrate
    fi
    if [[ ! -f ~/.config/groove-tool/kits/default.json ]]; then
      echo "\n=== Teach it your kit (one time, recommended) ==="
      echo "Helps it tell kick, snare and hi-hat apart on this mic. You'll play 4 of each when asked."
      read "ans?Do it now? (y/N): "
      [[ "$ans" == [yY]* ]] && G learn-kit
    fi
  fi
  read "bpm?$tempo_q (Enter for $([[ "$ts" == */8 ]] && echo 60 || echo 80)): "
  bpm=${bpm:-$([[ "$ts" == */8 ]] && echo 60 || echo 80)}
  read "name?Name this take (Enter for today's date and time): "
  name=${name:-$(date +%Y-%m-%d_%H%M)}
  name=${name// /-}
  if [[ -d "takes/$name" ]]; then
    read "ans?A take called '$name' already exists. Replace it? (y/N): "
    [[ "$ans" == [yY]* ]] || exit 1
    rm -rf "takes/$name"
  fi
  echo "\n=== Record ($name) ==="
  if [[ "$mode" == 3 ]]; then
    echo "The click can play out loud (no mic is used). 1-bar count-in, then play 8 bars."
    src=(--midi)
  else
    echo "Put headphones on for the click. 1-bar count-in, then play 8 bars."
    src=()
  fi
  read "?Press Enter to start recording... "
  G record $name --time $ts --bpm $bpm --bars 8 $src || exit 1
  take=("$name")
  opts=()
fi

echo "\n=== Analyze ==="
if [[ -z "$ANTHROPIC_API_KEY" ]]; then
  read -s "key?Paste your Anthropic API key for coaching, hidden (or press Enter to skip): "; echo
  [[ -n "$key" ]] && export ANTHROPIC_API_KEY=$key
fi
if [[ -n "$ANTHROPIC_API_KEY" ]]; then
  G analyze "${take[@]}" "${opts[@]}" --goal "learning drums to join a band"
else
  G analyze "${take[@]}" "${opts[@]}" --no-coach
fi
