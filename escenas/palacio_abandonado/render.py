"""
Renderiza la animación del palacio abandonado fotograma a fotograma.

Ejemplos (Windows, desde esta carpeta):
  "C:\\Program Files\\Blender Foundation\\Blender 5.0\\blender.exe" -b palacio_abandonado.blend -P render.py -- --gpu
  ... -P render.py -- --gpu --frames 1,250,500 --out pruebas   (solo unos fotogramas de prueba)
  ... -P render.py -- --gpu --start 1 --end 528                 (animación completa)

Se puede interrumpir y volver a lanzar: los fotogramas ya hechos no se repiten.
"""
import bpy, sys, os, time, argparse

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument('--gpu', action='store_true', help='usar la GPU (OptiX, si no CUDA)')
ap.add_argument('--start', type=int, default=None)
ap.add_argument('--end', type=int, default=None)
ap.add_argument('--frames', type=str, default=None, help='lista de fotogramas sueltos: 1,250,500')
ap.add_argument('--pct', type=int, default=100, help='porcentaje de resolución (base 1920x804)')
ap.add_argument('--samples', type=int, default=160)
ap.add_argument('--out', type=str, default=os.path.join('render', 'frames'))
a = ap.parse_args(argv)

here = os.path.dirname(bpy.data.filepath)
scene = bpy.context.scene
cy = scene.cycles

if a.gpu:
    prefs = bpy.context.preferences.addons['cycles'].preferences
    chosen = None
    for kind in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL'):
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        prefs.get_devices()
        devs = [d for d in prefs.devices if d.type == kind]
        if devs:
            for d in prefs.devices:
                d.use = d.type == kind
            chosen = kind
            break
    if chosen:
        cy.device = 'GPU'
        print('Render con GPU:', chosen, [d.name for d in prefs.devices if d.use])
    else:
        print('No se encontró GPU compatible; se usa la CPU')

scene.render.resolution_x = 1920
scene.render.resolution_y = 804
scene.render.resolution_percentage = a.pct
cy.samples = a.samples
cy.adaptive_threshold = 0.015
cy.use_denoising = True
cy.denoiser = 'OPENIMAGEDENOISE'
try:
    cy.denoising_use_gpu = bool(a.gpu)
except AttributeError:
    pass
cy.diffuse_bounces = 3
scene.render.use_motion_blur = True
scene.render.use_persistent_data = True
scene.render.use_overwrite = False
scene.render.use_placeholder = True

out_dir = a.out if os.path.isabs(a.out) else os.path.join(here, a.out)
os.makedirs(out_dir, exist_ok=True)

if a.frames:
    for f in [int(x) for x in a.frames.split(',')]:
        scene.frame_set(f)
        scene.render.filepath = os.path.join(out_dir, 'f_%04d.png' % f)
        t = time.time()
        bpy.ops.render.render(write_still=True)
        print('Fotograma %d: %.1f s' % (f, time.time() - t), flush=True)
else:
    scene.frame_start = a.start or scene.frame_start
    scene.frame_end = a.end or scene.frame_end
    scene.render.filepath = os.path.join(out_dir, 'f_')
    t = time.time()
    bpy.ops.render.render(animation=True)
    print('Animación terminada en %.1f min' % ((time.time() - t) / 60), flush=True)
