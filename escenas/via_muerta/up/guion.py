"""La cámara del corto: todo en primera persona. Una sola cámara a la altura de los ojos del
personaje, que sigue el hueso de la cabeza (sus pasos, cuando mira a los lados, la escalera, la
carrera, la cabina...). El movimiento se estabiliza un poco, como hace la mirada de verdad, y en
los momentos clave la mirada se va sola hacia el monstruo. La cabeza, la capucha y el frontal no
se ven en cámara (sí su sombra y su luz); el cuerpo, los brazos y las piernas sí.

También anima la exposición (los ojos se acostumbran a la oscuridad del túnel) y el anochecer
del cielo, y pone marcadores con los momentos de la historia (render.py --prueba los usa)."""
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


# ------------------------------------------------------------------ primera persona
LENS = 20.0                                  # ~84° de campo horizontal, como un juego en primera persona
EYE = Matrix.Translation((0, -0.075, 1.665)) @ Euler((math.radians(89), 0, math.pi)).to_matrix().to_4x4()
DOOR = (-2.3, 0.4, 3.0)                     # asomado a la puerta izquierda de la cabina (y relativo a BOARD_Y)


def head_track(arm, frames):
    """Matriz de los ojos (mundo) en cada fotograma. Solo se evalúa la colección del personaje."""
    sc = bpy.context.scene
    keep = arm.users_collection[0].name
    saved = []

    def has(lc):
        return lc.name == keep or any(has(ch) for ch in lc.children)

    def excl(lc):
        for ch in lc.children:
            if ch.name == keep:
                continue
            if has(ch):
                excl(ch)
            else:
                saved.append((ch, ch.exclude))
                ch.exclude = True
    excl(bpy.context.view_layer.layer_collection)
    pb = arm.pose.bones['cabeza']
    binv = arm.data.bones['cabeza'].matrix_local.inverted()
    out = []
    for f in frames:
        sc.frame_set(f)
        out.append(arm.matrix_world @ pb.matrix @ binv @ EYE)
    for lc, v in reversed(saved):
        lc.exclude = v
    sc.frame_set(1)
    return out


def gsmooth(X, sigma, cuts):
    """Filtro gaussiano por tramos (no mezcla a través de los cortes)."""
    r = int(3 * sigma) + 1
    k = np.arange(-r, r + 1)
    w = np.exp(-k ** 2 / (2 * sigma ** 2))
    w /= w.sum()
    out = X.copy()
    bounds = [0] + sorted(cuts) + [len(X)]
    for a, b in zip(bounds, bounds[1:]):
        if b - a < 2:
            continue
        P = np.pad(X[a:b], ((r, r), (0, 0)), mode='edge')
        for d in range(X.shape[1]):
            out[a:b, d] = np.convolve(P[:, d], w, mode='valid')
    return out


def env(t, t0, t1, ramp):
    return smoothstep(t0, t0 + ramp, t) * (1.0 - smoothstep(t1 - ramp, t1, t))


def attention(ev):
    """Momentos en que la mirada se va hacia algo: (t0, t1, rampa, peso, objetivo(t))."""
    P = tren.P
    L = [
        (ev['asoma'] + 0.3, ev['corre'] + 0.3, 0.8, 0.9, mon_face),                  # se asoma, cae y ruge
        # en el túnel, asomado: viene detrás, a la luz del farol de cola
        (P['t1'] + 2.3, P['t_boca'] - 0.9, 0.7, 0.9, lambda t: mon_pos(t) + Vector((0, 0, 0.4))),
        (ev['se_asoma'] + 0.3, ev['se_asoma'] + 5.3, 0.7, 0.95, lambda t: mon_pos(t) + Vector((0, 0, 0.4))),
        # asomado hacia delante: la vía se acaba en el puente roto
        (ev['mira_delante'] - 0.6, ev['freno'] - 0.3, 0.6, 0.85, lambda t: Vector((0.0, cfg.GAP[0] + 2.0, cfg.RAIL_TOP))),
        (P.get('t_tip', P['te'] + 1.4) + 0.4, P.get('t_impacto', P['te'] + 5) + 1.0, 0.9, 1.0, mon_face),
    ]
    for tt in ev.get('mira_corriendo', []):
        L.append((tt - 0.35, tt + 0.75, 0.3, 0.9, lambda t: mon_pos(t) + Vector((0, 0, 0.3))))
    return L


