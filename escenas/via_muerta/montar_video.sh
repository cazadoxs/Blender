#!/bin/sh
# Monta el corto final (fotogramas + sonido + etalonaje + título). Requiere python3 y ffmpeg.
cd "$(dirname "$0")"
python3 montar_video.py
