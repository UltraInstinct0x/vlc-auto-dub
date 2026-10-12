#!/bin/bash
# This shell script checks for Docker installation, builds the Docker image if needed,
# and then runs the container with the current working directory mounted.
# Usage: ./run_docker.sh <video_path> <output_audio>
if ! command -v docker &> /dev/null
then
    echo "Error: Docker is not installed. Please install Docker and try again."
    exit 1
fi

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <video_path> <output_path>"
    exit 1
fi

# Create output file to make realpath work
VIDEO_PATH=$(realpath "$1")
OUTPUT_PATH=$(dirname "$2")/$(basename "$2")

echo "[INFO] Building Docker image (if not already built)..."
docker build -t vlc-extension .

echo "[INFO] Running Docker container..."
echo "[INFO] Command: python main.py \"/input/$(basename "$VIDEO_PATH")\" \"/output/$(basename "$OUTPUT_PATH")\""
docker run --rm \
    -v "$(dirname "$VIDEO_PATH")":/input \
    -v "$(dirname "$OUTPUT_PATH")":/output \
    vlc-extension \
    python main.py \
        "/input/$(basename "$VIDEO_PATH")" \
        --output-base "/output/$(basename "$OUTPUT_PATH")"