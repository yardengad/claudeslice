#!/usr/bin/env python3
"""
video_slicer.py - Slice a local video into overlapping parts, optionally
burning in subtitles first.

Requires: Python 3.8+ and a local ffmpeg/ffprobe installation on your PATH.
No other dependencies.

EXAMPLES
--------
Split a video into 5-minute parts with a 10-second overlap between parts:
    python3 video_slicer.py -i myvideo.mp4 -l 300 -ov 10 -o parts/

Same, but also burn in subtitles from an SRT file:
    python3 video_slicer.py -i myvideo.mp4 -l 300 -ov 10 -s captions.srt -o parts/

Lengths/overlap can also be given as MM:SS or HH:MM:SS:
    python3 video_slicer.py -i myvideo.mp4 -l 2:30 -ov 0:05 -o parts/

Style the burned-in subtitles (ASS "force_style" syntax):
    python3 video_slicer.py -i myvideo.mp4 -l 60 -s captions.srt \\
        --sub-style "FontSize=28,PrimaryColour=&H00FFFF&,Outline=2" -o parts/

Prioritize speed over exact-second accuracy (only affects runs with no
subtitles; boundaries then snap to the source's existing keyframes):
    python3 video_slicer.py -i myvideo.mp4 -l 60 -ov 5 --fast -o parts/
"""

import argparse
import sys

from slicer_core import (
    SliceOptions, SlicerError, default_log, parse_time_to_seconds, run_pipeline,
)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Slice a video into overlapping parts, optionally burning in subtitles.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("-i", "--input", required=True, help="Path to the input video (mp4, mov, mkv, HEVC/H.265, etc.)")
    p.add_argument("-o", "--output-dir", default="output_parts", help="Folder to write the parts into (default: ./output_parts)")
    p.add_argument("-l", "--length", required=True, help="Length of each part. Seconds or MM:SS / HH:MM:SS, e.g. 60 or 1:30")
    p.add_argument("-ov", "--overlap", default="0", help="Overlap between consecutive parts. Same format as --length. Default: 0")
    p.add_argument("-s", "--subtitles", default=None, help="Optional path to an SRT/ASS/VTT subtitle file to burn into the video")
    p.add_argument("--sub-style", default=None, help="Optional ffmpeg 'force_style' string for burned-in subtitles, e.g. \"FontSize=28,PrimaryColour=&H00FFFF&\"")
    p.add_argument("--fast", action="store_true", help="Use fast stream-copy cutting instead of re-encoding. Faster, but part boundaries snap to the nearest existing keyframe in the source and can drift from the exact times you requested. Ignored when --subtitles is used (that path is always fast AND exact).")
    p.add_argument("--prefix", default="part", help="Filename prefix for output parts (default: 'part' -> part_01.mp4, part_02.mp4, ...)")
    p.add_argument("--crf", type=int, default=18, help="x264 quality when re-encoding is needed (lower = higher quality/larger file). Default: 18")
    p.add_argument("--encode-speed", default="fast", choices=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"], help="x264 encoding speed/efficiency trade-off when re-encoding is needed. Default: fast")
    p.add_argument("--keep-full-subtitled-video", action="store_true", help="If burning subtitles, also keep the full-length subtitled video (before slicing) in the output folder")
    return p


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)

    try:
        length = parse_time_to_seconds(args.length)
        overlap = parse_time_to_seconds(args.overlap)

        opts = SliceOptions(
            input_path=args.input,
            output_dir=args.output_dir,
            length=length,
            overlap=overlap,
            subtitles_path=args.subtitles,
            subtitle_style=args.sub_style,
            fast_copy=args.fast,
            prefix=args.prefix,
            keep_intermediate=args.keep_full_subtitled_video,
            crf=args.crf,
            preset=args.encode_speed,
        )
        run_pipeline(opts, log=default_log)
        return 0

    except SlicerError as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
