# vlc-auto-dub

> Dub a video's speech into subtitles and an alternate audio track, locally.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Dubs a video file end to end: extract audio → transcribe (STT) → **optional
translate** → synthesize speech (TTS) → fit each clip to its time slot →
assemble → mux a new audio track. The original media is never modified.

Everything runs locally. No media is uploaded anywhere by the default
providers, and no API key is required.

## What it does

- **Transcription** with [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper)
  (local, CPU, `tiny` model by default — see *Models and downloads*).
- **Optional translation** so the dub and subtitles can target a different
  language, using [`argostranslate`](https://github.com/argosopentech/argos-translate)
  (local, offline) by default.
- **Speech synthesis** with [`piper`](https://github.com/rhasspy/piper)
  (local, CPU) or `espeak-ng` (small, no model download).
- **Time-aligned output**: each synthesized clip is fitted into its segment's
  `[start, end]` window, and non-speech audio is preserved from the source.
- **Subtitles**: writes an UTF-8 `.srt` next to the dubbed video.

## Requirements

- **ffmpeg / ffprobe** on `PATH` (`sudo apt-get install ffmpeg`).
- **Python 3.10+** (verified on 3.14).
- Python packages: `pip install -r requirements.txt`.
- Optional: **`espeak-ng`** for the lightweight TTS backend
  (`sudo apt-get install espeak-ng`).

## Usage

```bash
python main.py INPUT --output-base BASE [options]
```

Writes `<BASE>_dubbed<ext>` (dubbed video) and `<BASE>.srt` (subtitles).

```bash
# Dub an English video into Turkish (transcription + translation + TTS)
python main.py movie.mp4 --output-base movie_tr \
    --source-lang en --target-lang tr

# Same language, just re-voice + subtitles
python main.py clip.mp4 --output-base clip --source-lang en --tts espeak

# Subtitles only (no TTS, no muxing)
python main.py talk.mp4 --output-base talk --subtitle-only

# Choose providers / voice explicitly
python main.py v.mp4 --output-base v --stt whisper --translate argos \
    --tts piper --voice en_US-lessac-medium
```

### Options

| Option | Description | Default |
|---|---|---|
| `INPUT` | input video file (never modified) | required |
| `--output-base BASE` | writes `BASE_dubbed<ext>` and `BASE.srt` | required |
| `--source-lang` | source language code, e.g. `en` | STT auto-detect |
| `--target-lang` | target language; when it differs from the source, translate | off |
| `--stt` | STT provider: `whisper`, `fake` | `whisper` |
| `--translate` | translation provider: `argos`, `http`, `fake` | `argos` |
| `--tts` | TTS provider: `piper`, `espeak`, `fake` | `piper` |
| `--voice` | provider-specific voice name | provider default |
| `--subtitle-only` | write only the SRT | off |
| `--keep-workdir` | keep intermediates at `BASE.work` | off |
| `--config FILE` | config file (`key = value` or JSON) | none |

Config-file keys mirror the flags (`stt`, `translate`, `tts`, `voice`); the
environment variables `AUTODUB_STT`, `AUTODUB_TRANSLATE`, `AUTODUB_TTS`,
`AUTODUB_VOICE` are also read (CLI flags win).

### Models and downloads

- **STT**: the `tiny` model (~75 MB) is downloaded by faster-whisper on first
  run into the Hugging Face cache. Select another size by editing
  `WhisperSTT(model_size=...)` or `faster_whisper`'s cache.
- **TTS (piper)**: a voice model (~60 MB) is downloaded on first use into
  `~/.cache/vlc-auto-dub/piper`. Override the directory with
  `AUTODUB_PIPER_DIR`.
- **Translation (argos)**: the language package is downloaded on first use of a
  given pair.

## Providers

| Kind | Name | Backend | Network | Status |
|---|---|---|---|---|
| STT | `whisper` | faster-whisper (local) | model download only | verified |
| STT | `fake` | deterministic test double | none | test-only |
| translate | `argos` | argostranslate (local, offline) | package download on first pair | verified |
| translate | `http` | LibreTranslate-compatible HTTP | yes | **code-only, untested** |
| translate | `fake` | deterministic test double | none | test-only |
| TTS | `piper` | piper-tts (local) | model download on first voice | verified |
| TTS | `espeak` | espeak-ng (local) | none | verified |
| TTS | `fake` | deterministic test double | none | test-only |

The `http` translation backend is **not** enabled by default, ships **untested**,
and requires `AUTODUB_TRANSLATE_URL` (optionally `AUTODUB_TRANSLATE_KEY`). Do not
point it at a public endpoint with private media — only text spans you may share
are sent.

## VLC integration

`transcribe.vlc.lua` adds an **Auto-Dub** menu item that runs the CLI on the
currently playing file and writes `<base>.srt` / `<base>_dubbed<ext>`.

It has **no hardcoded path**. Configure once in
`~/.config/vlc-auto-dub/config.lua`:

```lua
return {
  python = "/usr/bin/python3",
  script = "/absolute/path/to/vlc-auto-dub/main.py",
}
```

(or set `VLC_AUTODUB_PYTHON` / `VLC_AUTODUB_SCRIPT`). Copy the file to your VLC
extensions directory, e.g. on Linux
`~/.local/share/vlc/lua/extensions/`, on macOS
`~/Library/Application\ Support/org.videolan.vlc/lua/extensions/`.

The extension's argument contract (verified by tests, not inside VLC):
`"<python>" "<script>" "<video>" --output-base "<base>" --target-lang "<lang>"`.
It runs the job in the background so VLC's UI thread is not blocked, and logs to
`<base>.autodub.log`. The VLC runtime itself was **not** exercised in CI/here
(no VLC Lua host); the extension is *invocation-verified* and *syntax-checked*,
not *VLC-verified*.

## Testing

```bash
pip install -r requirements.txt pytest
python -m pytest -v
```

- Unit tests use deterministic provider fakes (no model, no network).
- The end-to-end test runs the **real** ffmpeg pipeline on a synthesized fixture
  and asserts: both streams present (ffprobe), subtitles monotonic and
  non-overlapping, assembled duration within tolerance, and the **input hash
  unchanged**.
- `tests/test_real_backends.py` runs real `faster-whisper` + `espeak-ng`+ real
  `argostranslate` (skipped if a backend is absent). It asserts that a real
  model produced real segments and a real engine produced real audio; it does
  **not** assert recognition/translation *quality*.

Generate the synthesized fixture yourself:

```bash
scripts/make_fixture.sh fixture.mp4 4
```

## Limitations

- **Quality is not guaranteed.** The pipeline is mechanically correct (timing,
  muxing, subtitles) but transcription, translation and speech quality depend on
  the models; a `tiny` STT model and offline translation are deliberately small
  and will make mistakes.
- **Single speaker assumed.** No diarization or per-speaker voice mapping.
- **Translation** only covers language pairs argostranslate ships; the `http`
  backend is untested.
- **Piper** speaks the voice you pick; matching the source speaker's voice is out
  of scope.
- **The Docker path** (`Dockerfile`, `run_docker.sh`) is legacy and was **not**
  rebuilt or run for this change.

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2024 VLC Video Dubbing Extension.
