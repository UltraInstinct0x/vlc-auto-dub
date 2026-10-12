"""Pipeline: extract -> STT -> optional translate -> TTS -> fit -> assemble -> mux.

Fully local and content-agnostic: it processes whatever file it is handed, with
no moderation gate, no upload, and no telemetry. Provider selection decides the
backends; the defaults never touch the network beyond one-time model/voice
downloads.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile

from . import media
from .config import Config
from .errors import AutoDubError, InputError, MediaError
from .languages import normalize_code, primary_subtag
from .providers import make_stt, make_translator, make_tts
from .subtitles import Cue, write_srt
from .voices import effective_voice


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_outputs(input_path: str, output_base: str, has_video: bool) -> tuple[str, str]:
    if has_video:
        ext = os.path.splitext(input_path)[1] or ".mp4"
        media_out = f"{output_base}_dubbed{ext}"
    else:
        media_out = f"{output_base}_dubbed.wav"  # audio-only input stays audio-only
    return media_out, f"{output_base}.srt"


def run(input_path: str, output_base: str, config: Config) -> dict:
    """Run the dubbing pipeline. Returns a summary dict."""
    if not os.path.isfile(input_path):
        raise InputError(f"input file not found: {input_path}")

    media.require_binary("ffmpeg")
    media.require_binary("ffprobe")
    if not media.has_audio_stream(input_path):
        raise InputError(f"input has no audio stream: {input_path}")
    has_video = media.has_video_stream(input_path)

    output_media, output_srt = _resolve_outputs(input_path, output_base, has_video)
    if os.path.abspath(input_path) == os.path.abspath(output_media):
        raise InputError("output would overwrite the input file; choose a different --output-base")

    source_lang = normalize_code(config.source_lang) if config.source_lang else None
    target_lang = normalize_code(config.target_lang) if config.target_lang else None
    source_code = primary_subtag(source_lang) if source_lang else ""
    target_code = primary_subtag(target_lang) if target_lang else ""
    do_translate = bool(source_code and target_code and source_code != target_code)

    input_hash_before = _sha256(input_path)

    workdir = (
        output_base + ".work"
        if config.keep_workdir
        else tempfile.mkdtemp(prefix="autodub-")
    )
    os.makedirs(workdir, exist_ok=True)

    stt = make_stt(config.stt)
    translator = make_translator(config.translate) if do_translate else None

    # TTS voice follows the target language (falling back to the source language,
    # then to the provider default); an explicit --voice always wins.
    voice, voice_warning = effective_voice(config.tts, target_code or source_code)
    if config.voice:
        voice, voice_warning = config.voice, None
    tts = make_tts(config.tts, voice) if not config.subtitle_only else None

    summary: dict = {
        "input": os.path.abspath(input_path),
        "output_video": os.path.abspath(output_media),
        "output_media": os.path.abspath(output_media),
        "output_srt": os.path.abspath(output_srt),
        "has_video": has_video,
        "providers": {"stt": config.stt, "tts": None if config.subtitle_only else config.tts},
        "voice": voice,
        "translated": False,
        "warnings": [],
    }
    if voice_warning:
        summary["warnings"].append(voice_warning)

    try:
        audio = os.path.join(workdir, "audio.wav")
        media.extract_audio(input_path, audio)
        source_dur = media.duration(audio)

        raw_segments = stt.transcribe(audio, source_code or None)

        segments = []
        for seg in raw_segments:
            text = seg.text
            if do_translate and translator is not None:
                text = translator.translate(text, source_code, target_code)
            segments.append((seg.start, seg.end, text))
        summary["translated"] = do_translate and bool(segments)
        summary["segment_count"] = len(segments)

        cues = [Cue(start=s, end=e, text=t) for (s, e, t) in segments]
        write_srt(cues, output_srt)

        if config.subtitle_only:
            summary["mode"] = "subtitle-only"
            return summary
        assert tts is not None  # set whenever we are not in subtitle-only mode

        # Build the dubbed timeline.
        parts: list[str] = []
        cursor = 0.0
        for i, (start, end, text) in enumerate(segments):
            if start > cursor + 1e-3:
                non = os.path.join(workdir, f"nonspeech_{i}.wav")
                media.slice_audio(audio, cursor, start - cursor, non)
                parts.append(non)
            raw = os.path.join(workdir, f"seg_{i}.wav")
            tts.synthesize(text, raw, voice)
            fitted = os.path.join(workdir, f"fit_{i}.wav")
            media.fit_segment(raw, end - start, fitted)
            parts.append(fitted)
            cursor = end

        if cursor < source_dur - 1e-3:
            non = os.path.join(workdir, "nonspeech_tail.wav")
            media.slice_audio(audio, cursor, source_dur - cursor, non)
            parts.append(non)

        if not parts:  # no speech detected: keep the original audio
            parts.append(audio)

        dubbed = os.path.join(workdir, "dubbed.wav")
        media.concat_audio(parts, dubbed, os.path.join(workdir, "concat.txt"))

        dubbed_dur = media.duration(dubbed)
        if abs(dubbed_dur - source_dur) > config.duration_tolerance:
            summary["warnings"].append(
                f"assembled audio is {dubbed_dur - source_dur:+.2f}s off the source "
                f"(tolerance {config.duration_tolerance}s)"
            )

        if has_video:
            media.mux(input_path, dubbed, output_media)
        else:
            # audio-only input has no video stream to copy; keep the dubbed audio
            shutil.copyfile(dubbed, output_media)

        input_hash_after = _sha256(input_path)
        if input_hash_after != input_hash_before:
            raise MediaError("input file changed during processing; this must never happen")
        summary["dubbed_duration"] = round(dubbed_dur, 3)
        summary["source_duration"] = round(source_dur, 3)
        summary["mode"] = "full"
        return summary
    finally:
        if not config.keep_workdir:
            shutil.rmtree(workdir, ignore_errors=True)


__all__ = ["run", "AutoDubError"]
