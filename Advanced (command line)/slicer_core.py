"""
slicer_core.py
Core engine for cutting a video into overlapping parts and (optionally)
burning subtitles into it first. No third-party packages required -
only a local ffmpeg / ffprobe installation.

This module is intentionally UI-agnostic: both the CLI (video_slicer.py)
and the GUI (video_slicer_gui.py) import and drive it. All long-running
work reports progress through a `log(str)` callback so a caller can print
to a terminal or append to a GUI text box.
"""

import glob
import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Callable, List, Optional

LogFn = Callable[[str], None]


def default_log(msg: str) -> None:
    print(msg, flush=True)


class SlicerError(Exception):
    """Raised for any user-facing / expected failure (bad input, missing
    ffmpeg, invalid options, ffmpeg failure, etc.)."""


# --------------------------------------------------------------------------
# Environment / probing helpers
# --------------------------------------------------------------------------

def _augment_windows_path_for_ffmpeg() -> None:
    """On Windows, a freshly winget-installed ffmpeg is a well-documented
    source of confusion: winget often registers PATH entries that don't
    actually resolve (see e.g. microsoft/winget-pkgs#120360), and even when
    it works, a Python process started from an already-open window won't
    see a PATH updated after that window opened. Rather than make the user
    sign out and back in, look in the well-known install locations and add
    them to THIS process's PATH if ffmpeg turns up there. No-op elsewhere.
    """
    if platform.system() != "Windows" or shutil.which("ffmpeg"):
        return

    candidates = []
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    for base in (
        os.path.join(local_app_data, "Microsoft", "WinGet", "Packages"),
        os.path.join(program_files, "WinGet", "Packages"),
    ):
        if base and os.path.isdir(base):
            candidates += glob.glob(os.path.join(base, "Gyan.FFmpeg*", "**", "bin", "ffmpeg.exe"), recursive=True)
    candidates += glob.glob(r"C:\ffmpeg\bin\ffmpeg.exe")
    candidates += glob.glob(os.path.join(program_files, "ffmpeg", "bin", "ffmpeg.exe"))

    for exe_path in candidates:
        bin_dir = os.path.dirname(exe_path)
        if os.path.isfile(os.path.join(bin_dir, "ffprobe.exe")):
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
            return


def check_ffmpeg_available() -> None:
    _augment_windows_path_for_ffmpeg()
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        raise SlicerError(
            "Could not find " + " and ".join(missing) + " on your system PATH.\n"
            "This tool needs ffmpeg installed locally. Install it with:\n"
            "  Windows (winget): winget install ffmpeg\n"
            "  macOS (Homebrew): brew install ffmpeg\n"
            "  Ubuntu/Debian:    sudo apt install ffmpeg\n"
            "Then re-run this program."
        )


def get_duration_seconds(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise SlicerError(f"Could not read video info from '{path}'. Is it a valid video file?\n{e.stderr}")
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise SlicerError(f"Could not determine duration of '{path}'.")


def get_video_codec(path: str) -> Optional[str]:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True)
    codec = out.stdout.strip()
    return codec or None


# --------------------------------------------------------------------------
# Time / segment math
# --------------------------------------------------------------------------

def parse_time_to_seconds(value: str) -> float:
    """Accepts plain seconds ('90', '12.5') or 'HH:MM:SS(.ms)' / 'MM:SS'."""
    value = value.strip()
    if re.fullmatch(r"\d+(\.\d+)?", value):
        return float(value)
    parts = value.split(":")
    if len(parts) not in (2, 3):
        raise SlicerError(f"Could not parse time value '{value}'. Use seconds (e.g. 90) or HH:MM:SS.")
    parts = [float(p) for p in parts]
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


def format_seconds(t: float) -> str:
    """HH:MM:SS.mmm, used for ffmpeg args."""
    if t < 0:
        t = 0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


