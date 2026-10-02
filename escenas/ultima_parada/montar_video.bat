@echo off
rem Monta el corto final: fotogramas + sonido + etalonaje, viñeta, grano y título.
rem Requiere ffmpeg en el PATH. Ejecutar desde esta carpeta (doble clic vale).
cd /d "%~dp0"
set FONT=C\:/Windows/Fonts/georgia.ttf
set T='if(lt(t,66.5),0,if(lt(t,68),(t-66.5)/1.5,if(lt(t,72.2),1,if(lt(t,73.6),(73.6-t)/1.4,0))))'
set S='if(lt(t,67.3),0,if(lt(t,68.8),(t-67.3)/1.5,if(lt(t,72.2),1,if(lt(t,73.6),(73.6-t)/1.4,0))))'
ffmpeg -y -framerate 24 -i render\frames\f_%%04d.png -i sonido.wav ^
  -vf "eq=contrast=1.04:saturation=1.06:gamma=0.98,colorbalance=rs=-0.02:bs=0.025:rh=0.03:bh=-0.035,vignette=angle=PI/5.5,noise=alls=4:allf=t,fade=t=in:st=0:d=1.5,fade=t=out:st=73.2:d=1.8,drawtext=fontfile='%FONT%':textfile=titulo.txt:fontsize=78:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2-18:alpha=%T%,drawtext=fontfile='%FONT%':textfile=subtitulo.txt:fontsize=26:fontcolor=0xDDDDDD:x=(w-text_w)/2:y=(h/2)+48:alpha=%S%,format=yuv420p" ^
  -c:v libx264 -preset slow -crf 17 -tune grain -c:a aac -b:a 320k -shortest -movflags +faststart ^
  ultima_parada.mp4
rem Versión ligera para compartir
ffmpeg -y -i ultima_parada.mp4 -c:v libx264 -preset slow -crf 23 -c:a aac -b:a 192k -movflags +faststart ultima_parada_web.mp4
