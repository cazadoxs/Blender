"""
Renderiza "Vía muerta" fotograma a fotograma (se puede cortar y relanzar:
los fotogramas ya hechos no se repiten).

Desde esta carpeta, en Windows:
  set BLENDER="C:\\Program Files\\Blender Foundation\\Blender 5.0\\blender.exe"
  %BLENDER% -b via_muerta.blend -P render.py -- --gpu                 (película entera)
  %BLENDER% -b via_muerta.blend -P render.py -- --gpu --plano 3       (solo el plano 3)
  %BLENDER% -b via_muerta.blend -P render.py -- --gpu --prueba        (1 fotograma por plano, rápido)
  %BLENDER% -b via_muerta.blend -P render.py -- --gpu --frames 60,550 --out pruebas

Opciones:
  --calidad equilibrada|maxima   (por defecto maxima. equilibrada: 128 muestras y niebla más ligera de
                 calcular; maxima: 256 muestras y todos los rebotes, varias veces más lenta)
  --muestras N   fuerza las muestras por píxel (el ruido lo limpia OpenImageDenoise)
  --pct N        porcentaje de resolución sobre 1920x804
"""
import bpy, sys, os, time, argparse, json

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument('--gpu', action='store_true')
ap.add_argument('--plano', type=int, default=None)
ap.add_argument('--prueba', action='store_true')
ap.add_argument('--start', type=int, default=None)
ap.add_argument('--end', type=int, default=None)
ap.add_argument('--frames', type=str, default=None)
ap.add_argument('--muestras', type=int, default=None)
ap.add_argument('--calidad', choices=('equilibrada', 'maxima'), default='maxima')
ap.add_argument('--pct', type=int, default=100)
ap.add_argument('--out', type=str, default=None)
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
        print('Render con GPU:', chosen, [d.name for d in prefs.devices if d.use], flush=True)
    else:
        print('No se encontró GPU compatible; se usa la CPU', flush=True)
    try:
        cy.denoising_use_gpu = True
    except AttributeError:
        pass

scene.render.resolution_percentage = a.pct
if a.calidad == 'equilibrada':
    # casi igual a la vista, varias veces más rápido: la niebla con pasos más largos, menos rebotes
    # (en un túnel oscuro casi no aportan) y menos muestras (el ruido lo limpia el denoiser)
    cy.samples = 128
    cy.adaptive_threshold = 0.025
    cy.volume_step_rate = 3.0
    cy.volume_max_steps = 256
    cy.max_bounces = 6
    cy.diffuse_bounces = 3
    cy.glossy_bounces = 2
    cy.transmission_bounces = 4
    cy.transparent_max_bounces = 16
    try:
        cy.use_guiding = False            # el path guiding solo funciona con la CPU
    except AttributeError:
        pass
    # sin desenfoque de movimiento propio en lo que no se mueve: la cámara sigue desenfocando todo
    # igual (misma imagen) y el render va un 30-40 % más rápido (medido en la RTX 3060)
    for o in scene.objects:
        if o.animation_data is None and o.parent is None and not o.constraints:
            o.cycles.use_motion_blur = False
    # la niebla del valle no se ve ni desde el monte ni desde el túnel (planos 01 a 15; comprobado
    # con imagen antes/después: solo cambia el ruido) y se lleva un 18 % del tiempo: ahí no se calcula
    mk = {m.name[:2]: m.frame for m in scene.timeline_markers}
    valle = scene.objects.get('Volumen niebla valle')
    if valle and '16' in mk:
        def _valle(sc, *_):
            valle.hide_render = sc.frame_current < mk['16']
        bpy.app.handlers.frame_change_pre.append(_valle)
if a.muestras:
    cy.samples = a.muestras
scene.render.use_overwrite = False
scene.render.use_placeholder = True
scene.render.use_persistent_data = True

shots = [(m.frame, m.name) for m in sorted(scene.timeline_markers, key=lambda m: m.frame)]
ends = [f for f, _ in shots[1:]] + [scene.frame_end + 1]
ranges = [(f, e - 1, n) for (f, n), e in zip(shots, ends)]

out_dir = a.out or os.path.join('render', 'frames')
out_dir = out_dir if os.path.isabs(out_dir) else os.path.join(here, out_dir)
os.makedirs(out_dir, exist_ok=True)


def one(f):
    scene.frame_set(f)
    path = os.path.join(out_dir, 'f_%04d.png' % f)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return
    scene.render.filepath = path
    t = time.time()
    bpy.ops.render.render(write_still=True)
    print('Fotograma %d: %.1f s' % (f, time.time() - t), flush=True)


if a.frames:
    for f in [int(x) for x in a.frames.split(',')]:
        one(f)
elif a.prueba:
    for f0, f1, n in ranges:
        one((f0 + f1) // 2)
else:
    if a.plano:
        f0, f1, n = ranges[a.plano - 1]
        print('Plano %s: fotogramas %d-%d' % (n, f0, f1), flush=True)
    else:
        f0, f1 = scene.frame_start, scene.frame_end
    scene.frame_start = a.start or f0
    scene.frame_end = a.end or f1
    scene.render.filepath = os.path.join(out_dir, 'f_')
    t = time.time()
    bpy.ops.render.render(animation=True)
    print('Terminado en %.1f min' % ((time.time() - t) / 60), flush=True)
