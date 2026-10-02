"""Guion de cámara: siete planos con cortes en marcadores, desenfoque de lente,
movimiento de cámara en mano y exposición que se adapta al salir del túnel."""
import bpy, math
from mathutils import Vector
from . import cfg
from .util import coll

FPS = cfg.FPS
# (nombre, primer fotograma, último fotograma)
SHOTS = [
    ('01 Gota', 1, 144),
    ('02 Via', 145, 432),
    ('03 Locomotora', 433, 672),
    ('04 Rueda', 673, 816),
    ('05 Placa', 817, 936),
    ('06 Hacia la luz', 937, 1560),
    ('07 Ultima parada', 1561, 1800),
]
DROPS = [64]          # fotograma en que se suelta la gota de la raíz
EXIT_FRAMES = (1150, 1235)   # la cámara sale por la boca: la exposición baja


def fcurves_of(id_data):
    ad = id_data.animation_data
    if not ad or not ad.action:
        return []
    act = ad.action
    try:
        return list(act.fcurves)
    except AttributeError:
        from bpy_extras import anim_utils
        cb = anim_utils.action_get_channelbag_for_slot(act, ad.action_slot)
        return list(cb.fcurves) if cb else []


def handheld(cam, strength=0.004, scale=38.0, seed=0):
    cam.rotation_euler = (0, 0, 0)
    cam.keyframe_insert('rotation_euler', frame=1)
    for i, fc in enumerate(fcurves_of(cam)):
        if fc.data_path != 'rotation_euler':
            continue
        m = fc.modifiers.new('NOISE')
        m.strength = strength * (0.6 if fc.array_index == 2 else 1.0)
        m.scale = scale
        m.phase = seed * 13.7 + i * 5.1
        m.depth = 1


def smooth_keys(id_data, kind='BEZIER'):
    for fc in fcurves_of(id_data):
        for kp in fc.keyframe_points:
            kp.interpolation = kind
            kp.handle_left_type = kp.handle_right_type = 'AUTO_CLAMPED'


def rig(c, name, keys, lens, fstop, focus, sensor=36.0, shake=0.004, seed=0):
    """keys: [(fotograma, posición, objetivo)]. focus: objeto o distancia fija."""
    root = bpy.data.objects.new(name + ' rig', None)
    c.objects.link(root)
    tgt = bpy.data.objects.new(name + ' objetivo', None)
    c.objects.link(tgt)
    tgt.empty_display_size = 0.2
    for f, p, t in keys:
        root.location = p
        root.keyframe_insert('location', frame=f)
        tgt.location = t
        tgt.keyframe_insert('location', frame=f)
    smooth_keys(root)
    smooth_keys(tgt)
    con = root.constraints.new('TRACK_TO')
    con.target = tgt
    con.track_axis = 'TRACK_NEGATIVE_Z'
    con.up_axis = 'UP_Y'
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.sensor_width = sensor
    cd.clip_start = 0.02
    cd.clip_end = 8000
    cd.dof.use_dof = True
    cd.dof.aperture_fstop = fstop
    cd.dof.aperture_blades = 7
    cd.dof.aperture_rotation = 0.3
    if isinstance(focus, (int, float)):
        cd.dof.focus_distance = focus
    else:
        cd.dof.focus_object = focus or tgt
    cam = bpy.data.objects.new(name, cd)
    c.objects.link(cam)
    cam.parent = root
    if shake > 0:
        handheld(cam, shake, seed=seed)
    return cam, tgt


def fill(c, name, loc, target, size, energy, f0, f1, color=(1.0, 0.86, 0.72)):
    """Luz de relleno invisible para la cámara (como un rebote o una pantalla en un rodaje real),
    encendida solo durante su plano."""
    ld = bpy.data.lights.new(name, 'AREA')
    ld.shape = 'DISK'
    ld.size = size
    ld.color = color
    ob = bpy.data.objects.new(name, ld)
    c.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    ob.visible_camera = False
    try:
        ob.visible_glossy = False
    except AttributeError:
        pass
    for f, e in ((f0 - 1, 0.0), (f0, energy), (f1, energy), (f1 + 1, 0.0)):
        ld.energy = e
        ld.keyframe_insert('energy', frame=f)
    for fc in fcurves_of(ld):
        for kp in fc.keyframe_points:
            kp.interpolation = 'CONSTANT'
    return ob