@dataclass
class Segment:
    index: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def compute_segments(
    total_duration: float,
    length: float,
    overlap: float,
    min_last_segment: float = 1.0,
) -> List[Segment]:
    if length <= 0:
        raise SlicerError("Segment length must be greater than 0.")
    if overlap < 0:
        raise SlicerError("Overlap cannot be negative.")
    if overlap >= length:
        raise SlicerError("Overlap must be smaller than the segment length, "
                           "otherwise segments never move forward.")
    if total_duration <= 0:
        raise SlicerError("Video duration must be greater than 0.")

    step = length - overlap
    segments: List[Segment] = []
    start = 0.0
    idx = 1
    while start < total_duration - 1e-6:
        end = min(start + length, total_duration)
        segments.append(Segment(idx, start, end))
        if end >= total_duration - 1e-6:
            break
        start += step
        idx += 1

    # If the final segment is a tiny sliver (shorter than min_last_segment),
    # merge it into the previous one instead of shipping a near-empty clip.
    if len(segments) >= 2 and segments[-1].duration < min_last_segment:
        tail = segments.pop()
        segments[-1] = Segment(segments[-1].index, segments[-1].start, tail.end)

    return segments


# --------------------------------------------------------------------------
# Subtitle path escaping (ffmpeg's `subtitles` filter treats ':' and '\'
# specially, which bites Windows paths like C:\Users\... in particular)
# --------------------------------------------------------------------------

def escape_subtitles_path(path: str) -> str:
    p = os.path.abspath(path)
    p = p.replace("\\", "\\\\")
    p = p.replace(":", "\\:")
    p = p.replace("'", "\\'")
    return p


# --------------------------------------------------------------------------
# Running ffmpeg with live log streaming
# --------------------------------------------------------------------------

def run_ffmpeg(cmd: List[str], log: LogFn) -> None:
    log("$ " + " ".join(cmd))
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, universal_newlines=True,
    )
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip()
        if line:
            log(line)
    process.wait()
    if process.returncode != 0:
        raise SlicerError(f"ffmpeg failed (exit code {process.returncode}). See log above for details.")


# --------------------------------------------------------------------------
# High level operations
# --------------------------------------------------------------------------

@dataclass
class SliceOptions:
    input_path: str
    output_dir: str
    length: float
    overlap: float = 0.0
    subtitles_path: Optional[str] = None
    subtitle_style: Optional[str] = None       # e.g. "FontSize=28,PrimaryColour=&H00FFFF&"
    fast_copy: bool = False                    # opt-in: stream-copy cuts (fast, but boundaries
                                                # snap to the nearest existing keyframe in the
                                                # source - can drift by seconds on long-GOP video).
                                                # Default is a re-encode per segment, which is
                                                # slower but always lands on the exact second.
    prefix: str = "part"
    keep_intermediate: bool = False
    crf: int = 18
    preset: str = "fast"


def burn_subtitles_full_video(
    input_path: str,
    subtitles_path: str,
    out_path: str,
    force_keyframe_times: List[float],
    log: LogFn,
    subtitle_style: Optional[str] = None,
    crf: int = 18,
    preset: str = "fast",
) -> None:
    """Burns subtitles into the ENTIRE source video in a single pass, and
    forces a keyframe at every future segment boundary. Doing this once,
    up front, means:
      1. Subtitle timing is guaranteed correct (no seek-related timestamp
         ambiguity, since we never seek here - just full decode/encode).
      2. Every later per-segment cut lands exactly on a keyframe, so the
         segment extraction step can use fast stream copy and still get
         frame-exact boundaries.
    """
    escaped = escape_subtitles_path(subtitles_path)
    vf = f"subtitles='{escaped}'"
    if subtitle_style:
        vf += f":force_style='{subtitle_style}'"

    kf_arg = ",".join(f"{t:.3f}" for t in force_keyframe_times) if force_keyframe_times else "0"

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", vf,
        "-force_key_frames", kf_arg,
        "-c:v", "libx264", "-crf", str(crf), "-preset", preset,
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        out_path,
    ]
    log("Burning subtitles into the full video (one pass)... this can take a while for long videos.")
    run_ffmpeg(cmd, log)


