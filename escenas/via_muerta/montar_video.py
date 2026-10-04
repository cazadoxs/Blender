"""
Monta "Vía muerta": fotogramas renderizados + sonido.wav + etalonaje de noche (frío, contraste,
viñeta fuerte y grano de película) + el título en negro al final.
Lee los tiempos de timing.json. Necesita ffmpeg en el PATH.

  python montar_video.py            (o doble clic en montar_video.bat)
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
T = json.load(open('timing.json', encoding='utf-8'))
t0 = T['titulo']['inicio']
dur = T['titulo']['duracion']
# la imagen acaba en el golpe; hasta el título queda negro (se oye al monstruo arriba)
black = max(0.0, t0 - T['frames'] / T['fps'])
a0, a1, b1 = t0 + 0.6, t0 + 1.4, t0 + dur - 0.4
alpha = "if(lt(t,%.2f),0,if(lt(t,%.2f),(t-%.2f)/%.2f,if(lt(t,%.2f),1,max(0,(%.2f-t)/0.4))))" % (a0, a1, a0, a1 - a0, b1, t0 + dur)
if sys.platform.startswith('win'):
    font = 'C\\:/Windows/Fonts/georgia.ttf'
else:
    font = os.environ.get('FONT', '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf')
vf = ','.join([
    'eq=contrast=1.08:saturation=0.82:gamma=0.97',
    'colorbalance=rs=-0.03:gs=-0.005:bs=0.05:rm=-0.02:bm=0.03:rh=0.02:bh=-0.01',
    'vignette=angle=PI/4.2',
    'noise=alls=7:allf=t',
    'tpad=stop_mode=add:stop_duration=%.2f:color=black' % (black + dur),
    'fade=t=in:st=0:d=2.0',
    "drawtext=fontfile='%s':textfile=titulo.txt:fontsize=84:fontcolor=0xE8E2D8:x=(w-text_w)/2:y=(h-text_h)/2:alpha='%s'" % (font, alpha),
    'format=yuv420p',
])
cmd = ['ffmpeg', '-y', '-framerate', str(T['fps']), '-i', os.path.join('render', 'frames', 'f_%04d.png'), '-i', 'sonido.wav',
       '-vf', vf, '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-tune', 'grain', '-c:a', 'aac', '-b:a', '320k',
       '-shortest', '-movflags', '+faststart', 'via_muerta.mp4']
print(' '.join(cmd))
subprocess.check_call(cmd)
subprocess.check_call(['ffmpeg', '-y', '-i', 'via_muerta.mp4', '-c:v', 'libx264', '-preset', 'slow', '-crf', '23',
                       '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', 'via_muerta_web.mp4'])
