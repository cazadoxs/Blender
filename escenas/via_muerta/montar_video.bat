@echo off
rem Monta el corto final (fotogramas + sonido + etalonaje + título). Requiere Python y ffmpeg.
cd /d "%~dp0"
python montar_video.py
pause
