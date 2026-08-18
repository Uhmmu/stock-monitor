#!/bin/sh
set -eu

binary=${1:?usage: capture.sh BINARY OUTPUT_DIR}
output_dir=${2:?usage: capture.sh BINARY OUTPUT_DIR}
mkdir -p "$output_dir"

QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1 "$binary" --playground --theme dark \
  --screenshot "$output_dir/component-playground-dark.png"
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.5 "$binary" --showcase --theme dark --density comfortable \
  --screenshot "$output_dir/showcase-dark-comfortable-1920x1080.png"
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.5 "$binary" --showcase --theme light --density comfortable \
  --screenshot "$output_dir/showcase-light-comfortable-1920x1080.png"
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.5 "$binary" --showcase --theme dark --density compact \
  --screenshot "$output_dir/showcase-dark-compact-1920x1080.png"
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.5 "$binary" --showcase --theme light --density compact \
  --screenshot "$output_dir/showcase-light-compact-1920x1080.png"
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.5 "$binary" --showcase --theme dark --reduced-transparency \
  --screenshot "$output_dir/showcase-reduced-transparency-1920x1080.png"
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=2 "$binary" --showcase --theme dark --high-contrast \
  --reduced-motion --reduced-transparency \
  --screenshot "$output_dir/showcase-high-contrast-2560x1440.png"
