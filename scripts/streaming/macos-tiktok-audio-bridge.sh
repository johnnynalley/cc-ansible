#!/bin/zsh
set -eu

INPUT_URL="${1:-rtmp://100.66.6.113:1936/live/vertical}"
FFMPEG="${FFMPEG:-/opt/homebrew/bin/ffmpeg}"
LOG_PREFIX="tiktok-audio-bridge"

cleanup() {
  /usr/bin/pkill -P $$ 2>/dev/null || true
}

trap cleanup INT TERM EXIT

find_vbcable_index() {
  "$FFMPEG" -hide_banner -f lavfi -i anullsrc=r=48000:cl=stereo -t 0.1 \
    -f audiotoolbox -list_devices true - 2>&1 \
    | awk '/com\.vbaudio\.vbcable|VB-Cable/ {
        if (match($0, /\[[0-9]+\]/)) {
          print substr($0, RSTART + 1, RLENGTH - 2)
          exit
        }
      }'
}

while true; do
  index="$(find_vbcable_index || true)"
  if [[ -z "${index}" ]]; then
    print -u2 "${LOG_PREFIX}: VB-Cable output device not found"
    sleep 5
    continue
  fi

  print -u2 "${LOG_PREFIX}: starting input=${INPUT_URL} vbcable_output_index=${index}"
  set +e
  "$FFMPEG" \
    -hide_banner \
    -nostdin \
    -loglevel info \
    -i "${INPUT_URL}" \
    -map 0:a:0 \
    -vn \
    -ac 2 \
    -ar 48000 \
    -f audiotoolbox \
    -audio_device_index "${index}" \
    -
  rc=$?
  set -e

  print -u2 "${LOG_PREFIX}: ffmpeg exited rc=${rc}; restarting in 2s"
  sleep 2
done
