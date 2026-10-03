"""Los planos del corto: una cámara por plano, con su movimiento calculado a partir de la
animación (siguen al personaje, al monstruo o al tren), cámara en mano, foco y exposición.
Cada plano pone un marcador en la línea de tiempo que activa su cámara (render.py los usa).

Los planos subjetivos (punto de vista del personaje) cuelgan del hueso de la cabeza; durante
esos planos la cabeza, la capucha y el frontal no se ven en cámara (sí su sombra y su luz)."""
import bpy, math
import numpy as np
from mathutils import Vector, Matrix, Quaternion, Euler
from . import cfg, anim as A, tren, ajustes
from .anim import nz, smoothstep, lerp
from .util import coll

SHOTS = []      # (nombre, t0, t1, cámara)
TITLE = 3.5     # segundos de negro con el título al final (los pone el montaje)


# ------------------------------------------------------------------ muestras de la animación
class Samples:
    def __init__(self, d):
        self.ts = np.array(d['ts'])
        self.d = d

    def i(self, t):
        return int(np.clip(round((t - self.ts[0]) * cfg.FPS), 0, len(self.ts) - 1))

    def M(self, t):
        i = self.i(t)
        return Matrix.Translation(self.d['locs'][i]) @ Quaternion(self.d['quats'][i]).to_matrix().to_4x4()

    def get(self, key, t):
        return Vector(self.d[key][self.i(t)])


PERS = MON = None


def root(t):
    return PERS.M(t).translation.copy()


def head(t):
    return PERS.M(t) @ Vector((0, -0.03, 1.6))


def fwd(t):
    return (PERS.M(t).to_3x3() @ Vector((0, -1, 0))).normalized()


def mon_pos(t):
    return MON.M(t).translation.copy()


def mon_face(t):
    from .monstruo import FACE_Y
    return MON.M(t) @ Vector((0, FACE_Y, 0.05))


def maq(t, p):
    return tren.group_matrix('maq', t) @ Vector(p)


def t_at_y(y, t0, t1):
    """Primer instante (entre t0 y t1) en que el personaje pasa por la coordenada y."""
    for t in np.arange(t0, t1, 1 / cfg.FPS):
        if root(t).y >= y:
            return float(t)
    return t1


# ------------------------------------------------------------------ cámaras
def new_cam(c, name, lens, fstop):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.sensor_width = 36.0
    cd.clip_start = 0.03
    cd.clip_end = 6000
    cd.dof.use_dof = fstop > 0
    cd.dof.aperture_fstop = max(fstop, 0.5)
    cd.dof.aperture_blades = 7
    cd.dof.aperture_rotation = 0.3
    ob = bpy.data.objects.new(name, cd)
    c.objects.link(ob)
    return ob


def bake_world(cam, t0, t1, fn, shake=0.004, seed=0, roll=0.0, focus=None):
    """fn(t) -> (posición, objetivo). Bakea posición, giro (con cámara en mano) y foco."""
    frames = A.frames_range(t0 - 0.1, t1 + 0.1)
    locs, quats, foc = [], [], []
    for f in frames:
        t = A.time_of(f)
        p, tg = fn(t)
        p, tg = Vector(p), Vector(tg)
        d = tg - p
        q = d.to_track_quat('-Z', 'Y')
        sh = Euler((nz(t, seed, 0.9) * shake + nz(t, seed + 5, 3.1) * shake * 0.25,
                    nz(t, seed + 1, 0.8) * shake + nz(t, seed + 6, 2.7) * shake * 0.25,
                    roll + nz(t, seed + 2, 0.5) * shake * 0.6))
        q = q @ sh.to_quaternion()
        locs.append(p)
        quats.append(q)
        foc.append(d.length if focus is None else focus(t, p))
    A.bake_obj(cam, frames, locs, quats)
    A.bake(cam.data, 'dof.focus_distance', frames, foc)


def pov(cam, arm, t0, t1, shake=0.006, seed=0, pitch=-6.0):
    """Cámara subjetiva colgada del hueso de la cabeza (a la altura de los ojos)."""
    b = arm.data.bones['cabeza']
    tail = b.matrix_local @ Matrix.Translation((0, b.length, 0))
    rest = Matrix.Translation((0, -0.075, 1.665)) @ Euler((math.radians(90 + pitch), 0, math.pi)).to_matrix().to_4x4()
    cam.parent = arm
    cam.parent_type = 'BONE'
    cam.parent_bone = 'cabeza'
    cam.matrix_parent_inverse = tail.inverted()
    cam.matrix_basis = rest
    frames = A.frames_range(t0 - 0.1, t1 + 0.1)
    base = rest.to_quaternion()
    quats = []
    for f in frames:
        t = A.time_of(f)
        sh = Euler((nz(t, seed, 1.1) * shake, nz(t, seed + 1, 0.9) * shake, nz(t, seed + 2, 0.6) * shake * 0.5))
        quats.append(base @ sh.to_quaternion())
    A.bake_obj(cam, frames, quats=quats)
    cam.data.dof.focus_distance = 2.5


