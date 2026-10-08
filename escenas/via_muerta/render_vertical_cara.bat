@echo off
rem Render vertical solo del clip de la cara (fotogramas 2651-2979). Se puede cerrar y relanzar: sigue donde lo dejo.
cd /d "%~dp0"
set BLENDER="C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
%BLENDER% -b via_muerta.blend -P render_vertical.py -- --gpu --calidad equilibrada --muestras 64 --pct 75 --out render\vertical --start 2651 --end 2979
echo Terminado
