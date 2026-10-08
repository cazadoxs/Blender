"""
VÍA MUERTA: construye la escena completa del corto de terror y guarda via_muerta.blend.

  "C:\\Program Files\\Blender Foundation\\Blender 5.0\\blender.exe" -b -P construir_escena.py

Parte del túnel de "Última parada" (más largo, de noche y con niebla) y añade el pozo
con su escalera, el personaje con su frontal, el monstruo y la locomotora que arranca.
Lee recursos/manifiesto.json (lo crea descargar_recursos.py); si falta algún recurso,
esa parte usa un material o modelo procedural, así que la escena siempre se construye.

Opciones (después de "--"):
  --partes tunel,pozo,loco,exterior,vegetacion,noche,personaje,monstruo,animacion,camaras
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
ap.add_argument('--partes', default='tunel,pozo,loco,exterior,vegetacion,noche,personaje,monstruo,animacion,camaras')
ap.add_argument('--salida', default=os.path.join(HERE, 'via_muerta.blend'))
A = ap.parse_args(argv)
PARTES = set(A.partes.split(','))

t0 = time.time()
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.name = 'Via muerta'
util.load_manifest()
main = util.coll('Escena')
ctx = {}


def step(name):
    print('[%6.1f s] %s' % (time.time() - t0, name), flush=True)


from up import ajustes
ajustes.render_settings(scene)

if 'tunel' in PARTES:
    step('Túnel, vía y acantilado')
    from up import tunel
    ctx['tunel'] = tunel.build(main)

if 'pozo' in PARTES:
    step('Pozo, escalera y camino')
    from up import pozo
    ctx['pozo'] = pozo.build(main, ctx)

if 'loco' in PARTES:
    step('Locomotora')
    from up import locomotora, tren
    ctx['loco'] = locomotora.build(main, ctx)
    ctx['tren'] = tren.prepare(main, ctx)

if 'exterior' in PARTES:
    step('Viaducto, valle y montañas')
    from up import exterior
    ctx['exterior'] = exterior.build(main, ctx)

if 'vegetacion' in PARTES:
    step('Vegetación, raíces y hiedra')
    from up import vegetacion
    ctx['vegetacion'] = vegetacion.build(main, ctx)
    if 'tren' in ctx:
        from up import tren
        tren.attach_vegetation(ctx)

if 'noche' in PARTES:
    step('Luna, cielo y niebla')
    from up import noche
    ctx['noche'] = noche.build(main, ctx)

if 'personaje' in PARTES:
    step('Personaje')
    from up import personaje
    ctx['personaje'] = personaje.build(main, ctx)

if 'monstruo' in PARTES:
    step('Monstruo')
    from up import monstruo
    ctx['monstruo'] = monstruo.build(main, ctx)

if 'animacion' in PARTES:
    step('Animación: personaje, monstruo y tren')
    from up import historia
    ctx['historia'] = historia.build(main, ctx)

if 'camaras' in PARTES:
    step('Cámaras y planos')
    from up import guion
    ctx['guion'] = guion.build(main, ctx)
    json.dump(guion.timing(ctx), open(os.path.join(HERE, 'timing.json'), 'w', encoding='utf-8'), indent=1,
              ensure_ascii=False)

# recuento de instancias (para vigilar memoria)
dg = bpy.context.evaluated_depsgraph_get()
cnt = {}
for inst in dg.object_instances:
    if inst.is_instance and inst.parent:
        cnt[inst.parent.name] = cnt.get(inst.parent.name, 0) + 1
print('Instancias: %d en total' % sum(cnt.values()))
for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])[:12]:
    print('   %-40s %d' % (k, v))

step('Guardando')
bpy.ops.wm.save_as_mainfile(filepath=A.salida, relative_remap=True)
try:
    bpy.ops.file.make_paths_relative()
    bpy.ops.wm.save_mainfile()
except Exception as e:
    print('Aviso: no se pudieron hacer relativas las rutas:', e)
step('Hecho: ' + A.salida)
