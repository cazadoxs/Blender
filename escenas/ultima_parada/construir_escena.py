"""
ÚLTIMA PARADA: construye la escena completa y guarda ultima_parada.blend.

  "C:\\Program Files\\Blender Foundation\\Blender 5.0\\blender.exe" -b -P construir_escena.py

Lee recursos/manifiesto.json (lo crea descargar_recursos.py). Si falta algún
recurso, esa parte usa un material o modelo procedural, así que la escena
siempre se construye.

Opciones (después de "--"):
  --partes tunel,loco,vegetacion,exterior,camaras   (para pruebas: solo algunas partes)
  --salida archivo.blend
"""
import bpy, sys, os, time, argparse, json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for m in [k for k in sys.modules if k == 'up' or k.startswith('up.')]:
    del sys.modules[m]

from up import util, cfg

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument('--partes', default='tunel,loco,vegetacion,exterior,luz,camaras')
ap.add_argument('--salida', default=os.path.join(HERE, 'ultima_parada.blend'))
A = ap.parse_args(argv)
PARTES = set(A.partes.split(','))

t0 = time.time()
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.name = 'Ultima parada'
util.load_manifest()
main = util.coll('Escena')
ctx = {}


def step(name):
    print('[%6.1f s] %s' % (time.time() - t0, name), flush=True)


if 'tunel' in PARTES:
    step('Túnel, vía y acantilado')
    from up import tunel
    ctx['tunel'] = tunel.build(main)

if 'loco' in PARTES:
    step('Locomotora')
    from up import locomotora
    ctx['loco'] = locomotora.build(main, ctx)

if 'exterior' in PARTES:
    step('Viaducto, valle y montañas')
    from up import exterior
    ctx['exterior'] = exterior.build(main, ctx)

if 'vegetacion' in PARTES:
    step('Vegetación, raíces y hiedra')
    from up import vegetacion
    ctx['vegetacion'] = vegetacion.build(main, ctx)

if 'luz' in PARTES:
    step('Sol, cielo y atmósfera')
    from up import luz
    ctx['luz'] = luz.build(main, ctx)

if 'camaras' in PARTES:
    step('Cámaras y planos')
    from up import camaras
    ctx['camaras'] = camaras.build(main, ctx)

from up import ajustes
ajustes.render_settings(scene)

if 'camaras' in PARTES:
    # tiempos para el sonido (audio.py) y el montaje
    import math
    from up import camaras, vegetacion
    px, py, tip = vegetacion.DROP_ROOT_TIP or (0, 0, 2.4)
    from up import tunel
    fall = math.sqrt(2 * (tip - tunel.PUDDLE_DROP[2]) / 9.81)
    timing = {
        'fps': cfg.FPS, 'frames': ajustes.FRAMES, 'duracion': ajustes.FRAMES / cfg.FPS,
        'planos': [{'nombre': n, 'inicio': (f0 - 1) / cfg.FPS, 'fin': f1 / cfg.FPS} for n, f0, f1 in camaras.SHOTS],
        'gotas': [(f - 1) / cfg.FPS + fall for f in camaras.DROPS],
        'salida_tunel': [(f - 1) / cfg.FPS for f in camaras.EXIT_FRAMES],
        'pajaros': 1249 / cfg.FPS,
        'titulo': [66.5, 73.6],
    }
    json.dump(timing, open(os.path.join(HERE, 'timing.json'), 'w'), indent=1, ensure_ascii=False)

step('Guardando')
bpy.ops.file.make_paths_relative() if bpy.data.filepath else None
bpy.ops.wm.save_as_mainfile(filepath=A.salida, relative_remap=True)
try:
    bpy.ops.file.make_paths_relative()
    bpy.ops.wm.save_mainfile()
except Exception as e:
    print('Aviso: no se pudieron hacer relativas las rutas:', e)
step('Hecho: ' + A.salida)
