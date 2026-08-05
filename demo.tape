# demo.tape — source for the README demo GIF (docs/assets/demo.gif).
#
# Recorded manually, not in CI: the run hits a live model with a real
# ingested project, so it needs an API key, network, and spends tokens.
#
# To record (from the repo root, with an ingested project in ./indialaw):
#   brew install vhs
#   vhs demo.tape

Output docs/assets/demo.gif

Set FontSize 15
Set Width 1100
# 820, not 750: the full exchange (banner through answer) has to land in the
# last frame, and 750 clips the top banner line — the version string.
Set Height 820
Set Padding 16
Set TypingSpeed 40ms
Set WaitTimeout 300s

# Enter the project quietly; the recording starts at a clean prompt.
# (Hide only pauses frame capture — clear the screen before Show.)
Hide
Type "cd indialaw"
Enter
Wait
Type "clear"
Enter
Show

Sleep 1s
Type "uv run reigner chat"
Sleep 500ms
Enter

# Wait for the REPL composer to come up (the "› " input prompt).
Wait+Screen@60s /›/
Sleep 1s

# Bound the answer length: the whole exchange has to fit one screen, banner
# included. An open-ended "answer briefly" scrolls the banner and the cost
# line off the top on a verbose model.
Type "What are the main concerns about the rule of law? Answer in 4 short bullets."
Sleep 500ms
Enter

# The turn ends with the Sources block and the Answer panel (flushed
# together). Wait on "Sources" — "Answer" would false-match the question
# text ("Answer briefly.") the moment it's typed. Then hold so the
# citations are readable.
Wait+Screen@300s /Sources/
Sleep 8s

# Leave the REPL off-camera so the last frame is the answer, not the exit.
Hide
Type "/exit"
Enter
