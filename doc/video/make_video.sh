#!/bin/sh
# The demo video, from scratch: KLayout frames, setupEM frames, composition. Run from the repository root.
# Environment: KLAYOUT (klayout_app), PYTHON (with setupEM, Pillow, imageio-ffmpeg), VIDEO (output folder).
set -e
KLAYOUT=${KLAYOUT:-/d/KLayout/klayout_app.exe}
PYTHON=${PYTHON:-/d/venv/palace/Scripts/python.exe}
VIDEO=${VIDEO:-/d/Palace_testcases/klayout_export/video}
export VIDEO
timeout -k 10 1000 "$KLAYOUT" -rm doc/video/capture_video.py
if grep -q FAILED "$VIDEO/capture.log"; then grep -A8 FAILED "$VIDEO/capture.log"; exit 1; fi
timeout -k 10 120 "$PYTHON" doc/userguide/capture/capture_setupem.py "$VIDEO/work/cascode_em.simcfg" "$VIDEO/frames/setupem"
"$PYTHON" doc/video/compose_video.py "$VIDEO"
