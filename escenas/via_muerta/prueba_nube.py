"""
Prueba rápida sin GPU (la usa la acción de GitHub y sirve en cualquier PC):
abre via_muerta.blend y renderiza unos fotogramas a baja resolución.

  python prueba_nube.py --frames 72,552,1190 --ancho 960 --muestras 32 --out pruebas
  (o: blender -b via_muerta.blend -P prueba_nube.py -- --frames ...)
"""
import sys, os, time, argparse
import bpy

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
ap = argparse.ArgumentParser()
ap.add_argument('--blend', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'via_muerta.blend'))
ap.add_argument('--frames', default='97,481,700,841,1273,2420,2700,3000,3217,3740,3880,4000,4140,4300,4390,4420')
ap.add_argument('--ancho', type=int, default=960)
ap.add_argument('--muestras', type=int, default=32)
ap.add_argument('--out', default='pruebas')
a = ap.parse_known_args(argv)[0]
if not bpy.data.filepath:
    bpy.ops.wm.open_mainfile(filepath=a.blend)
s = bpy.context.scene
s.render.resolution_x = a.ancho
s.render.resolution_y = round(a.ancho / 2.388)
s.render.resolution_percentage = 100
s.cycles.samples = a.muestras
s.cycles.dicing_rate = 3.0
s.cycles.volume_step_rate = 3.0
s.render.use_motion_blur = False
out = a.out if os.path.isabs(a.out) else os.path.join(os.path.dirname(bpy.data.filepath), a.out)
os.makedirs(out, exist_ok=True)
for f in [int(x) for x in a.frames.split(',')]:
    s.frame_set(f)
    s.render.filepath = os.path.join(out, 'f_%04d.png' % f)
    t = time.time()
    bpy.ops.render.render(write_still=True)
    print('FOTOGRAMA %d %.1f s' % (f, time.time() - t), flush=True)
