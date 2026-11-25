# vlc-auto-dub

> Dub a video's speech into subtitles and an alternate audio track, locally.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Dubs a video file end to end: extract audio → transcribe (STT) → **optional
translate** → synthesize speech (TTS) → fit each clip to its time slot →
assemble → mux a new audio track. By default the original media is never
modified; with `--in-place` the dub and subtitles are added to the file itself
as extra tracks (every original track kept, atomic replace).

Everything runs locally. The default path is **fully local and
content-agnostic**: `faster-whisper` (speech-to-text), `argostranslate`
(translation) and `piper`/`espeak-ng` (speech). No media or transcripts leave
your machine, there is **no moderation/content gate, no telemetry, and no
refusal based on the material** — it processes any file it is handed, in any
language pair the local backends support. No API key is required.

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
- **Language-general**: `--source-lang`/`--target-lang` accept arbitrary
  ISO-style codes the local backends support. Missing argos packs install on
  demand; the TTS voice follows the target language.
- **Subtitles**: a subtitle track inside the dubbed media, plus an UTF-8 `.srt`
  (skip it with `--no-srt`).
- **Handles real inputs**: video or audio-only files, any container ffmpeg
  reads, paths with spaces/non-ASCII characters, and non-ASCII source text.

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

Writes `<BASE>_dubbed<ext>`: every original track (audio, subtitles, chapters),
plus the dub as the default audio track and the new subtitles as the default
subtitle track, like `--in-place` but in a copy, and the subtitles also as
`<BASE>.srt`. `--no-srt` skips the `.srt` when the subtitles are inside the copy;
it is still written when they cannot go inside: `--subtitle-only`, audio-only
input (`<BASE>_dubbed.wav`), containers other than MP4/M4V/MOV/MKV, or a
container that cannot carry some original track (that copy falls back to the
video plus the dub, with a warning). Data tracks the container cannot carry
(timecode, phone sensor data) are left out, with a warning. An existing
`<BASE>.srt` is never deleted, and with `--no-srt` the fallback writes
`<BASE>_dubbed.srt` rather than overwrite it.

```bash
python main.py INPUT --in-place [options]
```

Adds the tracks to `INPUT` itself instead (`.mp4`/`.m4v`/`.mov`/`.mkv`).

```bash
# Dub an English video into Turkish (transcription + translation + TTS)
python main.py movie.mp4 --output-base movie_tr \
    --source-lang en --target-lang tr

# Same language, just re-voice + subtitles
python main.py clip.mp4 --output-base clip --source-lang en --tts espeak

# Subtitles only (no TTS, no muxing)
python main.py talk.mp4 --output-base talk --subtitle-only

# Add a Turkish dub + subtitle track inside the file; source auto-detected
python main.py movie.mkv --in-place --target-lang tr

# Dub track only, no subtitles
python main.py movie.mp4 --in-place --source-lang en --target-lang de --dub-only

# Skip transcription: dub from the file's own subtitle track (much faster)
python main.py movie.mkv --in-place --target-lang tr --use-embedded-subs

# Voice-over: keep the original voices audible under the dub
python main.py movie.mkv --in-place --target-lang tr --original-volume 0.3

# Choose providers / voice explicitly
python main.py v.mp4 --output-base v --stt whisper --translate argos \
    --tts piper --voice en_US-lessac-medium
```

### Options

| Option | Description | Default |
|---|---|---|
| `INPUT` | input video file (never modified) | required |
| `--output-base BASE` | writes `BASE_dubbed<ext>` and `BASE.srt` (see above) | required unless `--in-place` |
| `--no-srt` | no `BASE.srt` when the subtitles are inside the dubbed copy | off |
| `--in-place` | add the tracks inside `INPUT` (see below) | off |
| `--source-lang` | source language code, e.g. `en` | STT auto-detect |
| `--target-lang` | target language; when it differs from the source, translate | off |
| `--stt` | STT provider: `whisper`, `fake` | `whisper` |
| `--translate` | translation provider: `nllb`, `argos`, `http`, `fake` | `nllb` |
| `--tts` | TTS provider: `piper`, `espeak`, `fake` | `piper` |
| `--voice` | provider-specific voice name | provider default |
| `--whisper-model` | faster-whisper model (`large-v3`, `large-v3-turbo`, `medium`, ...) | `large-v3` |
| `--no-sound-tags` | no `[laughter]`/`[music]`/`[train]`... tags in subtitles | tags on |
| `--subtitle-only` | subtitles only, no dub | off |
| `--original-volume` | keep the original speech under the dub at this gain, 0–1 (voice-over) | `0` (dub replaces it) |
| `--dub-volume` | dub loudness as a linear gain, 0–3 | `1.0` |
| `--use-embedded-subs` | dub from a text subtitle track in the file instead of transcribing (see below) | off |
| `--dub-only` | dub only, no subtitles | off |
| `--keep-workdir` | keep intermediates at `BASE.work` | off |
| `--config FILE` | config file (`key = value` or JSON) | none |

