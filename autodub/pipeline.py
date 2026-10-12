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
from .errors import AutoDubError, InputError, MediaError, ProviderError
from .languages import normalize_code, primary_subtag, track_language
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


def _replace_in_place(input_path: str, audio: str | None, srt: str | None, language: str,
                      subtitle_codec: str, input_hash: str, workdir: str) -> None:
    """Add the tracks to ``input_path`` atomically.

    The new file is written next to the original (same filesystem, so the final
    rename is atomic), checked, and only then renamed over the original. Any
    failure before the rename leaves the original byte-for-byte untouched.
    """
    folder, name = os.path.split(os.path.abspath(input_path))
    stem, ext = os.path.splitext(name)
    fd, tmp = tempfile.mkstemp(prefix=f".{stem}.autodub-", suffix=ext, dir=folder)
    os.close(fd)
    try:
        expected = media.mux_tracks(input_path, tmp, audio=audio, srt=srt,
                                    language=language, subtitle_codec=subtitle_codec)
        _verify_rewrite(input_path, tmp, expected, language, audio is not None, srt is not None)
        if _sha256(input_path) != input_hash:
            raise MediaError("input file changed during processing; not replacing it")
        shutil.copymode(input_path, tmp)
        os.replace(tmp, input_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _verify_rewrite(original: str, rewritten: str, expected: dict, language: str,
                    added_audio: bool, added_subs: bool) -> None:
    streams = media.probe_streams(rewritten)
    counts: dict[str, int] = {}
    for s in streams:
        kind = s.get("codec_type", "")
        counts[kind] = counts.get(kind, 0) + 1
    if counts != expected:
        raise MediaError(f"rewritten file has streams {counts}, expected {expected}; "
                         f"the original was left untouched")
    ours = [s for s in streams if media.is_autodub_stream(s)
            and s.get("tags", {}).get("language") == language]
    want = ({"subtitle"} if added_subs else set()) | ({"audio"} if added_audio else set())
    if {s.get("codec_type") for s in ours} != want:
        raise MediaError("rewritten file is missing the labelled AutoDub tracks; "
                         "the original was left untouched")
    if abs(media.duration(rewritten) - media.duration(original)) > 1.0:
        raise MediaError("rewritten file duration differs from the original; "
                         "the original was left untouched")


def run(input_path: str, output_base: str | None, config: Config) -> dict:
    """Run the dubbing pipeline. Returns a summary dict."""
    if not os.path.isfile(input_path):
        raise InputError(f"input file not found: {input_path}")

    media.require_binary("ffmpeg")
    media.require_binary("ffprobe")
    if not media.has_audio_stream(input_path):
        raise InputError(f"input has no audio stream: {input_path}")
    has_video = media.has_video_stream(input_path)

    subtitle_codec = None
    audio_index = None
    if config.in_place:
        ext = os.path.splitext(input_path)[1].lower()
        subtitle_codec = media.IN_PLACE_SUBTITLE_CODEC.get(ext)
        if subtitle_codec is None:
            supported = ", ".join(sorted(media.IN_PLACE_SUBTITLE_CODEC))
            raise InputError(f"--in-place supports {supported} files, not {ext or 'no extension'!r}")
        if not os.access(os.path.dirname(os.path.abspath(input_path)), os.W_OK):
            raise InputError(f"--in-place needs write access to the folder of {input_path}")
        # Transcribe the original speech, never an AutoDub track from an earlier run.
        audio_streams = [s for s in media.probe_streams(input_path) if s.get("codec_type") == "audio"]
        originals = [i for i, s in enumerate(audio_streams) if not media.is_autodub_stream(s)]
        audio_index = originals[0] if originals else None
        output_media, output_srt = os.path.abspath(input_path), None
    else:
        if not output_base:
            raise InputError("--output-base is required unless --in-place is used")
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
        (output_base or os.path.splitext(input_path)[0]) + ".work"
        if config.keep_workdir
        else tempfile.mkdtemp(prefix="autodub-")
    )
    os.makedirs(workdir, exist_ok=True)

    if config.subtitle_only and config.dub_only:
        raise InputError("--subtitle-only and --dub-only cannot be combined")

    stt = make_stt(config.stt)

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
        "output_srt": os.path.abspath(output_srt) if output_srt else None,
        "in_place": config.in_place,
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
        media.extract_audio(input_path, audio, audio_index=audio_index)
        source_dur = media.duration(audio)

        raw_segments = stt.transcribe(audio, source_code or None)
        if not source_code and target_code:
            # Source left on auto: translate from whatever the STT detected.
            detected = getattr(stt, "detected_language", None)
            if detected:
                source_code = primary_subtag(detected)
                source_lang = source_code
                summary["detected_language"] = source_code
            else:
                summary["warnings"].append(
                    "source language could not be detected; not translating")
            do_translate = bool(source_code and source_code != target_code)
        translator = make_translator(config.translate) if do_translate else None

        segments = []
        unchanged = 0
        for seg in raw_segments:
            text = seg.text
            if do_translate and translator is not None:
                translated = translator.translate(text, source_code, target_code)
                if translated.strip() == text.strip():
                    unchanged += 1
                text = translated
            segments.append((seg.start, seg.end, text))

        # Guard against the dangerous silent failure: a "translation" step that
        # returns the source text verbatim for every segment means the pack is
        # not actually loaded, and the dub would be source-language audio.
        if do_translate and segments and unchanged == len(segments):
            raise ProviderError(
                f"translation {source_code!r}->{target_code!r} returned the source text "
                f"unchanged for every segment; refusing to label source-language audio as "
                f"translated. Install/verify the pack: "
                f"argospm install translate-{source_code}_{target_code}"
            )

        summary["translated"] = do_translate and bool(segments)
        summary["segment_count"] = len(segments)

        cues = [Cue(start=s, end=e, text=t) for (s, e, t) in segments]
        if config.dub_only:
            srt_path = None
            summary["output_srt"] = None
        else:
            srt_path = output_srt or os.path.join(workdir, "subtitles.srt")
            write_srt(cues, srt_path)
        language = track_language(target_lang or source_lang)
        summary["track_language"] = language

        if config.subtitle_only:
            if config.in_place:
                _replace_in_place(input_path, None, srt_path, language, subtitle_codec,
                                  input_hash_before, workdir)
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

        if config.in_place:
            _replace_in_place(input_path, dubbed, srt_path, language, subtitle_codec,
                              input_hash_before, workdir)
            summary["dubbed_duration"] = round(dubbed_dur, 3)
            summary["source_duration"] = round(source_dur, 3)
            summary["mode"] = "full"
            return summary
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
