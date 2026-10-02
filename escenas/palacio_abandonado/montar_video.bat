@echo off
rem Junta los fotogramas renderizados y el sonido en el vídeo final (requiere ffmpeg en el PATH).
cd /d "%~dp0"
ffmpeg -y -framerate 24 -i render\frames\f_%%04d.png -i sonido.wav ^
  -vf "eq=contrast=1.07:saturation=1.12:gamma=0.97,colorbalance=rs=0.03:bs=-0.03:rh=0.03:bh=-0.04,vignette=angle=PI/6,noise=alls=5:allf=t,format=yuv420p" ^
  -c:v libx264 -preset slow -crf 16 -c:a aac -b:a 256k -shortest -movflags +faststart ^
  palacio_abandonado.mp4
