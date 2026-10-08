@echo off
rem Render vertical de los tres clips para Shorts, Reels y TikTok. Se puede cerrar y relanzar: sigue donde lo dejo.
cd /d "%~dp0"
set BLENDER="C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
set OPC=--gpu --calidad equilibrada --muestras 64 --pct 75 --out render\vertical
rem 1. La cara se asoma
%BLENDER% -b via_muerta.blend -P render_vertical.py -- %OPC% --start 2651 --end 2979
rem 2. Persecucion por el techo
%BLENDER% -b via_muerta.blend -P render_vertical.py -- %OPC% --start 3218 --end 3630
rem 3. El freno
%BLENDER% -b via_muerta.blend -P render_vertical.py -- %OPC% --start 4136 --end 4379
echo Terminado
