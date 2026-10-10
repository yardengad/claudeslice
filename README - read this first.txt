VIDEO SLICER — for Windows
=============================

What it does: cuts a video into parts of a length you choose, with an
overlap you choose between parts, and can burn in subtitles (SRT/ASS/VTT)
first. Everything runs on your PC — nothing is uploaded anywhere.

ONE-TIME SETUP (only needed the first time)
--------------------------------------------
This app needs a free tool called ffmpeg to actually process video, which
doesn't come with Windows. Installing it is one step:

1. Double-click "Install ffmpeg (run once).bat".
2. Windows may warn you the first time you run any new .bat/.exe you
   downloaded — see "IF WINDOWS BLOCKS IT" below.
3. It installs ffmpeg using winget (Windows' built-in app installer). If
   winget itself isn't set up yet, this will open its Microsoft Store page
   for you — install it there, then re-run this file.
4. When it says "Done!", close the window.

You also need Python 3 installed (the app is written in Python). If you
don't already have it, get it free from python.org/downloads/windows —
during setup, tick "Add python.exe to PATH". If Python isn't found,
"Video Slicer.exe" will tell you and offer to open that download page for
you directly, so you don't strictly need to do this ahead of time.

You only need to do this setup once. After that, just open the app.

USING THE APP
--------------
Double-click "Video Slicer.exe". Fill in:
- Input video — the file you want to slice
- Output folder — where the parts get saved
- Part length / overlap — in seconds, or MM:SS / HH:MM:SS
- Subtitles (optional) — an SRT/ASS/VTT file to burn into the video

Click "Slice Video". Progress shows in the log box at the bottom.

IF WINDOWS BLOCKS IT ("Windows protected your PC")
------------------------------------------------------
Since these files weren't downloaded from the Microsoft Store, Windows may
warn you the first time you run each one, by design - either a small
"Open File - Security Warning" box (just click "Run"), or the fuller blue
"Windows protected your PC" screen. For the blue screen:

1. Click "More info".
2. Click "Run anyway".

You may need to do this once for "Install ffmpeg (run once).bat" and once
for "Video Slicer.exe" — after that, they open normally.

TROUBLESHOOTING
-----------------
- The app should walk you through anything missing (Python, ffmpeg) with
  its own pop-up messages rather than failing silently — read those if it
  doesn't open.
- Clicked "Video Slicer.exe" and genuinely nothing happened — no window,
  no message? A file called "VideoSlicer_debug_log.txt" appears next to
  "Video Slicer.exe" after every run. Open it with Notepad — it holds the
  exact error from Python, if there was one (most often a missing piece
  of the Python install, like tcl/tk). If that file is empty or also
  missing, double-check you clicked "Video Slicer.exe" itself and not a
  shortcut, and that your antivirus didn't quarantine it (check its
  quarantine/history list).
- Just installed ffmpeg and the app still can't find it? Video Slicer
  automatically checks ffmpeg's usual install folder on its own, so this
  is rare — if it still happens, sign out and back in once (or restart),
  which refreshes Windows so newly installed programs are found.
- Prefer the command line? There's a standalone version in the
  "Advanced (command line)" folder — run it with --help for usage (needs
  Python; open a Command Prompt in that folder and run:
  python video_slicer.py --help). Running the GUI this way also shows
  errors directly: open Command Prompt in this folder and run
  python app\video_slicer_gui.py

Fast mode note: by default, cuts land on the exact second you asked for
(a quick re-encode). There's also a "fast" checkbox that skips re-encoding
for speed, at the cost of cut points possibly drifting by a couple of
seconds on videos with widely-spaced keyframes — leave it off unless you
know you want that trade-off.