def extract_segment(
    source_path: str,
    segment: Segment,
    out_path: str,
    use_copy: bool,
    source_codec: Optional[str],
    crf: int = 18,
    preset: str = "fast",
    log: LogFn = default_log,
) -> None:
    cmd = ["ffmpeg", "-y", "-ss", format_seconds(segment.start), "-i", source_path,
           "-t", format_seconds(segment.duration)]

    if use_copy:
        cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        # Apple players are picky about HEVC-in-MP4 without this tag.
        if source_codec in ("hevc", "h265"):
            cmd += ["-tag:v", "hvc1"]
    else:
        cmd += ["-c:v", "libx264", "-crf", str(crf), "-preset", preset, "-c:a", "aac"]

    cmd += [out_path]
    log(f"Extracting part {segment.index}: {format_seconds(segment.start)} -> {format_seconds(segment.end)} "
        f"({segment.duration:.2f}s)")
    run_ffmpeg(cmd, log)


def run_pipeline(opts: SliceOptions, log: LogFn = default_log) -> List[str]:
    """Runs the full pipeline described by `opts`. Returns the list of
    output file paths that were created, in order."""

    check_ffmpeg_available()

    if not os.path.isfile(opts.input_path):
        raise SlicerError(f"Input video not found: {opts.input_path}")
    if opts.subtitles_path and not os.path.isfile(opts.subtitles_path):
        raise SlicerError(f"Subtitles file not found: {opts.subtitles_path}")

    os.makedirs(opts.output_dir, exist_ok=True)

    duration = get_duration_seconds(opts.input_path)
    log(f"Source duration: {duration:.2f}s")

    segments = compute_segments(duration, opts.length, opts.overlap)
    log(f"Planned {len(segments)} part(s) "
        f"(length={opts.length}s, overlap={opts.overlap}s):")
    for s in segments:
        log(f"  part {s.index}: {format_seconds(s.start)} -> {format_seconds(s.end)} ({s.duration:.2f}s)")

    _, ext = os.path.splitext(opts.input_path)
    ext = ext if ext else ".mp4"

    intermediate_path = None
    source_for_slicing = opts.input_path
    use_copy = opts.fast_copy
    source_codec = get_video_codec(opts.input_path)
    out_ext = ext

    if use_copy and not opts.subtitles_path:
        log("Fast mode: cuts will snap to the nearest existing keyframe in your source video. "
            "If your source has widely-spaced keyframes, part boundaries and overlap length "
            "can drift from what you requested. Omit --fast for exact, re-encoded cuts.")

    try:
        if opts.subtitles_path:
            # Burn once into the whole video; force keyframes at every
            # segment start so the later cuts (stream copy) are exact.
            boundary_times = sorted({s.start for s in segments} | {s.end for s in segments})
            fd, intermediate_path = tempfile.mkstemp(suffix=".mp4", prefix="_subtitled_")
            os.close(fd)
            burn_subtitles_full_video(
                opts.input_path, opts.subtitles_path, intermediate_path,
                boundary_times, log,
                subtitle_style=opts.subtitle_style,
                crf=opts.crf, preset=opts.preset,
            )
            source_for_slicing = intermediate_path
            source_codec = "h264"  # re-encoded above
            use_copy = True        # keyframes were forced, safe + fast to copy
            out_ext = ".mp4"

        out_paths = []
        pad = max(2, len(str(len(segments))))
        for seg in segments:
            out_name = f"{opts.prefix}_{seg.index:0{pad}d}{out_ext}"
            out_path = os.path.join(opts.output_dir, out_name)
            extract_segment(
                source_for_slicing, seg, out_path,
                use_copy=use_copy, source_codec=source_codec,
                crf=opts.crf, preset=opts.preset, log=log,
            )
            out_paths.append(out_path)

        log(f"Done. {len(out_paths)} file(s) written to: {opts.output_dir}")
        return out_paths

    finally:
        if intermediate_path and os.path.exists(intermediate_path):
            if opts.keep_intermediate:
                kept = os.path.join(opts.output_dir, f"{opts.prefix}_full_with_subtitles.mp4")
                shutil.move(intermediate_path, kept)
                log(f"Kept intermediate subtitled video: {kept}")
            else:
                os.remove(intermediate_path)