def hide_head_in(arm, ranges):
    """Durante los planos subjetivos la cabeza no se ve en cámara (pero sigue dando sombra)."""
    obs = [o for o in bpy.data.objects if o.parent == arm and o.parent_type == 'BONE' and o.parent_bone == 'cabeza'
           and o.type == 'MESH']
    for o in obs:
        keys = [(-1.0, 1.0)]
        for t0, t1 in ranges:
            keys += [(t0 - 0.01, 1.0), (t0, 0.0), (t1, 0.0), (t1 + 0.01, 1.0)]
        o.visible_camera = True
        A.bake(o, 'visible_camera', [A.frame_of(t) for t, v in keys], [v for t, v in keys], interp='CONSTANT')


# ------------------------------------------------------------------ guion de planos
def plan(ev):
    """Lista de planos: (nombre, t_inicio, lente, f, cámara en mano, exposición, kind, args)."""
    from .historia import WALK_STOP_Y, H4, BOARD_Y
    from .tunel import top_z
    sx, sy = cfg.SHAFT
    gz = ev.get('gz', 9.6)
    hx, hy = H4
    vz = cfg.vault_z(hx)
    P = tren.P
    t_lad = ev['corte_bajada']
    t_fl = ev['pisa_suelo']
    t_w = ev['empieza_andar']
    t106 = t_at_y(-106.0, t_w, ev['para'])
    t93 = t_at_y(-91.5, t_w, ev['para'])
    t_look = ev['se_asoma']
    t_fwd = t_look + 5.8
    edge = cfg.GAP[0] - 2.8

    def g(x, y, h):
        return Vector((x, y, top_z(x, y) + h))
    S = []

    def shot(name, t0, lens, fstop, shake, fn=None, kind='mundo', exp=1.6, **kw):
        S.append(dict(name=name, t0=t0, lens=lens, fstop=fstop, shake=shake, fn=fn, kind=kind, exp=exp, kw=kw))
    # Acto 1 · el monte
    c1 = g(16.0, -146.0, 7.0)
    shot('Monte', 0.0, 55, 2.8, 0.0015, lambda t: (c1 + Vector((-0.12, 0.2, -0.02)) * t, head(t) + Vector((0, 0, -0.4))), exp=2.1)
    p2 = root(11.8)
    side = Vector((-fwd(11.8).y, fwd(11.8).x, 0)).normalized()
    c2 = p2 + side * 1.3 + fwd(11.8) * 1.6
    c2.z = top_z(c2.x, c2.y) + 0.32
    shot('Camino', 8.0, 26, 2.2, 0.003, lambda t: (c2, root(t) + Vector((0, 0, 0.35))), exp=2.0)
    c3 = g(sx + 3.0, sy - 2.6, 1.45)
    shot('Alcantarilla', 15.5, 32, 2.8, 0.0025, lambda t: (c3, head(t).lerp(Vector((sx, sy, gz + 0.3)), 0.35)), exp=2.0)
    shot('Pozo', ev['llega_pozo'] + 1.0, 0, 0, 0.007, kind='pov', exp=2.2)
    # Acto 2 · la bajada
    shot('Bajada', t_lad, 16, 4.0, 0.002,
         lambda t: (Vector((sx + 0.1, sy + 0.08, 0.95)), Vector((cfg.LADDER_X + 0.15, sy, gz))), exp=2.4)
    shot('Peldanos', t_lad + 7.5, 24, 2.0, 0.003,
         lambda t: (Vector((sx - 0.15, sy + 0.42, PERS.get('hand_R', t).z + 0.22)), PERS.get('hand_R', t)), exp=2.2)
    shot('Tunel', t_lad + 12.5, 24, 4.0, 0.0015,
         lambda t: (Vector((2.0, sy + 10.0, 0.9)), Vector((-3.9, sy, 1.8))), exp=2.5)
    # Acto 3 · el túnel
    shot('Nada', t_fl + 1.2, 28, 2.8, 0.004,
         lambda t: (Vector((1.6, sy - 2.2, 1.35)), head(t)), exp=2.4)
    shot('Camina', t_w + 1.5, 40, 2.0, 0.004,
         lambda t: (head(t - 0.3) + Vector((0.15, 3.0, 0.05)), head(t)), exp=2.2)
    shot('Traviesas', t_w + 11.0, 30, 2.0, 0.003,
         lambda t: (Vector((root(t - 0.2).x + 1.25, root(t - 0.2).y + 0.9, 0.62)), root(t) + Vector((0, 0.3, 0.2))),
         exp=2.2)
    shot('Luna', t106, 40, 4.0, 0.001,
         lambda t: (Vector((3.1, -82.0, 1.1)), Vector((0.0, -101.0, 1.5))), exp=2.4)
    shot('Respira', t93, 50, 1.8, 0.004,
         lambda t: (head(t - 0.2) + Vector((1.05, 0.35, 0.02)), head(t)), exp=2.2)
    shot('Sonido', ev['ruido1'] - 3.5, 45, 2.0, 0.0035,
         lambda t: (Vector((0.25, WALK_STOP_Y + 1.35, 1.62)), head(t)), exp=2.2)
    # Acto 4 · se asoma
    shot('Detras', ev['mira_atras'], 0, 0, 0.007, kind='pov', exp=2.3)
    shot('Se asoma', ev['asoma'] + 4.8, 30, 2.8, 0.0025,
         lambda t: (Vector((0.55, WALK_STOP_Y + 1.5, 1.25)), Vector((hx, hy, vz - 0.6))), exp=2.5)
    shot('Cara', ev['asoma'] + 8.6, 60, 2.0, 0.002,
         lambda t: (Vector((hx + 0.5, hy + 4.2, 2.9)).lerp(Vector((hx + 0.45, hy + 3.4, 3.4)), smoothstep(ev['asoma'] + 8.6, ev['asoma'] + 12.2, t)),
                    mon_face(t)), exp=2.6)
    shot('Miedo', ev['asoma_fin'] + 0.6, 45, 2.0, 0.005,
         lambda t: (Vector((0.15, WALK_STOP_Y - 1.25, 1.6)), head(t)), exp=2.2)
    # Acto 5 · la persecución
    shot('Cae', ev['cae'], 22, 4.0, 0.004,
         lambda t: (Vector((2.4, WALK_STOP_Y + 5.0, 0.7)), Vector((hx * 0.5, hy + 1.0, 3.2))), exp=2.5)
    shot('Corre', ev['persigue'] + 0.6, 26, 2.8, 0.012,
         lambda t: (root(t - 0.15) + Vector((0.4, -2.6, 1.55)), head(t) + Vector((0, 4.0, -0.25))), exp=2.4)
    shot('Paredes', ev['persigue'] + 5.2, 30, 2.8, 0.01,
         lambda t: (root(t) + Vector((0.6, 5.2, 1.45)), head(t) + Vector((0, -3.0, 0.6))), exp=2.5)
    yt = mon_pos(ev['techo'] + 1.5).y
    shot('Techo', ev['techo'] - 1.5, 18, 4.0, 0.004,
         lambda t: (Vector((-1.2, yt + 6.0, 0.55)), mon_pos(t)), exp=2.6)
    shot('Locomotora', ev['techo'] + 3.0, 0, 0, 0.014, kind='pov', exp=2.5)
    shot('Tender', ev['llega_loco'] - 3.8, 24, 2.8, 0.009,
         lambda t: (Vector((-3.75, root(t).y + 1.4, 1.45)), head(t) + Vector((0.4, 2.0, -0.1))), exp=2.5)
    # Acto 6 · el tren (las cámaras de la cabina viajan con la locomotora)
    shot('Cabina', ev['llega_loco'] - 0.2, 18, 2.8, 0.004,
         lambda t: (maq(t, (0.95, 47.95, 3.15)), maq(t, (-1.3, BOARD_Y, 2.3))), exp=2.5)
    shot('Regulador', ev['regulador'] - 1.2, 30, 2.0, 0.003,
         lambda t: (maq(t, (-0.75, 46.25, 3.05)), maq(t, (0.25, 47.05, 2.55))), exp=2.4)
    shot('Ruedas', P['t0'] - 0.1, 30, 2.8, 0.003,
         lambda t: (Vector((-2.6, 50.0, 0.65)), Vector((-0.8, 50.8 + 0.6 * smoothstep(P['t1'], P['t1'] + 3, t), 0.95))), exp=2.5)
    shot('Arranca', P['t1'] + 3.0, 35, 2.8, 0.003,
         lambda t: (Vector((1.3, 86.0, 1.1)), maq(t, (0.0, 57.0, 2.6))), exp=2.5)
    shot('Boca', tren.t_of_s(24.0), 28, 4.0, 0.002,
         lambda t: (Vector((7.5, 128.0, 4.0)), Vector((0.0, 101.0, 3.0)).lerp(maq(t, (0, 52, 2.5)), 0.5 * smoothstep(P['t_boca'] - 1, P['t_boca'] + 2, t))),
         exp=2.2)
    shot('Mira atras', t_look - 0.6, 28, 2.8, 0.005,
         lambda t: (maq(t, (-2.35, 49.6, 2.75)), maq(t, (-1.3, BOARD_Y, 2.75))), exp=2.3)
    shot('Lo ve', t_look + 1.6, 45, 2.8, 0.006,
         lambda t: (maq(t, (-1.95, 46.3, 2.95)), mon_pos(t) + Vector((0, 0, 0.3))), exp=2.3)
    shot('Delante', t_fwd, 32, 2.8, 0.005,
         lambda t: (maq(t, (-0.45, 46.45, 3.05)), maq(t, (0.0, 80.0, 1.8))), exp=2.2)
    shot('Freno', P['tb'] - 0.3, 26, 2.0, 0.008,
         lambda t: (maq(t, (0.35, 46.3, 2.95)), maq(t, (-0.62, 46.9, 2.45))), exp=2.3)
    # Acto 7 · la caída
    shot('Caida', P['te'] - 1.0, 45, 5.6, 0.0015,
         lambda t: (Vector((55.0, 196.0, -6.0)), Vector((0.0, 213.0, -3.0))), exp=2.1)
    shot('Abismo', P.get('t_caida', P['te'] + 2) + 1.2, 28, 4.0, 0.004,
         lambda t: (Vector((1.8, 209.5, 1.9)), maq(t, tren.PIV_M)), exp=2.1)
    shot('Borde', P.get('t_impacto', P['te'] + 5) + 1.5, 40, 2.8, 0.002,
         lambda t: (Vector((2.4, edge + 8.5, 1.4)).lerp(Vector((2.0, edge + 7.2, 1.7)), smoothstep(ev['grito_final'] - 2, ev['fin'], t)),
                    mon_face(t)), exp=2.2)
    return S


