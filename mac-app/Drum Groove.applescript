-- Drum Groove: drag a recording onto the app (or double-click it to choose one).
-- It asks for the time signature, tempo, kit profile and whether to include
-- coaching, runs `groove analyze`, and opens the report. No terminal needed.
--
-- Built into an app by mac-app/build.sh, which fills in TOOL_DIR below.

property toolDir : "TOOL_DIR"
property logFile : "~/Library/Logs/DrumGroove.log"
property lastTime : "4/4"
property lastKit : ""
property lastCoach : "Timing only"

on run
	try
		set picked to choose file with prompt "Choose a drum recording to analyze:" with multiple selections allowed
	on error number -128
		return
	end try
	repeat with f in picked
		analyzeFile(f)
	end repeat
end run

on open droppedItems
	repeat with f in droppedItems
		analyzeFile(f)
	end repeat
end open

on analyzeFile(f)
	set p to POSIX path of f
	set fileName to name of (info for f)
	set isMidi to (fileName ends with ".mid" or fileName ends with ".midi")
	try
		-- Time signature
		set choices to {"4/4", "3/4", "6/8", "12/8", "Other…"}
		set ts to choose from list choices with title "Drum Groove" with prompt "Time signature of “" & fileName & "”?" default items {lastTime}
		if ts is false then return
		set ts to item 1 of ts
		if ts is "Other…" then
			set ts to text returned of (display dialog "Time signature (e.g. 5/4, 7/8):" default answer lastTime with title "Drum Groove")
		end if
		set lastTime to ts

		-- Tempo (and what the metronome counted, for x/8 meters)
		set bpm to text returned of (display dialog "Tempo you played at, in bpm." & return & return & "Played along to a song? Use the song's tempo (search “song name bpm”)." & return & "Leave blank if you don't know it." default answer "" with title "Drum Groove")
		set bpmNote to ""
		if bpm is not "" and ts ends with "/8" then
			set n to choose from list {"Dotted quarters (2 beats per bar in 6/8)", "Quarter notes", "8th notes"} with title "Drum Groove" with prompt "What did your metronome count at " & bpm & " bpm?" default items {"Quarter notes"}
			if n is false then return
			set n to item 1 of n
			if n starts with "Dotted" then
				set bpmNote to "dotted-quarter"
			else if n starts with "Quarter" then
				set bpmNote to "quarter"
			else
				set bpmNote to "eighth"
			end if
		end if

		-- Kit profile (not needed for MIDI files: e-kits say which pad was hit)
		set kit to ""
		if not isMidi then
			set kits to paragraphs of (do shell script "ls ~/.config/groove-tool/kits/ 2>/dev/null | sed -n 's/\\.json$//p'")
			set options to kits & {"None (built-in rules)"}
			if lastKit is in options then
				set pick to lastKit
			else
				set pick to item 1 of options
			end if
			set k to choose from list options with title "Drum Groove" with prompt "Which kit profile? (Use the one you taught on the same mic.)" default items {pick}
			if k is false then return
			set k to item 1 of k
			set lastKit to k
			if k does not start with "None" then set kit to k
		end if

		-- Coaching
		set coach to button returned of (display dialog "Include Claude's coaching and fill ideas?" & return & "(About 10–25¢ per take; timing analysis is free.)" buttons {"Cancel", "Timing only", "With coaching"} default button lastCoach with title "Drum Groove")
		set lastCoach to coach
	on error number -128
		return -- Cancel pressed
	end try

	-- Build the command. The API key comes from Keychain, so it's never typed or shown.
	set cmd to "cd " & quoted form of toolDir & " && export ANTHROPIC_API_KEY=\"$(security find-generic-password -a \"$USER\" -s anthropic-api-key -w 2>/dev/null)\"; "
	set cmd to cmd & ".venv/bin/python -m groove analyze " & quoted form of p & " --time " & quoted form of ts
	if bpm is not "" then set cmd to cmd & " --bpm " & quoted form of bpm
	if bpmNote is not "" then set cmd to cmd & " --bpm-note " & bpmNote
	if kit is not "" then set cmd to cmd & " --kit " & quoted form of kit
	if coach is "Timing only" then set cmd to cmd & " --no-coach"
	set cmd to cmd & " > " & logFile & " 2>&1"

	display notification "Analyzing " & fileName & "… the report opens when it's ready." with title "Drum Groove"
	try
		do shell script cmd
	on error
		set reportMade to (do shell script "grep -c '^Report:' " & logFile & " || true") is not "0"
		if reportMade then
			set why to do shell script "grep -m1 'Coaching failed' " & logFile & " || echo 'Coaching did not work this time.'"
			display dialog "Your timing report for “" & fileName & "” is ready, but the coaching didn't work:" & return & return & why buttons {"OK"} default button "OK" with title "Drum Groove"
		else
			set tailText to do shell script "tail -n 6 " & logFile & " 2>/dev/null || true"
			display dialog "Couldn't analyze “" & fileName & "”." & return & return & tailText buttons {"OK"} default button "OK" with title "Drum Groove" with icon caution
		end if
	end try
end analyzeFile