Config-file keys mirror the flags (`stt`, `translate`, `tts`, `voice`); the
environment variables `AUTODUB_STT`, `AUTODUB_TRANSLATE`, `AUTODUB_TTS`,
`AUTODUB_VOICE` are also read (CLI flags win).

### `--in-place`

- Keeps **every** original video, audio, subtitle and attachment stream; nothing
  from the source is re-encoded. Only the new dub is encoded (AAC).
- The dub becomes the **default** audio track, tagged with its ISO 639-2
  language (`tur`, `ger`, ...) and titled `AutoDub (<lang>)`.
- Subtitles go in as a track in the format the container accepts: `mov_text`
  for MP4/M4V/MOV, SubRip for MKV. MP4 players usually enable the first
  subtitle track automatically; MKV leaves it off until selected.
- Re-running for the same language **replaces** the earlier AutoDub tracks (an
  untranslated run also replaces ones with no language tag, which older versions
  wrote);
  a different language adds another pair. Transcription always reads the
  original audio, never an earlier dub.
- Safety: the result is written to a hidden temp file in the same folder,
  verified (stream counts, labelled tracks, duration), and only then renamed
  over the original in one atomic step. Any failure before that leaves the
  original byte-for-byte untouched and removes the temp file.

### `--use-embedded-subs`

Transcription is the slowest stage. When the file already carries a **text**
subtitle track (SubRip, ASS/SSA, mov_text, WebVTT), its cues give the lines and
their timing, so the dub is built from them and STT is skipped entirely
(the sample video: ~12 s instead of ~2 min).

- **Track choice**: a track already in `--target-lang` (no translation needed),
  else one in the spoken language: `--source-lang`, or the language detected from
  a few short samples (always Whisper `base`, whatever `--whisper-model` is;
  one-time ~145 MB download; an unsure result means transcribing). An untagged
  track is used only when `--source-lang` is set; a track in any other language
  never is. Full tracks beat SDH/hearing-impaired ones, and the default track
  beats the rest. **Forced** tracks and AutoDub tracks from an earlier
  `--in-place` run are never used. Bitmap tracks (PGS, VobSub, DVB) hold
  pictures, not text, and are ignored.
- **Language**: translation runs from the track's language tag, and the TTS
  voice follows it.
- **Cleaning**: styling (`<i>`, `{\an8}`), sounds (`[door slams]`, `(laughs)`),
  sung lines (`♪ ... ♪`), speaker labels (`JOHN:`) and dialogue dashes are
  removed so they are not spoken; overlapping cues are merged or trimmed into a
  non-overlapping timeline.
- **Fallback**: no suitable track, a track that cannot be read, or one with no
  speakable text → the audio is transcribed as usual and a warning says why.

### Voice-over mix: `--original-volume`, `--dub-volume`

By default the dub **replaces** the speech: the original audio is only kept in
the gaps between lines. With one synthetic voice for everyone, that makes it
hard to tell who is talking. `--original-volume 0.3` keeps the original speech
underneath at 30%, documentary voice-over style, so each speaker's voice, tone
and timing still come through. `--dub-volume` scales the dub itself (`0.75`
softer, `1.5` louder).

- Only the speech slots are mixed; the gaps keep the original at full level.
- A limiter stops the sum from clipping (it does not auto-level quiet parts).
- Both also read from the config file (`original_volume`, `dub_volume`) and the
  environment (`AUTODUB_ORIGINAL_VOLUME`, `AUTODUB_DUB_VOLUME`).
- VLC plays one audio track at a time, so the mix is baked into the dub track.

### Recognition, timing and sound tags

- **STT**: Whisper `large-v3` with word timestamps and
  `condition_on_previous_text` off (avoids hallucination loops). On Apple
  Silicon it runs on the GPU via `mlx-whisper` with
  `hallucination_silence_threshold`; elsewhere faster-whisper on CPU (int8, VAD,
  beam 5). CPU `large-v3` is slower than real time on a laptop;
  `--whisper-model large-v3-turbo` is much faster.
- **Cue timing** is rebuilt from word timestamps: a cue starts at its first word
  and ends ~0.2 s after its last, splitting at pauses and sentence ends, at most
  6 s / ~2 lines per cue. Silence no longer keeps a line on screen.
- **Translation**: NLLB-200 distilled 1.3B (CTranslate2, int8, ~1.4 GB one-time
  download, model licence CC-BY-NC 4.0). Argos remains as `--translate argos`.
- **Sound tags**: an AudioSet classifier (MIT AST) listens to the gaps between
  speech and writes tags such as `[laughter]`, `[screaming]`, `[crying]`,
  `[moaning]`, `[heavy breathing]`, `[music]`, `[train]`, `[siren]` (in Turkish
  for `tr`: `[kahkaha]`, `[çığlık]`, ...). Tags are subtitles only, never dubbed.