def build(main, ctx):
    from . import tunel, vegetacion
    c = coll('Camaras', main)
    scene = bpy.context.scene
    cams = []
    px, py, pz = tunel.PUDDLE_DROP
    L = cfg.LOCO_FRONT

    # 1. Gota: macro a ras del charco, la gota cae en el haz de luz
    cam, _ = rig(c, '01 Gota', [
        (1, (px + 0.35, py - 1.0, 0.2), (px, py, pz + 0.04)),
        (144, (px + 0.28, py - 0.82, 0.19), (px, py, pz + 0.06)),
    ], lens=65, fstop=2.0, focus=None, shake=0.0015, seed=1)
    cams.append(cam)

    # 2. Vía: travelling a ras de los carriles hacia la locomotora
    cam, _ = rig(c, '02 Via', [
        (145, (0.05, -3.0, 0.62), (0.0, 60, 2.8)),
        (432, (-0.1, 15.0, 0.85), (0.1, 70, 2.6)),
    ], lens=24, fstop=4.0, focus=18.0, shake=0.004, seed=2)
    cams.append(cam)

    # 3. Locomotora: lateral, de la caja de humos a la cabina y el árbol
    cam, _ = rig(c, '03 Locomotora', [
        (433, (-3.95, L + 6.0, 0.95), (0.3, L - 2.0, 2.2)),
        (672, (-3.9, L - 12.5, 1.7), (0.2, cfg.CAB_Y + 0.5, 4.6)),
    ], lens=20, fstop=4.0, focus=4.8, shake=0.004, seed=3)
    cams.append(cam)

    # 4. Rueda: detalle de las ruedas motrices y bielas
    cam, _ = rig(c, '04 Rueda', [
        (673, (-2.15, L - 3.6, 0.85), (-0.8, L - 6.6, 1.15)),
        (816, (-2.05, L - 5.2, 0.95), (-0.8, L - 7.6, 1.2)),
    ], lens=40, fstop=2.2, focus=2.6, shake=0.003, seed=4)
    cams.append(cam)

    # 5. Placa: frente de la locomotora, de la placa al farol
    cam, _ = rig(c, '05 Placa', [
        (817, (0.55, L + 2.4, 1.95), (0.0, L - 0.92, 2.32)),
        (936, (0.45, L + 2.1, 2.55), (0.0, L - 0.95, 3.55)),
    ], lens=50, fstop=2.0, focus=3.3, shake=0.003, seed=5)
    cams.append(cam)

    # 6. Hacia la luz: de la locomotora a la boca, salida al viaducto y grúa sobre el valle
    cam, _ = rig(c, '06 Hacia la luz', [
        (937, (0.45, L + 2.0, 2.3), (0.0, 100, 3.0)),
        (1040, (0.35, L + 18, 2.35), (0.0, 110, 3.0)),
        (1150, (0.25, 96.5, 2.5), (0.0, 140, 3.0)),
        (1235, (0.1, 110.0, 3.4), (0.0, 200, 1.0)),
        (1330, (-8.0, 130.0, 4.5), (0.0, 212, -8.0)),
        (1450, (-55.0, 150.0, -4.0), (0.0, 214, -24.0)),
        (1560, (-135.0, 162.0, -16.0), (0.0, 222, -30.0)),
    ], lens=24, fstop=5.6, focus=None, shake=0.0035, seed=6)
    # el foco va al objetivo de la grúa salvo dentro del túnel
    cam.data.dof.focus_object = None
    for f, d in ((937, 8.0), (1150, 30.0), (1235, 60.0), (1450, 85.0), (1560, 150.0)):
        cam.data.dof.focus_distance = d
        cam.data.dof.keyframe_insert('focus_distance', frame=f)
    cams.append(cam)

    # 7. Plano final: desde el otro lado del valle, la boca del túnel iluminada por el sol bajo
    cam, _ = rig(c, '07 Ultima parada', [
        (1561, (40.0, 266.0, 31.0), (-2.0, 104.0, 6.0)),
        (1800, (33.0, 246.0, 25.0), (-2.0, 102.0, 5.0)),
    ], lens=45, fstop=8.0, focus=150.0, shake=0.0015, seed=7)
    cams.append(cam)

    # rellenos (rebote cálido del suelo iluminado)
    fill(c, 'Relleno via', (-1.5, 4.0, 0.6), (0, 25, 1.5), 2.5, 18, 145, 432)
    fill(c, 'Relleno locomotora', (-4.2, L - 4.0, 0.5), (0, L - 6.0, 2.0), 3.0, 30, 433, 672)
    fill(c, 'Relleno rueda', (-2.6, L - 7.5, 0.35), (-0.8, L - 6.5, 1.1), 1.5, 10, 673, 816)
    fill(c, 'Relleno placa', (1.6, L + 2.6, 0.6), (0, L - 0.9, 2.6), 1.5, 9, 817, 936)
    fill(c, 'Relleno gota', (px + 1.2, py - 0.6, 0.7), (px, py, pz), 0.8, 1.2, 1, 144)

    # marcadores con cámara: cada plano corta en su fotograma
    for (name, f0, f1), cam in zip(SHOTS, cams):
        m = scene.timeline_markers.new(name, frame=f0)
        m.camera = cam
    scene.camera = cams[0]

    # exposición: dentro del túnel se abre el diafragma; al salir se cierra (como una cámara real)
    vs = scene.view_settings
    expo = [(1, 0.7), (144, 0.7), (145, 2.0), (433, 1.9), (673, 2.0), (817, 1.9), (937, 1.9), (1100, 1.6),
            (EXIT_FRAMES[0], 1.1), (EXIT_FRAMES[1], 0.0), (1560, 0.0), (1561, 0.15), (1800, 0.15)]
    for f, e in expo:
        vs.exposure = e
        vs.keyframe_insert('exposure', frame=f)
    for fc in fcurves_of(scene):
        if 'exposure' in fc.data_path:
            for kp in fc.keyframe_points:
                kp.interpolation = 'BEZIER'
            # cortes secos de exposición entre planos
            for kp in fc.keyframe_points:
                if int(kp.co.x) in (144, 432, 672, 816, 936, 1560):
                    kp.interpolation = 'CONSTANT'
    return {'shots': SHOTS, 'cams': cams}