def pov_camera(cam, arm, ev, t_end):
    from .historia import BOARD_Y
    P = tren.P
    frames = A.frames_range(-0.05, t_end + 0.05)
    ts = [A.time_of(f) for f in frames]
    M = head_track(arm, frames)
    pos = np.array([m.translation[:] for m in M])
    fw = np.array([(m.to_3x3() @ Vector((0, 0, -1)))[:] for m in M])
    up = np.array([(m.to_3x3() @ Vector((0, 1, 0)))[:] for m in M])
    cut = [frames.index(f) for f in frames if abs(A.time_of(f) - ev['corte_bajada']) < 0.5 / cfg.FPS]
    pos = gsmooth(pos, 1.6, cut)
    fw = gsmooth(fw, 2.6, cut)
    up = gsmooth(up, 3.5, cut)
    att = attention(ev)
    t_tip = P.get('t_tip', P['te'] + 1.4)
    door = Vector((DOOR[0], BOARD_Y + DOOR[1], DOOR[2]))
    locs, quats = [], []
    Z = Vector((0, 0, 1))
    for i, t in enumerate(ts):
        p = Vector(pos[i])
        # al volcar se asoma por la puerta de la cabina para ver hacia atrás
        k = max(smoothstep(t_tip - 0.2, t_tip + 0.8, t),                       # asomado por la puerta:
                env(t, P['t1'] + 2.0, P['t_boca'] - 0.6, 0.8),                     # atrás, en el túnel
                env(t, ev['se_asoma'] - 0.2, ev['freno'] - 0.1, 0.8))              # atrás y luego delante
        if k > 0:
            p = p.lerp(maq(t, door), k)
        F = Vector(fw[i]).normalized()
        for t0, t1, ramp, wgt, fn in att:
            if t0 - 0.01 <= t <= t1 + 0.01:
                w = env(t, t0, t1, ramp) * wgt
                if w > 0:
                    D = (fn(t) - p).normalized()
                    F = (Quaternion().slerp(F.rotation_difference(D), w) @ F).normalized()
        # los ojos mantienen el horizonte (salvo cuando todo se cae)
        lev = 0.65 * (1.0 - smoothstep(t_tip - 0.3, t_tip + 0.6, t))
        U = Vector(up[i]).lerp(Z, lev)
        X = F.cross(U).normalized()
        Y = (-F).cross(X).normalized()
        R = Matrix((X, Y, -F)).transposed()
        sh = Euler((nz(t, 3, 0.7) * 0.004 + nz(t, 8, 2.3) * 0.0012, nz(t, 4, 0.6) * 0.004, nz(t, 5, 0.5) * 0.002))
        quats.append(R.to_quaternion() @ sh.to_quaternion())
        locs.append(p)
    A.bake_obj(cam, frames, locs, quats)


def hide_head(arm):
    """La cabeza (con su capucha y su frontal) no se ve en cámara: sí da sombra y luz."""
    for o in bpy.data.objects:
        if o.parent == arm and o.parent_type == 'BONE' and o.parent_bone == 'cabeza' and o.type == 'MESH':
            o.visible_camera = False


def beats(ev):
    """Momentos de la historia (marcadores): (nombre, t)."""
    P = tren.P
    B = [('Monte', 0.0), ('Camino', 12.0), ('Pozo', ev['llega_pozo']), ('Bajada', ev['corte_bajada']),
         ('Tunel', ev['pisa_suelo']), ('Camina', ev['empieza_andar']), ('Para', ev['ruido1'] - 4.0),
         ('Sonido', ev['ruido1']), ('Mira atras', ev['mira_atras']), ('Se asoma', ev['asoma'] + 3.0),
         ('Cara', ev['asoma'] + 8.0), ('Cae', ev['grito'] - 0.6), ('Corre', ev['corre']),
         ('Techo', ev['techo']), ('Locomotora', ev['llega_loco']), ('Regulador', ev['regulador'] - 0.8),
         ('Arranca', P['t1'] + 1.0), ('Boca', P['t_boca'] - 1.0), ('Lo ve', ev['ve_monstruo']),
         ('Delante', ev['mira_delante']), ('Freno', ev['freno']), ('Vuelca', P.get('t_tip', P['te'] + 1.4)),
         ('Caida', P.get('t_caida', P['te'] + 2.4)), ('Ruge', ev['grito_final'] - 0.3)]
    if ev.get('mira_corriendo'):
        B.append(('Mira atras corriendo', ev['mira_corriendo'][0]))
    return sorted(B, key=lambda b: b[1])


def build(main, ctx):
    global PERS, MON
    H = ctx['historia']
    PERS = Samples(H['pers'])
    MON = Samples(H['mon'])
    ev = dict(H['EV'])
    c = coll('Camaras', main)
    sc = bpy.context.scene
    arm = ctx['personaje']['arm']
    P = tren.P
    t_imp = P.get('t_impacto', P['te'] + 5)
    # la imagen se corta a negro en el golpe; el resto (rugido arriba, título) es negro del montaje
    t_cut = t_imp
    cam = new_cam(c, 'Ojos', LENS, 0)
    cam.data.clip_start = 0.06
    pov_camera(cam, arm, ev, t_cut)
    hide_head(arm)
    sc.camera = cam
    SHOTS.clear()
    B = beats(ev)
    for k, (n, t0) in enumerate(B):
        t1 = B[k + 1][1] if k + 1 < len(B) else t_cut
        SHOTS.append(('%02d %s' % (k + 1, n), t0, t1, cam, 0.0))
        m = sc.timeline_markers.new(SHOTS[-1][0], frame=max(1, int(round(A.frame_of(t0)))))
        m.camera = cam
    # los ojos se acostumbran: exposición suave entre el monte al anochecer, el pozo y el túnel
    tb = P['t_boca']
    # (en el salto de tiempo del brocal a la escalera, un parpadeo a negro)
    cb = ev['corte_bajada']
    ex = [(0.0, 1.2), (cb - 0.45, 1.4), (cb - 0.08, -6.0), (cb + 0.12, -6.0), (cb + 0.6, 2.0), (ev['pisa_suelo'], 2.4),
          (tb - 0.5, 2.4), (tb + 2.5, 1.7), (t_cut, 1.8)]
    A.bake_prop(sc, 'view_settings.exposure', ex)
    # el cielo se va apagando: del último resplandor a casi noche
    w = sc.world
    if w and w.node_tree and 'Atardecer' in w.node_tree.nodes:
        A.bake_prop(w.node_tree, 'nodes["Atardecer"].outputs[0].default_value',
                    [(0.0, 1.0), (ev['corte_bajada'], 0.8), (tb, 0.4), (t_cut, 0.32)])
    sc.frame_end = int(round(A.frame_of(t_cut)))
    ajustes.FRAMES = sc.frame_end
    print('  primera persona: %.1f s (%d fotogramas), %d momentos' % (t_cut, sc.frame_end, len(SHOTS)))
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
