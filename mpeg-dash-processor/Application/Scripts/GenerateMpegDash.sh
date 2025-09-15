#!/bin/bash

# check if an argument was given
if [ -z "$1" ]; then
  echo "Usage: $0 <input-file>"
  exit 1
fi

INPUT_FILE="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BASENAME="$(basename "$INPUT_FILE" .${INPUT_FILE##*.})"

CAPITALIZED="$(tr '[:lower:]' '[:upper:]' <<< ${BASENAME:0:1})${BASENAME:1}"

OUTPUT_DIR="$SCRIPT_DIR/../wwwroot/Static/$CAPITALIZED"

rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

# ffmpeg -i "$INPUT_FILE" \
  # -map 0:v -c:v libx264 -profile:v main -level 4.1 -pix_fmt yuv420p \
  # -map 0:a -c:a aac -b:a 128k \
  # -keyint_min 48 -g 48 -sc_threshold 0 \
  # -seg_duration 0.04 -use_template 1 -use_timeline 1 \
  # -init_seg_name init-\$RepresentationID\$.mp4 \
  # -media_seg_name chunk-\$RepresentationID\$-\$Number%05d\$.m4s \
  # -f dash "$OUTPUT_DIR/manifest.mpd"

ffmpeg -i "$INPUT_FILE" \
  -map 0:v -c:v libx264 -profile:v main -level 4.1 -pix_fmt yuv420p \
  -map 0:a -c:a aac -b:a 128k \
  -keyint_min 60 -g 60 -sc_threshold 0 \
  -seg_duration 4 -use_template 1 -use_timeline 1 \
  -init_seg_name init-\$RepresentationID\$.mp4 \
  -media_seg_name chunk-\$RepresentationID\$-\$Number%05d\$.m4s \
  -f dash "$OUTPUT_DIR/manifest.mpd"