# VLC AI Auto-Dubbing Extension 🎙️🔄

> Transcribe a video's audio and generate a dubbed track with faster-whisper and local speech synthesis

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 🎯 What it does

Process a video's audio with local transcription and speech synthesis:
- Automatic speech recognition (transcription) with faster-whisper
- Speech synthesis for the transcribed text with pyttsx3
- Volume lowering and mixing of the dubbed audio
- A Docker image that bundles ffmpeg, faster-whisper and pyttsx3
- An included VLC Lua extension (see limitations below)

## Key features

- **Containerized pipeline**: the Docker image bundles all processing tools.
- **Local processing**: no media leaves your machine for the Docker pipeline.
- **Subtitle output**: writes an SRT file next to the dubbed video.

## Overview

This project provides a Docker-based tool that creates a dubbed audio track from a video. The process:

1. Extract the audio track from the video.
2. Transcribe speech with faster-whisper.
3. Lower the original voice in each spoken segment.
4. Synthesize speech for the transcribed text with pyttsx3.
5. Mix the synthesized speech over the lowered segment.
6. Concatenate the processed segments and the non-speech audio.
7. Write the dubbed audio, the subtitle file, and the final video.

> **Note**: The Docker image installs its dependencies (ffmpeg, espeak, faster-whisper, pyttsx3), so the Python packages are not needed on the host for the Docker path.

## Quick Start

```bash
# Clone the repository
git clone https://github.com/UltraInstinct0x/vlc-auto-dub.git
cd vlc-auto-dub

# Make the script executable
chmod +x run_docker.sh

# Build the image and run the pipeline
./run_docker.sh /path/to/video.mp4 /path/to/output
```

The second argument is an output path base. The pipeline writes `<base>_dubbed.wav`, `<base>.srt`, and `<base>_dubbed<ext>` beside it.

## Project Structure

### Core Components

| File | Description |
|------|-------------|
| `main.py` | Core processing logic for audio extraction, transcription, and processing |
| `run_entrypoint.sh` | Docker container entrypoint script |
| `Dockerfile` | Container definition with all dependencies |
| `run_docker.sh` | Helper script for Docker operations |
| `transcribe.vlc.lua` | VLC extension for user interaction |

## Setup Guide

### Prerequisites

- **Docker Desktop**: [Download here](https://www.docker.com/products/docker-desktop)
- **VLC Media Player**: [Download here](https://www.videolan.org/vlc/)

### Installation Steps

1. **Docker Setup**
   ```bash
   # Verify Docker installation
   docker --version
   ```

2. **VLC Extension Installation**
   ```bash
   # macOS
   cp transcribe.vlc.lua ~/Library/Application\ Support/org.videolan.vlc/lua/extensions/
   ```

### Usage Instructions

#### Docker Method
```bash
./run_docker.sh <input_video> <output_base>
```

Example:
```bash
./run_docker.sh ~/Videos/movie.mp4 ~/Music/dubbed_movie
```

#### VLC Integration

1. Open VLC
2. Navigate to `View → Extensions`
3. Select the dubbing extension
4. Follow the on-screen prompts

## Advanced Configuration

### Customization Options

Edit `main.py` to adjust:
- Volume levels
- TTS voice settings
- Transcription parameters
- Audio processing options

### Development Notes

For local development:
1. Create a virtual environment
2. Install requirements
3. Run `main.py` directly

## Troubleshooting

Common issues and solutions:

- **Permission Denied**: Run `chmod +x run_docker.sh`
- **Docker Not Running**: Start Docker Desktop
- **Missing Output**: Ensure write permissions in output directory

## Implemented in repository

- Audio extraction, transcription with faster-whisper, per-segment volume lowering, pyttsx3 speech synthesis, audio mixing and concatenation, and SRT generation, all in `main.py`.
- A Docker image that installs ffmpeg, espeak, faster-whisper and pyttsx3.
- A VLC Lua extension that shows a language prompt and launches the pipeline.

## Limitations and unverified behavior

- **No translation.** The pipeline does not translate speech between languages, and there is no translation library or service anywhere in the code. Speech synthesis uses the transcribed text as-is, so the dub stays in the source language.
- **The VLC extension does not work as shipped.** In `transcribe.vlc.lua`, the launch command hardcodes the placeholder path `/path/to/main.py` and calls the host `python3` directly rather than the Docker script.
- **The extension's arguments do not match the pipeline.** It passes the entered language as the second argument, but `main.py` treats its second argument as an output path base, so the language never reaches any step.
- **Subtitle filename mismatch.** The extension looks for `<name>_transcription.srt`, while `main.py` writes `<base>.srt`.
- **Runtime status is not verified here.** The repository includes no test suite, and the pipeline has not been executed as part of documenting it.

## Roadmap (proposals, not commitments)

These are ideas, not implemented features:

- Add real translation so dubbing can target a language different from the source.
- Parameterize the extension launch path and align its arguments with the pipeline.
- Add a test suite.

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## License

MIT License

Copyright (c) 2024 VLC Video Dubbing Extension

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

For more information or support, please [open an issue](https://github.com/ultrainstinct0x/vlc-extension/issues).