def build(main, ctx):
    global PERS, MON
    H = ctx['historia']
    PERS = Samples(H['pers'])
    MON = Samples(H['mon'])
    ev = dict(H['EV'])
    ev['gz'] = ctx['pozo']['gz']
    c = coll('Camaras', main)
    sc = bpy.context.scene
    arm = ctx['personaje']['arm']
    S = plan(ev)
    t_end = ev['fin']
    SHOTS.clear()
    pov_ranges = []
    for k, s in enumerate(S):
        t0 = s['t0']
        t1 = S[k + 1]['t0'] if k + 1 < len(S) else t_end
        name = '%02d %s' % (k + 1, s['name'])
        cam = new_cam(c, name, s['lens'] or 20, s['fstop'])
        if s['kind'] == 'pov':
            cam.data.lens = 18
            cam.data.dof.use_dof = False
            pov(cam, arm, t0, t1, shake=s['shake'], seed=k * 7)
            pov_ranges.append((t0, t1))
        else:
            bake_world(cam, t0, t1, s['fn'], shake=s['shake'], seed=k * 7)
        SHOTS.append((name, t0, t1, cam, s['exp']))
        m = sc.timeline_markers.new(name, frame=int(round(A.frame_of(t0))))
        m.camera = cam
    sc.camera = SHOTS[0][3]
    hide_head_in(arm, pov_ranges)
    # exposición por plano (de noche: se sube un poco en el túnel)
    A.bake(sc, 'view_settings.exposure', [A.frame_of(t0) for n, t0, t1, cm, e in SHOTS], [e for n, t0, t1, cm, e in SHOTS],
           interp='CONSTANT')
    sc.frame_end = int(round(A.frame_of(t_end)))
    ajustes.FRAMES = sc.frame_end
    print('  %d planos, %.1f s (%d fotogramas)' % (len(SHOTS), t_end, sc.frame_end))
    for n, t0, t1, cm, e in SHOTS:
        print('   %-18s %6.1f - %6.1f  (%4.1f s)' % (n, t0, t1, t1 - t0))
    return {'planos': SHOTS}


def timing(ctx):
    """Datos para el sonido y el montaje (timing.json)."""
    H = ctx['historia']
    return {
        'fps': cfg.FPS,
        'frames': bpy.context.scene.frame_end,
        'titulo': {'inicio': H['EV']['fin'], 'duracion': TITLE},
        'planos': [{'nombre': n, 'inicio': round(t0, 3), 'fin': round(t1, 3)} for n, t0, t1, cm, e in SHOTS],
        'eventos': {k: (round(v, 3) if isinstance(v, float) else v) for k, v in H['EV'].items()},
        'pasos': [(round(t, 3), k) for t, k, p in H['steps']],
        'peldanos': [(round(t, 3), k) for t, k in H['rungs']],
        'patas': [round(m[0], 3) for m in H['msteps']],
        'tren': {k: round(float(v), 3) for k, v in tren.P.items() if isinstance(v, (int, float))},
        'ruedas': [round(t, 3) for t in tren.chuffs()] if hasattr(tren, 'chuffs') else [],
    }