### Languages and voices

- **Source auto-detect**: omit `--source-lang` and the STT model detects the
  spoken language; translation then runs from the detected language. The file's
  own language tag is not trusted (it is often wrong).
- **Pivot translation**: Argos ships most languages only to/from English, so when
  no direct pack exists (e.g. `es->tr`) the text is translated through English
  (`es->en->tr`), installing both packs on demand.

- Language codes are validated as ISO-ish (`en`, `tr`, `de`, `pt-BR`, ...).
- **Translation packs install on demand** for the requested pair on first use.
  If a pair does not exist, the run fails with a clear message naming the exact
  pair and the install command (`argospm install translate-<src>_<tgt>`) — it
  never silently emits source-language audio as if it were the target.
- **No-op translation is rejected:** if a requested `src->tgt` pair (with
  `src != tgt`) returns the source text unchanged for every segment — the
  failure mode where a pack is not actually loaded — the run aborts with a clear
  error and writes no output, rather than dubbing source-language audio.
- **TTS voice follows the target language**: `espeak` uses the language code as
  its voice; `piper` maps a set of languages (en, de, fr, es, it, tr, ru, pt) to
  real voices and falls back to `en_US-lessac-medium` for an unmapped language,
  recording a warning. An explicit `--voice` always overrides.

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

`transcribe.vlc.lua` adds **Auto-Dub** to VLC's Extensions menu (macOS: the
**VLC** app menu → Extensions). Its dialog offers:

- **Spoken language**: Auto-detect or a fixed language.
- **Translate to**: a target language, or no translation.
- **Produce**: Dub + subtitles, Dub only, or Subtitles only.
- **Use the video's subtitles (faster)** (off by default): runs
  `--use-embedded-subs`, skipping transcription when the file has a text subtitle
  track in the spoken or target language. Subtitles are often condensed and
  timed for reading, so the dub may follow the speech less closely.
- **Original voices** (Off / 15% / 30% / 50%) and **Dub volume**: run
  `--original-volume` / `--dub-volume`. Preselect your usual levels with
  `original_volume` / `dub_volume` in the config below.
- **Add tracks into this file** (on by default for MP4/M4V/MOV/MKV): runs
  `--in-place`. Untick it to write a dubbed copy, `<base>_dubbed<ext>`, instead
  (with `--no-srt`: the subtitles are inside it); **Reopen video** then plays
  the copy.

The job runs in the background (log: `<base>.autodub.log`). **Check status**
reads the log; **Reopen video** reloads the rewritten file at the current
position so the new tracks appear under Audio → Audio Track and Subtitle →
Sub Track. VLC launched from the Dock has a minimal `PATH`; the CLI adds
`/opt/homebrew/bin`, `/usr/local/bin` and `~/.local/bin` itself so ffmpeg is
still found.

It has **no hardcoded path**. Configure once in
`~/.config/vlc-auto-dub/config.lua`:

```lua
return {
  python = "/usr/bin/python3",
  script = "/absolute/path/to/vlc-auto-dub/main.py",
  original_volume = 0.3,  -- optional: preselect "Original voices"
  dub_volume = 1.0,       -- optional: preselect "Dub volume"
}
```

(or set `VLC_AUTODUB_PYTHON` / `VLC_AUTODUB_SCRIPT`). Copy the file to your VLC
extensions directory, e.g. on Linux
`~/.local/share/vlc/lua/extensions/`, on macOS
`~/Library/Application\ Support/org.videolan.vlc/lua/extensions/`.

Tests execute the extension's real `build_args()` with a standalone Lua
interpreter and run the CLI with the argv it produces. The dialog code itself
needs VLC's Lua host and is only syntax-checked in CI.

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
- **Audio-only input** produces an audio-only output (`<base>_dubbed.wav`); there
  is no video to carry.
- **Single speaker assumed.** No diarization or per-speaker voice mapping.
- **Translation** only covers language pairs argostranslate ships; an unavailable
  pair is a clear error, and the `http` backend is untested (off by default).
- **Piper** speaks the mapped voice for the target language; matching the source
  speaker's voice is out of scope, and unmapped languages fall back to English.
- **The Docker path** (`Dockerfile`, `run_docker.sh`) is legacy and was **not**
  rebuilt or run for this change.

## Privacy

The default pipeline is **offline and content-agnostic**. `faster-whisper`,
`argostranslate` and `piper`/`espeak-ng` run on your machine; no media,
transcript or metadata is uploaded, and there is no moderation gate, telemetry
or automatic refusal. The only network access is one-time model/voice/translation
downloads. The `http` translation backend is inert unless you explicitly set
`AUTODUB_TRANSLATE_URL`, and it sends only the text spans you allow.

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2024 VLC Video Dubbing Extension.
