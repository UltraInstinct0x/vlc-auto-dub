#!/usr/bin/env python3
"""vlc-auto-dub: dub a video's speech into subtitles and an alternate audio track.

Pipeline: extract audio -> transcribe (STT) -> optional translate -> synthesize
speech (TTS) -> fit each clip to its time slot -> assemble -> mux.

By default the original media is never modified. With --in-place the dub and
subtitles are added to the input file as extra tracks, atomically.
"""
from __future__ import annotations

import argparse
import sys

from autodub.config import DEFAULT_STT, DEFAULT_TRANSLATE, DEFAULT_TTS, build_config
from autodub.errors import AutoDubError
from autodub.pipeline import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Dub a video's speech into subtitles and an alternate audio track.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input", help="path to the input video file "
                                      "(never modified unless --in-place)")
    parser.add_argument(
        "--output-base", default=None,
        help="output path base; writes <base>_dubbed<ext> and <base>.srt "
             "(required unless --in-place)",
    )
    parser.add_argument(
        "--in-place", action="store_true",
        help="add the dub (default audio track) and subtitles as tracks inside the "
             "input file, keeping all original tracks; .mp4/.m4v/.mov/.mkv only",
    )
    parser.add_argument("--source-lang", default=None,
                        help="source language code, e.g. en (default: STT auto-detect)")
    parser.add_argument("--target-lang", default=None,
                        help="target language code; when it differs from --source-lang, "
                             "speech and subtitles are translated")
    parser.add_argument("--stt", default=None, help=f"STT provider (default: {DEFAULT_STT})")
    parser.add_argument("--translate", default=None,
                        help=f"translation provider (default: {DEFAULT_TRANSLATE})")
    parser.add_argument("--tts", default=None, help=f"TTS provider (default: {DEFAULT_TTS})")
    parser.add_argument("--voice", default=None, help="provider-specific voice name")
    parser.add_argument("--subtitle-only", action="store_true",
                        help="write only the SRT; skip TTS and muxing")
    parser.add_argument("--dub-only", action="store_true",
                        help="produce only the dubbed audio; no subtitles")
    parser.add_argument("--keep-workdir", action="store_true",
                        help="keep intermediate files at <output-base>.work")
    parser.add_argument("--config", default=None, help="path to a config file (key = value or JSON)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.in_place and not args.output_base:
        parser.error("--output-base is required unless --in-place is used")
    if args.subtitle_only and args.dub_only:
        parser.error("--subtitle-only and --dub-only cannot be combined")
    config = build_config(
        config_path=args.config,
        stt=args.stt,
        translate=args.translate,
        tts=args.tts,
        voice=args.voice,
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        subtitle_only=args.subtitle_only,
        keep_workdir=args.keep_workdir,
        in_place=args.in_place,
        dub_only=args.dub_only,
    )
    try:
        summary = run(args.input, args.output_base, config)
    except AutoDubError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"[autodub] mode: {summary['mode']}")
    print(f"[autodub] STT: {summary['providers']['stt']}"
          + (f", TTS: {summary['providers']['tts']}" if summary["providers"]["tts"] else ""))
    if summary.get("detected_language"):
        print(f"[autodub] detected source language: {summary['detected_language']}")
    print(f"[autodub] translation: {'yes' if summary['translated'] else 'no'}")
    print(f"[autodub] segments: {summary['segment_count']}")
    print(f"[autodub] voice: {summary.get('voice') or '(provider default)'}")
    if summary["in_place"]:
        if summary["mode"] == "subtitle-only":
            added = "subtitle track"
        elif args.dub_only:
            added = "dub audio track (default)"
        else:
            added = "dub audio track (default) + subtitle track"
        print(f"[autodub] in-place: added {added} "
              f"[{summary['track_language']}] to {summary['output_media']}")
    else:
        if summary["output_srt"]:
            print(f"[autodub] subtitles: {summary['output_srt']}")
        if summary["mode"] == "full":
            print(f"[autodub] media: {summary['output_media']}")
    for warning in summary["warnings"]:
        print(f"[autodub] warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
