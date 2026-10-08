"""
Render vertical (1080x1920) de "Vía muerta" para Shorts, Reels y TikTok.
Usa la misma cámara (los ojos) y las mismas opciones que render.py; solo cambia el formato.

  %BLENDER% -b via_muerta.blend -P render_vertical.py -- --gpu --calidad equilibrada --start 2651 --end 2979 --out render\\vertical

Variable VM_FOV (por defecto 0.85): altura del encuadre vertical respecto al ancho del panorámico.
"""
import bpy, os, runpy

sc = bpy.context.scene
sc.render.resolution_x, sc.render.resolution_y = 1080, 1920
cam = sc.camera.data
k = float(os.environ.get('VM_FOV', '0.85'))
if cam.sensor_fit in ('AUTO', 'HORIZONTAL'):
    cam.sensor_height = cam.sensor_width * k
cam.sensor_fit = 'VERTICAL'
print('Vertical 1080x1920, VM_FOV=%.2f' % k, flush=True)
runpy.run_path(os.path.join(os.path.dirname(bpy.data.filepath), 'render.py'), run_name='__main__')
