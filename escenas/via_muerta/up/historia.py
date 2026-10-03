"""La historia animada: el personaje (camina, baja por la escalera, mira, corre, sube a la
locomotora, tira del regulador, mira atrás y frena), el monstruo (se asoma por el hundimiento,
cae, ruge, persigue por el suelo, las paredes y la bóveda, y corre por el viaducto) y el tren.

Todo se calcula en Python y se escribe en curvas fotograma a fotograma (anim.bake).
Los tiempos van en segundos de película; EV guarda los instantes clave (los usan las cámaras
y el sonido)."""
import bpy, math
import numpy as np
from mathutils import Vector, Matrix, Quaternion, Euler
from mathutils.bvhtree import BVHTree
from . import cfg, anim as A, tren
from .anim import Track, smoothstep, lerp, nz

EV = {}          # instantes clave
STEPS = []       # pisadas del personaje (t, tipo, posición) para el sonido
MSTEPS = []      # apoyos de las patas del monstruo (t, x, y, z)
RUNGS = []       # golpes en los peldaños (t, mano/pie)
FPS = cfg.FPS

COLLAR_STAND = 1.35      # distancia del centro del pozo a la que se para
WALK_STOP_Y = -79.0      # dónde se para al oír el ruido
BOARD_Y = cfg.CAB_Y - 0.75
CAB_FLOOR = 1.89
H4 = [0.0, -91.0]        # centro real del hundimiento 4 (se lee del túnel al construir)


def snap(t):
    """Redondea al fotograma más cercano (para los cortes)."""
    return round(t * FPS) / FPS


# ------------------------------------------------------------------ geometría del entorno
def bvh_from(prefixes):
    verts, polys = [], []
    dg = bpy.context.evaluated_depsgraph_get()
    for o in bpy.data.objects:
        if o.type != 'MESH' or not o.name.startswith(prefixes):
            continue
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        mw = o.matrix_world
        base = len(verts)
        verts.extend([mw @ v.co for v in me.vertices])
        polys.extend([[base + i for i in p.vertices] for p in me.polygons])
        ev.to_mesh_clear()
    if not verts:
        verts, polys = [Vector((0, 0, -1000)), Vector((1, 0, -1000)), Vector((0, 1, -1000))], [[0, 1, 2]]
    return BVHTree.FromPolygons(verts, polys, all_triangles=False)


GROUND = None
WALLS = None


def in_tunnel(x, y):
    return abs(x) < cfg.HALF_W + 0.3 and cfg.Y0 < y < cfg.Y1


def ground_at(x, y, z_hint=None):
    """Altura del suelo pisable bajo (x, y). Dentro del túnel busca desde poco por encima de la vía
    (si no, encontraría el monte de encima); fuera, desde arriba."""
    if z_hint is None:
        z_hint = 2.5 if in_tunnel(x, y) else 200.0
    hit = GROUND.ray_cast(Vector((x, y, z_hint)), Vector((0, 0, -1)), z_hint + 100.0)
    return hit[0].z if hit[0] is not None else 0.0


def ground_smooth(x, y, z_hint=None):
    """Suelo promediado (para la raíz del cuerpo: que no salte de traviesa en traviesa)."""
    zs = [ground_at(x + dx, y + dy, z_hint) for dx, dy in ((0, 0), (0.2, 0.3), (-0.2, -0.3), (0.2, -0.3), (-0.2, 0.3))]
    return sorted(zs)[2]


# ------------------------------------------------------------------ extremidades por apoyos
class Limb:
    """Pie o mano: apoyos (t_apoyo, t_despegue, posición, orientación, espacio).
    Entre un despegue y el apoyo siguiente se interpola con un arco."""

    def __init__(self, name):
        self.name = name
        self.ev = []

    def plant(self, t_land, t_lift, pos, quat, lift=0.12, space='mundo', cut=False):
        self.ev.append(dict(t0=t_land, t1=t_lift, p=Vector(pos), q=Quaternion(quat), h=lift, sp=space, cut=cut))

    def sort(self):
        self.ev.sort(key=lambda e: e['t0'])
        for a, b in zip(self.ev, self.ev[1:]):
            lim = b['t0'] - (1e-4 if b['cut'] else 0.05)
            if a['t1'] > lim:
                a['t1'] = lim
            if a['t1'] < a['t0']:
                a['t1'] = a['t0']

    def index(self, t):
        ev = self.ev
        lo, hi = 0, len(ev) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if ev[mid]['t0'] <= t:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def at(self, t, to_world):
        ev = self.ev
        if t <= ev[0]['t0']:
            e = ev[0]
            return to_world(e['sp'], t, e['p']), e['q'], 0.0, e['sp']
        i = self.index(t)
        e = ev[i]
        if t <= e['t1'] or i == len(ev) - 1:
            return to_world(e['sp'], t, e['p']), e['q'], 0.0, e['sp']
        n = ev[i + 1]
        u = (t - e['t1']) / max(1e-6, n['t0'] - e['t1'])
        us = u * u * (3 - 2 * u)
        a = to_world(e['sp'], t, e['p'])
        b = to_world(n['sp'], t, n['p'])
        p = a.lerp(b, us) + Vector((0, 0, n['h'] * math.sin(math.pi * u)))
        q = e['q'].slerp(n['q'], us)
        return p, q, u, n['sp']


# ------------------------------------------------------------------ el personaje
def yaw_of(fwd):
    """Giro (rad) del esqueleto para mirar en la dirección fwd (en reposo mira a -Y)."""
    return math.atan2(fwd.x, -fwd.y)


def fwd_of(yaw):
    return Vector((math.sin(yaw), -math.cos(yaw), 0))


def left_of(yaw):
    return Vector((math.cos(yaw), math.sin(yaw), 0))


class Person:
    def __init__(self, P):
        self.arm = P['arm']
        self.tg = P['targets']
        self.root = []          # (t, pos, yaw, espacio)
        self.feet = {'L': Limb('pie.L'), 'R': Limb('pie.R')}
        self.hands = {'L': Limb('mano.L'), 'R': Limb('mano.R')}
        self.spine = []         # (t, {hueso: (giro, cabeceo, alabeo)})
        self.hip_keys = []      # (t, desplazamiento, (giro, cabeceo, alabeo))
        self.mode = []          # (t, modo): 'quieto', 'andar', 'correr', 'manos'
        bpy.context.view_layer.update()
        self.rest_q = {}
        for s in ('L', 'R'):
            for b in ('pie', 'mano'):
                self.rest_q[b + '.' + s] = self.tg[b + '.' + s].matrix_world.to_quaternion()

    def fq(self, side, yaw, pitch=0.0):
        """Orientación del objetivo del pie girada 'yaw' alrededor de Z."""
        return Euler((0, 0, yaw)).to_quaternion() @ Euler((pitch, 0, 0)).to_quaternion() @ self.rest_q['pie.' + side]

    def hq(self, side, yaw, pitch=0.0, roll=0.0):
        return Euler((0, 0, yaw)).to_quaternion() @ Euler((pitch, roll, 0)).to_quaternion() @ self.rest_q['mano.' + side]

    @staticmethod
    def to_world(space, t, p):
        if space == 'maq':
            return tren.group_matrix('maq', t) @ p
        return p

    def key_root(self, t, pos, yaw, space='mundo', ground=True):
        pos = Vector(pos)
        if ground and space == 'mundo':
            pos.z = ground_smooth(pos.x, pos.y)
        self.root.append((t, pos, yaw, space))

    def key_spine(self, t, **bones):
        self.spine.append((t, bones))

    def key_hip(self, t, off=(0, 0, 0), rot=(0, 0, 0)):
        self.hip_keys.append((t, Vector(off), Vector(rot)))

    def key_mode(self, t, m):
        self.mode.append((t, m))

    def foot_at(self, side, pos, yaw, width=0.11, fwd=0.0, space='mundo'):
        X = 1 if side == 'L' else -1
        p = Vector(pos) + left_of(yaw) * (X * width) + fwd_of(yaw) * fwd
        if space == 'mundo':
            p.z = ground_at(p.x, p.y)
        return Vector((p.x, p.y, p.z + 0.095))

    # ------------------------------------------------------------ caminar / correr por una ruta
    def locomote(self, t0, pts, v, L, beta, lift, width, run=False, accel=0.8, decel=0.8, end_close=True, yaw_fn=None):
        """Anda (o corre) por la polilínea pts a velocidad v. Devuelve el instante de llegada."""
        pts = [Vector((p[0], p[1], 0)) for p in pts]
        seg = [0.0]
        for a, b in zip(pts, pts[1:]):
            seg.append(seg[-1] + (b - a).length)
        S = seg[-1]

        def at_s(s):
            s = min(max(s, 0.0), S)
            k = max(0, min(len(pts) - 2, int(np.searchsorted(seg, s) - 1)))
            u = (s - seg[k]) / max(1e-9, seg[k + 1] - seg[k])
            return pts[k].lerp(pts[k + 1], u), (pts[k + 1] - pts[k]).normalized()
        ta, td = v / accel, v / decel
        sa, sd = 0.5 * v * ta, 0.5 * v * td
        if sa + sd > S:
            k = math.sqrt(S / (sa + sd))
            v, ta, td, sa, sd = v * k, ta * k, td * k, sa * k * k, sd * k * k
        tc = (S - sa - sd) / v
        T = ta + tc + td

        def s_of(t):
            t = t - t0
            if t <= 0:
                return 0.0
            if t < ta:
                return 0.5 * (v / ta) * t * t
            if t < ta + tc:
                return sa + v * (t - ta)
            if t < T:
                u = t - ta - tc
                return sa + v * tc + v * u - 0.5 * (v / td) * u * u
            return S

        def t_of(s):
            lo, hi = t0, t0 + T
            for _ in range(40):
                m = (lo + hi) / 2
                if s_of(m) < s:
                    lo = m
                else:
                    hi = m
            return hi

        def yaw_at(t, d):
            return yaw_fn(t, d) if yaw_fn else yaw_of(d)
        # el giro del cuerpo mira un poco por delante (las curvas no son esquinas)
        for f in A.frames_range(t0, t0 + T):
            t = A.time_of(f)
            s = s_of(t)
            p, d = at_s(s)
            ahead, _ = at_s(s + 0.8)
            dd = ahead - p
            if dd.length > 0.05:
                d = dd.normalized()
            self.key_root(t, p, yaw_at(t, d))
        self.key_mode(t0, 'correr' if run else 'andar')
        self.key_mode(t0 + T, 'quieto')
        contacts = []
        n = 0
        while L * (n + 0.5) <= S - 0.25 * L:
            contacts.append(('R' if n % 2 == 0 else 'L', L * (n + 0.5)))
            n += 1
        for side, sc in contacts:
            p, d = at_s(sc)
            yaw = yaw_at(t_of(sc), d)
            pos = self.foot_at(side, p, yaw, width)
            tl = t_of(max(0.0, sc - beta * L))
            self.feet[side].plant(tl, t_of(min(S, sc + beta * L)), pos, self.fq(side, yaw), lift=lift)
            STEPS.append((tl, 'correr' if run else 'andar', pos.copy()))
        if end_close:
            p, d = at_s(S)
            yaw = yaw_at(t0 + T, d)
            order = ('L', 'R') if len(contacts) % 2 else ('R', 'L')
            for k, side in enumerate(order):
                pos = self.foot_at(side, p, yaw)
                tl = t0 + T + 0.1 + 0.25 * k
                self.feet[side].plant(tl, tl + 600, pos, self.fq(side, yaw), lift=lift * 0.6)
                STEPS.append((tl, 'paso', pos.copy()))
        return t0 + T

    def stand(self, t, pos, yaw, width=0.11):
        for side in ('L', 'R'):
            self.feet[side].plant(t, t + 600, self.foot_at(side, pos, yaw, width), self.fq(side, yaw))
        self.key_root(t, pos, yaw)
        self.key_mode(t, 'quieto')

    def turn_in_place(self, t0, t1, pos, yaw0, yaw1):
        """Gira sobre sí mismo con pasitos."""
        n = max(2, int(abs(yaw1 - yaw0) / math.radians(50)) + 1)
        for k in range(n + 1):
            u = k / n
            self.key_root(lerp(t0, t1, u), pos, lerp(yaw0, yaw1, smoothstep(0, 1, u)))
        for k in range(1, n + 1):
            yaw = lerp(yaw0, yaw1, k / n)
            for j, side in enumerate(('R', 'L') if yaw1 > yaw0 else ('L', 'R')):
                tl = lerp(t0, t1, (k - 0.55 + 0.45 * j) / n)
                p = self.foot_at(side, pos, yaw, 0.12)
                self.feet[side].plant(tl, tl + 600, p, self.fq(side, yaw), lift=0.06)
                STEPS.append((tl, 'paso', p.copy()))

    # ------------------------------------------------------------ escalera
    def ladder_down(self, t0, rungs, z_feet0, rate=0.55):
        """Baja por los pates mirando al muro (-X). Empieza en t0 con un corte (ya agarrado).
        Devuelve (instante en que pisa el suelo, posición, giro)."""
        lx = cfg.LADDER_X
        sy = cfg.SHAFT[1]
        yaw = yaw_of(Vector((-1, 0, 0)))
        body_x = lx + 0.37
        step = cfg.RUNG_STEP

        def idx(z):
            return int(np.argmin([abs(r - z) for r in rungs]))
        fi = {'R': idx(z_feet0), 'L': idx(z_feet0) + 1}
        hi = {s: min(fi[s] + 5, len(rungs) - 1) for s in fi}
        q_hand = {s: self.hq(s, yaw, math.radians(-75)) for s in ('L', 'R')}
        q_foot = {s: self.fq(s, yaw, math.radians(-6)) for s in ('L', 'R')}

        def foot_p(side, i):
            X = 1 if side == 'L' else -1
            return Vector((lx + 0.1, sy - X * 0.11, rungs[i] + 0.11))

        def hand_p(side, i):
            X = 1 if side == 'L' else -1
            return Vector((lx + 0.05, sy - X * 0.16, rungs[i] + 0.05))

        def root_now():
            zf = (rungs[max(0, fi['L'])] + rungs[max(0, fi['R'])]) / 2
            return Vector((body_x, sy, zf + 0.01))
        for s in ('L', 'R'):
            self.feet[s].plant(t0, t0 + 0.01, foot_p(s, fi[s]), q_foot[s], cut=True)
            self.hands[s].plant(t0, t0 + 0.01, hand_p(s, hi[s]), q_hand[s], lift=0.0, cut=True)
        self.key_root(t0 - 1e-3, root_now(), yaw, ground=False)
        cyc = 2 * step / rate               # los cuatro miembros bajan dos peldaños
        order = [('R', 'pie'), ('R', 'mano'), ('L', 'pie'), ('L', 'mano')]
        t = t0 + 0.4
        done = False
        for _ in range(80):
            for j, (side, kind) in enumerate(order):
                ts = t + cyc * j / 4
                dur = cyc / 4 * 0.85
                if kind == 'pie':
                    if fi[side] - 2 < 0:
                        done = True
                        break
                    fi[side] -= 2
                    self.feet[side].plant(ts + dur, ts + cyc, foot_p(side, fi[side]), q_foot[side], lift=0.07)
                    RUNGS.append((ts + dur, 'pie'))
                else:
                    hi[side] = max(0, hi[side] - 2)
                    self.hands[side].plant(ts + dur, ts + cyc, hand_p(side, hi[side]), q_hand[side], lift=0.05)
                    RUNGS.append((ts + dur, 'mano'))
                self.key_root(ts + dur, root_now(), yaw, ground=False)
            if done:
                break
            t += cyc
        # del último peldaño al suelo: los dos pies; las manos sueltan
        t_floor = t + 0.35
        ground = ground_smooth(body_x, sy)
        for j, side in enumerate(('R', 'L')):
            X = 1 if side == 'L' else -1
            p = Vector((body_x - 0.04, sy - X * 0.11, 0))
            p.z = ground_at(p.x, p.y) + 0.095
            self.feet[side].plant(t_floor + 0.35 * j, t_floor + 600, p, self.fq(side, yaw), lift=0.1)
            STEPS.append((t_floor + 0.35 * j, 'paso', p.copy()))
        self.key_root(t_floor + 0.55, Vector((body_x, sy, ground)), yaw, ground=False)
        self.key_mode(t0 - 1e-3, 'manos')
        self.key_mode(t_floor + 0.6, 'quieto')
        return t_floor + 0.6, Vector((body_x, sy, ground)), yaw

    # ------------------------------------------------------------ escritura de curvas
    def bake(self, t_from, t_to):
        arm = self.arm
        for lim in list(self.feet.values()) + list(self.hands.values()):
            lim.sort()
        self.root.sort(key=lambda r: r[0])
        rt = np.array([r[0] for r in self.root])
        frames = A.frames_range(t_from, t_to)
        ts = [A.time_of(f) for f in frames]
        hip_tr = Track([(t, (o.x, o.y, o.z, r.x, r.y, r.z)) for t, o, r in self.hip_keys] or [(0, (0,) * 6)])
        bones = ['columna', 'pecho', 'cuello', 'cabeza']
        sp = {}
        for b in bones:
            keys = [(t, d[b]) for t, d in self.spine if b in d]
            sp[b] = Track(keys or [(0, (0, 0, 0))])
        modes = sorted(self.mode, key=lambda m: m[0])
        locs, quats, hip_l, hip_q = [], [], [], []
        sp_q = {b: [] for b in bones}
        feet = {s: ([], []) for s in ('L', 'R')}
        hands = {s: ([], [], []) for s in ('L', 'R')}
        rest_hips = arm.data.bones['cadera'].matrix_local.to_3x3()
        rest_b = {b: arm.data.bones[b].matrix_local.to_3x3() for b in bones}
        for t in ts:
            i = int(np.clip(np.searchsorted(rt, t, side='right') - 1, 0, len(rt) - 1))
            j = min(i + 1, len(rt) - 1)
            r0, r1 = self.root[i], self.root[j]
            if j == i or t <= r0[0]:
                u = 0.0
            else:
                u = min(1.0, (t - r0[0]) / max(1e-6, r1[0] - r0[0]))
            us = u if (r1[0] - r0[0]) < 0.1 else u * u * (3 - 2 * u)
            pos = r0[1].lerp(r1[1], us)
            dyaw = (r1[2] - r0[2] + math.pi) % (2 * math.pi) - math.pi
            yaw = r0[2] + dyaw * us
            space = r1[3] if u > 0.5 else r0[3]
            M = tren.group_matrix('maq', t) if space == 'maq' else Matrix.Identity(4)
            Mw = M @ Matrix.Translation(pos) @ Euler((0, 0, yaw)).to_matrix().to_4x4()
            locs.append(Mw.translation.copy())
            quats.append(Mw.to_quaternion())
            mode = 'quieto'
            for tm, m in modes:
                if tm <= t:
                    mode = m
                else:
                    break
            fz = []
            for s in ('L', 'R'):
                p, q, uu, spc = self.feet[s].at(t, self.to_world)
                if spc == 'maq':
                    q = tren.group_matrix('maq', t).to_quaternion() @ q
                feet[s][0].append(p)
                feet[s][1].append(q)
                fz.append(p.z - 0.095)
            h = hip_tr(t)
            off = Vector(h[:3])
            ph = self._gait_phase(t)
            if mode == 'andar':
                off += Vector((0.012 * math.sin(2 * math.pi * ph), 0, -0.02 - 0.014 * math.cos(4 * math.pi * ph)))
            elif mode == 'correr':
                off += Vector((0.01 * math.sin(2 * math.pi * ph), 0, -0.07 - 0.03 * math.cos(4 * math.pi * ph)))
            # que las piernas lleguen: si un pie está más bajo que la raíz, la cadera baja
            if mode != 'manos':
                need = (min(fz) + 0.015) - Mw.translation.z
                if need < 0:
                    off.z += need
            hip_l.append(rest_hips.inverted() @ off)
            e = Euler((h[4], h[5], h[3]))
            hip_q.append((rest_hips.inverted() @ e.to_matrix() @ rest_hips).to_quaternion())
            for b in bones:
                v = sp[b](t)
                if b == 'pecho':
                    v = v + Vector((0, 0.012 * math.sin(t * (2.6 if mode == 'correr' else 1.5)), 0))
                if b == 'cabeza':
                    v = v + Vector((nz(t, 51, 0.7) * 0.03, nz(t, 52, 0.6) * 0.025, 0))
                e = Euler((v[1], v[2], v[0]), 'ZXY')
                sp_q[b].append((rest_b[b].inverted() @ e.to_matrix() @ rest_b[b]).to_quaternion())
            for s in ('L', 'R'):
                free = self._free_hand(s, t, mode, ph, Mw)
                g = self._grip(self.hands[s], t)
                if g is None:
                    hands[s][0].append(free[0])
                    hands[s][1].append(free[1])
                    hands[s][2].append(0.0)
                else:
                    p, q, w = g
                    hands[s][0].append(free[0].lerp(p, w))
                    hands[s][1].append(free[1].slerp(q, w))
                    hands[s][2].append(w)
        self.samples = dict(ts=ts, locs=locs, quats=quats, hand_L=hands['L'][0], hand_R=hands['R'][0],
                            foot_L=feet['L'][0], foot_R=feet['R'][0])
        A.bake_obj(arm, frames, locs, quats)
        A.bake_pose(arm, 'cadera', frames, quats=hip_q, locs=hip_l)
        for b in bones:
            A.bake_pose(arm, b, frames, quats=sp_q[b])
        for s in ('L', 'R'):
            A.bake_obj(self.tg['pie.' + s], frames, feet[s][0], feet[s][1])
            A.bake_obj(self.tg['mano.' + s], frames, hands[s][0], hands[s][1])
            pb = arm.pose.bones['mano.' + s]
            cr = [c for c in pb.constraints if c.type == 'COPY_ROTATION'][0]
            A.bake(arm, 'pose.bones["mano.%s"].constraints["%s"].influence' % (s, cr.name), frames, hands[s][2])

    def _gait_phase(self, t):
        ev = self.feet['R'].ev
        if not ev:
            return 0.0
        i = self.feet['R'].index(t)
        if i + 1 < len(ev) and ev[i]['t0'] <= t:
            return (t - ev[i]['t0']) / max(1e-6, ev[i + 1]['t0'] - ev[i]['t0'])
        return 0.0

    def _grip(self, limb, t):
        """Agarre activo en t: (pos, quat, peso). Los apoyos se agrupan en tramos
        (huecos de más de 1.5 s) y el peso entra y sale en 0.35 s (o de golpe en un corte)."""
        ev = limb.ev
        if not ev:
            return None
        if not hasattr(limb, 'groups'):
            groups, cur = [], [ev[0]]
            for a, b in zip(ev, ev[1:]):
                if b['t0'] - a['t1'] > 1.5:
                    groups.append(cur)
                    cur = [b]
                else:
                    cur.append(b)
            groups.append(cur)
            limb.groups = groups
        w = 0.0
        for g in limb.groups:
            a0 = g[0]['t0'] - (0.0 if g[0]['cut'] else 0.35)
            b1 = g[-1]['t1'] + 0.35
            if a0 - 1e-6 <= t <= b1:
                win = 1.0 if g[0]['cut'] else smoothstep(a0, a0 + 0.35, t)
                w = win * (1 - smoothstep(b1 - 0.35, b1, t))
                break
        if w <= 0:
            return None
        p, q, uu, spc = limb.at(t, self.to_world)
        if spc == 'maq':
            q = tren.group_matrix('maq', t).to_quaternion() @ q
        return p, q, w

    def _free_hand(self, s, t, mode, ph, Mw):
        """Mano suelta: brazos colgando, balanceo al andar, brazos doblados al correr."""
        X = 1 if s == 'L' else -1
        sw = math.sin(2 * math.pi * ph) * (-X)
        if mode == 'correr':
            loc = Vector((X * 0.23, -0.06 - 0.26 * sw, 1.02 + 0.1 * max(0.0, sw)))
        elif mode == 'andar':
            loc = Vector((X * 0.26, -0.01 - 0.15 * sw, 0.85 + 0.03 * abs(sw)))
        else:
            loc = Vector((X * 0.27, -0.02 + nz(t, 21 + X, 0.3) * 0.015, 0.86))
        return Mw @ loc, Mw.to_quaternion() @ self.rest_q['mano.' + s]


# ------------------------------------------------------------------ guion del personaje
def person_story(P, ctx):
    from . import pozo
    pe = Person(P)
    sx, sy = cfg.SHAFT
    gz = ctx['pozo']['gz']
    rungs = ctx['pozo']['rungs']
    # 1) por el camino de tierra hasta el brocal
    path = [Vector((p.x, p.y, 0)) for p in pozo.path_samples(0.5)]
    L = [0.0]
    for a, b in zip(path, path[1:]):
        L.append(L[-1] + (b - a).length)
    k0 = int(np.searchsorted(L, L[-1] - 26.0))
    route = path[k0:-2] + [Vector((sx - COLLAR_STAND, sy + 0.1, 0))]
    pe.stand(-1.0, route[0], yaw_of(route[1] - route[0]))
    pe.key_spine(0.0, cuello=(0, 0.05, 0), cabeza=(0, 0.1, 0))
    t_arr = pe.locomote(1.0, route, 1.12, 0.68, 0.6, 0.11, 0.1)
    EV['llega_pozo'] = t_arr
    for k in range(4):
        tt = 4.0 + k * 4.5
        pe.key_spine(tt, cuello=(0, 0.05, 0), cabeza=(0, 0.1, 0))
        pe.key_spine(tt + 1.3, cuello=(0.25 * (-1) ** k, 0.0, 0), cabeza=(0.4 * (-1) ** k, 0.05, 0))
        pe.key_spine(tt + 2.8, cuello=(0, 0.05, 0), cabeza=(0, 0.1, 0))
    yaw_hole = yaw_of(Vector((1, 0, 0)))
    # se asoma al pozo: se inclina y mira abajo
    pe.key_spine(t_arr + 0.2, columna=(0, 0, 0), pecho=(0, 0, 0), cuello=(0, 0.05, 0), cabeza=(0, 0.1, 0))
    pe.key_spine(t_arr + 1.4, columna=(0, 0.12, 0), pecho=(0, 0.22, 0), cuello=(0, 0.3, 0), cabeza=(0.05, 0.45, 0))
    pe.key_spine(t_arr + 5.0, columna=(0, 0.14, 0), pecho=(0, 0.25, 0), cuello=(0, 0.32, 0), cabeza=(-0.08, 0.5, 0))
    pe.key_hip(t_arr, (0, 0, 0))
    pe.key_hip(t_arr + 1.4, (0, 0.03, -0.04), (0, 0.12, 0))
    # 2) corte: ya está en los pates, bajando
    t_lad = snap(max(t_arr + 5.5, 30.0))
    EV['corte_bajada'] = t_lad
    pe.key_root(t_lad - 0.02, route[-1], yaw_hole)
    pe.key_hip(t_lad - 0.01, (0, 0.03, -0.04), (0, 0.12, 0))
    pe.key_hip(t_lad, (0, 0.05, -0.02), (0, -0.05, 0))
    pe.key_spine(t_lad - 0.01, columna=(0, 0.14, 0), pecho=(0, 0.25, 0), cuello=(0, 0.32, 0), cabeza=(-0.08, 0.5, 0))
    pe.key_spine(t_lad, columna=(0, -0.05, 0), pecho=(0, 0.0, 0), cuello=(0, 0.1, 0), cabeza=(0, 0.2, 0))
    for k in range(5):
        tt = t_lad + 2.5 + k * 3.3
        sd = 1 if k % 2 else -1
        pe.key_spine(tt, cuello=(0.0, 0.1, 0), cabeza=(0.0, 0.2, 0))
        pe.key_spine(tt + 0.8, cuello=(0.35 * sd, 0.35, 0), cabeza=(0.5 * sd, 0.45, 0))
        pe.key_spine(tt + 1.7, cuello=(0.0, 0.1, 0), cabeza=(0.0, 0.2, 0))
    t_floor, p_floor, yaw_l = pe.ladder_down(t_lad, rungs, gz - 0.9)
    EV['pisa_suelo'] = t_floor
    pe.key_hip(t_floor - 0.6, (0, 0.05, -0.02), (0, -0.05, 0))
    pe.key_hip(t_floor + 0.3, (0, 0, 0), (0, 0, 0))
    pe.key_spine(t_floor, columna=(0, 0, 0), pecho=(0, 0, 0), cuello=(0, 0.05, 0), cabeza=(0, 0.1, 0))
    # 3) se da la vuelta y mira a los dos lados del túnel: el haz barre la bóveda
    yaw_in = yaw_of(Vector((0, 1, 0)))
    p0 = Vector((p_floor.x + 0.3, p_floor.y, 0))
    pe.turn_in_place(t_floor + 0.2, t_floor + 1.7, p0, yaw_l, yaw_in)
    tl = t_floor + 1.9
    pe.key_spine(tl, columna=(0, 0, 0), pecho=(0, 0, 0), cuello=(0, 0.05, 0), cabeza=(0, 0.1, 0))
    pe.key_spine(tl + 1.5, columna=(-0.15, 0, 0), pecho=(-0.35, 0, 0), cuello=(-0.45, -0.05, 0), cabeza=(-0.6, -0.1, 0))
    pe.key_spine(tl + 3.3, columna=(-0.15, 0, 0), pecho=(-0.35, 0, 0), cuello=(-0.45, -0.25, 0), cabeza=(-0.55, -0.3, 0))
    pe.key_spine(tl + 4.8, columna=(0.1, 0, 0), pecho=(0.25, 0, 0), cuello=(0.35, -0.1, 0), cabeza=(0.5, -0.15, 0))
    pe.key_spine(tl + 6.4, columna=(0.1, 0, 0), pecho=(0.2, 0, 0), cuello=(0.3, -0.05, 0), cabeza=(0.45, -0.05, 0))
    pe.key_spine(tl + 7.6, columna=(0, 0, 0), pecho=(0, 0, 0), cuello=(0, 0.05, 0), cabeza=(0, 0.1, 0))
    EV['mira_lados'] = tl
    # 4) camina por la vía hacia la boca (+Y), por el centro
    t_w = tl + 7.4
    EV['empieza_andar'] = t_w
    route = [p0, Vector((-2.0, sy + 2.5, 0)), Vector((-0.2, sy + 7.0, 0)), Vector((0.0, sy + 10.0, 0)),
             Vector((0.0, WALK_STOP_Y, 0))]
    for k in range(9):
        tt = t_w + 3 + k * 4.1
        sd = (-1) ** k
        up = k % 3 == 0
        pe.key_spine(tt, cuello=(0, 0.05, 0), cabeza=(0, 0.1, 0))
        pe.key_spine(tt + 1.2, cuello=(0.2 * sd, -0.12 if up else 0.05, 0), cabeza=(0.35 * sd, -0.35 if up else 0.12, 0))
        pe.key_spine(tt + 2.6, cuello=(0, 0.05, 0), cabeza=(0, 0.1, 0))
    t_stop = pe.locomote(t_w, route, 1.0, 0.66, 0.6, 0.1, 0.1, decel=0.6)
    EV['para'] = t_stop
    EV['ruido1'] = t_stop - 1.8
    # 5) oye algo detrás: se queda quieto, gira la cabeza y luego todo el cuerpo
    ts = t_stop + 0.5
    pe.key_spine(ts, columna=(0, 0, 0), pecho=(0, 0, 0), cuello=(0, 0.05, 0), cabeza=(0, 0.1, 0))
    pe.key_spine(ts + 1.4, columna=(-0.2, 0, 0), pecho=(-0.45, 0, 0), cuello=(-0.5, 0, 0), cabeza=(-0.6, 0.0, 0))
    pe.key_spine(ts + 1.9, columna=(-0.2, 0, 0), pecho=(-0.45, 0, 0), cuello=(-0.5, 0, 0), cabeza=(-0.6, 0.0, 0))
    yaw_back = yaw_in - math.pi
    pstop = Vector((0.0, WALK_STOP_Y, 0))
    pe.turn_in_place(ts + 2.0, ts + 3.5, pstop, yaw_in, yaw_back)
    pe.key_spine(ts + 3.5, columna=(0, 0, 0), pecho=(0, 0, 0), cuello=(0, 0.05, 0), cabeza=(0, 0.1, 0))
    EV['mira_atras'] = ts + 3.5
    # el haz busca en la oscuridad... y sube hacia el hundimiento
    tb = ts + 3.7
    hx, hy = H4
    up_ang = math.atan2(cfg.vault_z(hx) - 1.65, abs(WALK_STOP_Y - hy))
    pe.key_spine(tb + 1.0, cuello=(0.15, 0.05, 0), cabeza=(0.25, 0.1, 0))
    pe.key_spine(tb + 2.2, cuello=(-0.12, 0.0, 0), cabeza=(-0.2, 0.05, 0))
    pe.key_spine(tb + 3.4, cuello=(0, -0.05, 0), cabeza=(0, 0.0, 0))
    look_up = dict(pecho=(0, -0.08, 0), cuello=(0, -0.25, 0), cabeza=(0.0, -(up_ang - 0.33), 0))
    pe.key_spine(tb + 5.4, **look_up)
    EV['mira_hueco'] = tb + 5.4
    # 6) el monstruo se asoma: se queda helado
    t_peek = tb + 5.0
    EV['asoma'] = t_peek
    EV['asoma_fin'] = t_peek + 11.6
    pe.key_spine(t_peek + 11.8, **look_up)
    pe.key_hip(t_peek + 6.0, (0, 0, 0), (0, 0, 0))
    pe.key_hip(t_peek + 7.0, (0, 0.03, -0.02), (0, -0.06, 0))
    # retrocede de espaldas, sin dejar de mirar el hueco
    back_to = pstop + Vector((0, 1.3, 0))
    t_back0 = t_peek + 12.3
    pe.locomote(t_back0, [pstop, back_to], 0.45, 0.45, 0.65, 0.06, 0.11, yaw_fn=lambda t, d: yaw_back)
    pe.key_spine(t_back0 + 2.5, pecho=(0, -0.05, 0), cuello=(0, -0.15, 0), cabeza=(0, -(up_ang * 0.6 - 0.2), 0))
    t_scream = t_back0 + 5.0
    EV['grito'] = t_scream
    # 7) el monstruo cae: se encoge, se da la vuelta y corre
    t_drop = t_scream + 0.15
    EV['cae'] = t_drop
    pe.key_hip(t_drop, (0, 0, 0), (0, 0, 0))
    pe.key_hip(t_drop + 0.25, (0, 0.04, -0.1), (0, 0.2, 0))
    pe.key_spine(t_drop + 0.25, columna=(0, 0.1, 0), pecho=(0, 0.15, 0), cuello=(0, 0.1, 0), cabeza=(0, -0.1, 0))
    t_turn = t_drop + 0.9
    pe.turn_in_place(t_turn, t_turn + 0.55, back_to, yaw_back, yaw_in)
    pe.key_hip(t_turn + 0.55, (0, -0.03, -0.06), (0, 0.18, 0))
    t_run = t_turn + 0.45
    EV['corre'] = t_run
    run_route = [back_to, Vector((0.0, back_to.y + 4, 0)), Vector((0.0, 28.0, 0)), Vector((-1.6, 33.0, 0)),
                 Vector((-2.15, 38.0, 0)), Vector((-2.2, BOARD_Y - 0.35, 0))]
    EV['mira_corriendo'] = []
    for k in range(10):
        tt = t_run + 2.0 + k * 2.6
        pe.key_spine(tt, columna=(0, 0.06, 0), pecho=(0, 0.08, 0), cuello=(0, -0.05, 0), cabeza=(0, -0.05, 0))
        if k in (2, 5, 8):
            pe.key_spine(tt + 0.6, columna=(-0.1, 0.1, 0), pecho=(-0.3, 0.1, 0), cuello=(-0.5, 0, 0), cabeza=(-0.7, 0, 0))
            pe.key_spine(tt + 1.3, columna=(0, 0.06, 0), pecho=(0, 0.08, 0), cuello=(0, -0.05, 0), cabeza=(0, -0.05, 0))
            EV['mira_corriendo'].append(tt + 0.6)
    pe.key_hip(t_run + 1.0, (0, -0.03, -0.03), (0, 0.16, 0))
    t_door = pe.locomote(t_run, run_route, 5.3, 1.5, 0.36, 0.2, 0.085, run=True, accel=3.0, decel=4.0, end_close=False)
    EV['llega_loco'] = t_door
    pe.key_hip(t_door - 0.4, (0, -0.03, -0.03), (0, 0.16, 0))
    # 8) sube a la cabina: estribos y asideros de la puerta izquierda (el tren aún está quieto:
    #    las coordenadas de la máquina coinciden con las del mundo)
    tb0 = t_door
    yaw_x = yaw_of(Vector((1, 0, 0)))
    g0 = ground_smooth(-2.2, BOARD_Y)
    pe.key_root(tb0 + 0.25, Vector((-2.05, BOARD_Y, g0)), yaw_x, 'maq')
    rail_lo = Vector((-1.47, BOARD_Y - 0.3, 2.05))
    rail_hi = Vector((-1.47, BOARD_Y + 0.3, 2.35))
    qg = {s: pe.hq(s, yaw_x, 0, math.radians(90 * (1 if s == 'L' else -1))) for s in ('L', 'R')}
    pe.hands['L'].plant(tb0 + 0.15, tb0 + 1.2, rail_hi, qg['L'], lift=0.05, space='maq')
    pe.hands['R'].plant(tb0 + 0.3, tb0 + 1.5, rail_lo, qg['R'], lift=0.05, space='maq')
    pe.hands['L'].plant(tb0 + 1.4, tb0 + 2.0, rail_hi + Vector((0, 0, 0.4)), qg['L'], lift=0.05, space='maq')
    fq = {s: pe.fq(s, yaw_x) for s in ('L', 'R')}
    pe.feet['R'].plant(tb0 + 0.5, tb0 + 0.85, Vector((-1.52, BOARD_Y - 0.08, 0.615 + 0.095)), fq['R'], lift=0.3, space='maq')
    pe.feet['L'].plant(tb0 + 0.95, tb0 + 1.35, Vector((-1.5, BOARD_Y + 0.1, 1.065 + 0.095)), fq['L'], lift=0.35, space='maq')
    pe.key_root(tb0 + 0.65, Vector((-1.95, BOARD_Y, 0.45)), yaw_x, 'maq')
    pe.key_root(tb0 + 1.1, Vector((-1.85, BOARD_Y, 0.9)), yaw_x, 'maq')
    pe.key_root(tb0 + 1.6, Vector((-1.4, BOARD_Y, 1.55)), yaw_x, 'maq')
    pe.key_mode(tb0, 'manos')
    stand = Vector((-0.35, BOARD_Y + 0.05, CAB_FLOOR))
    pe.feet['R'].plant(tb0 + 1.5, tb0 + 1.85, Vector((-1.05, BOARD_Y - 0.08, CAB_FLOOR + 0.095)), fq['R'], lift=0.35, space='maq')
    pe.key_root(tb0 + 2.0, Vector((-0.9, BOARD_Y, CAB_FLOOR)), yaw_x, 'maq')
    pe.key_root(tb0 + 2.5, stand, yaw_in, 'maq')
    for k, s in enumerate(('L', 'R')):
        X = 1 if s == 'L' else -1
        p = stand + left_of(yaw_in) * (X * 0.12) + Vector((0, 0, 0.095))
        pe.feet[s].plant(tb0 + 2.1 + 0.25 * k, tb0 + 600, p, pe.fq(s, yaw_in), lift=0.08, space='maq')
        STEPS.append((tb0 + 2.1 + 0.25 * k, 'chapa', p.copy()))
    pe.key_mode(tb0 + 2.3, 'quieto')
    pe.key_hip(tb0 + 0.6, (0, 0.0, -0.05), (0, 0.25, 0))
    pe.key_hip(tb0 + 2.5, (0, 0, -0.02), (0, 0.1, 0))
    EV['dentro'] = tb0 + 2.5
    # 9) abre el hogar (la luz del fuego) y tira del regulador
    t_r = tb0 + 3.9
    by = tren.BACKHEAD_Y
    door_h = Vector((0.2, by - 0.12, 2.22))
    reg = Vector((0.32, by - 0.14, 2.92))
    qp = {s: pe.hq(s, yaw_in, math.radians(-80)) for s in ('L', 'R')}
    pe.hands['R'].plant(t_r - 1.9, t_r - 1.3, door_h, qp['R'], lift=0.03, space='maq')
    pe.hands['R'].plant(t_r - 0.45, t_r - 0.25, reg, qp['R'], lift=0.04, space='maq')
    pe.hands['R'].plant(t_r + 0.3, t_r + 2.6, reg + Vector((0, -0.24, -0.08)), qp['R'], lift=0.0, space='maq')
    pe.hands['L'].plant(t_r - 0.2, t_r + 6.0, Vector((-0.62, by - 0.3, 2.62)), qp['L'], lift=0.04, space='maq')
    pe.key_spine(t_r - 2.2, pecho=(0, 0.2, 0), cuello=(0, 0.1, 0), cabeza=(0, 0.2, 0))
    pe.key_spine(t_r - 0.6, pecho=(0.1, 0.1, 0), cuello=(0, 0.0, 0), cabeza=(-0.1, 0.0, 0))
    pe.key_spine(t_r + 0.5, pecho=(0, -0.05, 0), cuello=(0, 0.0, 0), cabeza=(0, 0.0, 0))
    pe.key_hip(t_r - 1.6, (0, -0.02, -0.12), (0, 0.3, 0))
    pe.key_hip(t_r, (0, 0.02, -0.03), (0, 0.05, 0))
    EV['regulador'] = t_r
    return pe, stand, yaw_in


def person_train(pe, stand, yaw_in):
    """En la locomotora: se asoma a mirar atrás, ve al monstruo, vuelve, frena y se agarra."""
    P = tren.P
    by = tren.BACKHEAD_Y
    q = {s: pe.hq(s, yaw_in, math.radians(-80)) for s in ('L', 'R')}
    t_look = P['t_boca'] + 1.0
    EV['se_asoma'] = t_look
    yaw_lean = yaw_in + math.radians(55)
    lean = Vector((-0.95, BOARD_Y + 0.05, stand.z))
    pe.key_root(t_look - 0.8, stand, yaw_in, 'maq')
    pe.key_root(t_look + 0.2, lean, yaw_lean, 'maq')
    pe.hands['L'].plant(t_look - 0.1, t_look + 5.6, Vector((-1.47, BOARD_Y + 0.3, 2.45)), q['L'], lift=0.05, space='maq')
    for k, s in enumerate(('R', 'L')):
        X = 1 if s == 'L' else -1
        p = lean + left_of(yaw_lean) * (X * 0.13) + Vector((0, 0, 0.095))
        pe.feet[s].plant(t_look + 0.25 * k, t_look + 5.8, p, pe.fq(s, yaw_lean), lift=0.07, space='maq')
    pe.key_spine(t_look - 0.5, columna=(0, 0, 0), pecho=(0, 0, 0), cuello=(0, 0.0, 0), cabeza=(0, 0.0, 0))
    pe.key_spine(t_look + 0.4, columna=(0.2, 0, 0.0), pecho=(0.5, 0.0, 0.1), cuello=(0.55, 0.0, 0), cabeza=(0.7, -0.05, 0))
    pe.key_spine(t_look + 1.2, columna=(0.25, 0, 0.1), pecho=(0.6, 0.0, 0.15), cuello=(0.6, 0.0, 0), cabeza=(0.75, 0.0, 0))
    pe.key_spine(t_look + 5.2, columna=(0.25, 0, 0.1), pecho=(0.6, 0.0, 0.15), cuello=(0.6, 0.0, 0), cabeza=(0.75, 0.05, 0))
    EV['ve_monstruo'] = t_look + 0.9
    t_fwd = t_look + 5.8
    pe.key_spine(t_fwd + 0.6, columna=(0, 0.05, 0), pecho=(0, 0.05, 0), cuello=(0, 0.0, 0), cabeza=(0, -0.05, 0))
    pe.key_root(t_fwd, lean, yaw_lean, 'maq')
    pe.key_root(t_fwd + 0.6, stand + Vector((-0.25, 0.1, 0)), yaw_in, 'maq')
    EV['mira_delante'] = t_fwd + 0.6
    for k, s in enumerate(('L', 'R')):
        X = 1 if s == 'L' else -1
        p = stand + Vector((-0.25, 0.1, 0.095)) + left_of(yaw_in) * (X * 0.12)
        pe.feet[s].plant(t_fwd + 0.15 + 0.2 * k, t_fwd + 600, p, pe.fq(s, yaw_in), lift=0.07, space='maq')
    # el freno: el volante a la izquierda, lo gira con las dos manos
    tb = P['tb']
    EV['freno'] = tb
    wheel = Vector((-0.62, by - 0.31, 2.45))
    pe.hands['L'].plant(tb - 0.7, tb + 3.5, wheel + Vector((-0.12, 0, 0.05)), q['L'], lift=0.05, space='maq')
    pe.hands['R'].plant(tb - 0.55, tb + 3.5, wheel + Vector((0.12, 0, -0.05)), q['R'], lift=0.05, space='maq')
    pe.key_spine(tb - 0.4, columna=(0.1, 0.15, 0), pecho=(0.1, 0.2, 0), cuello=(0, -0.2, 0), cabeza=(0, -0.3, 0))
    pe.key_hip(tb - 0.5, (0.0, 0.0, -0.08), (0.15, 0.2, 0))
    pe.key_hip(tb + 3.0, (0.0, 0.05, -0.12), (0.15, -0.1, 0))
    # se encoge cuando el tren vuelca
    t_tip = P.get('t_tip', P['te'] + 1.4)
    pe.key_spine(t_tip, columna=(0, 0.4, 0), pecho=(0, 0.4, 0), cuello=(0, 0.3, 0), cabeza=(0, 0.3, 0))
    pe.key_hip(t_tip + 0.5, (0.0, 0.1, -0.35), (0, 0.5, 0))


# ------------------------------------------------------------------ el monstruo
ZF = cfg.SLEEPER_TOP
HW, WH, RA = cfg.HALF_W, cfg.WALL_H, cfg.R_ARCH
WALL = WH - ZF
ARC = math.pi * RA
LOOP_P = 2 * HW + 2 * WALL + ARC
U_RWALL = HW + WALL * 0.5            # muro derecho, media altura
U_TOP = HW + WALL + ARC / 2           # clave de la bóveda


def loop_point(u):
    """Punto (x, z) y normal hacia dentro del perímetro del túnel; u en metros desde el centro
    del suelo hacia +X, luego hacia arriba por el muro derecho, la bóveda y el muro izquierdo."""
    u = u % LOOP_P
    if u < HW:
        return Vector((u, ZF)), Vector((0, 1))
    u -= HW
    if u < WALL:
        return Vector((HW, ZF + u)), Vector((-1, 0))
    u -= WALL
    if u < ARC:
        a = u / RA
        return Vector((RA * math.cos(a), WH + RA * math.sin(a))), Vector((-math.cos(a), -math.sin(a)))
    u -= ARC
    if u < WALL:
        return Vector((-HW, WH - u)), Vector((1, 0))
    u -= WALL
    return Vector((-HW + u, ZF)), Vector((0, 1))


def tunnel_body(y, u, H=2.1):
    p, n = loop_point(u)
    return Vector((p.x, y, p.y)) + Vector((n.x, 0, n.y)) * H, Vector((n.x, 0, n.y))


_LOOP = None


def surf_project(q):
    """Lleva un punto ideal de apoyo a la superficie más cercana (túnel, viaducto o monte)."""
    global _LOOP
    if in_tunnel(q.x, q.y) and q.z < cfg.CROWN + 0.3:
        if _LOOP is None:
            us = np.linspace(0, LOOP_P, 400, endpoint=False)
            _LOOP = (us, np.array([tuple(loop_point(u)[0]) for u in us]))
        us, pts = _LOOP
        d = (pts[:, 0] - q.x) ** 2 + (pts[:, 1] - q.z) ** 2
        p, n = loop_point(float(us[int(np.argmin(d))]))
        n3 = Vector((n.x, 0, n.y))
        hit = WALLS.ray_cast(Vector((p.x, q.y, p.y)) + n3 * 0.8, -n3, 2.5)
        if hit[0] is not None:
            return hit[0], hit[1]
        return Vector((p.x, q.y, p.y)), n3
    hit = WALLS.ray_cast(q + Vector((0, 0, 3.0)), Vector((0, 0, -1)), 12.0)
    if hit[0] is not None:
        return hit[0], hit[1]
    return q, Vector((0, 0, 1))


class Monster:
    def __init__(self, MR):
        from .monstruo import LEGS
        self.MR = MR
        self.arm = MR['arm']
        self.keys = []          # (t, pos, adelante, arriba)
        self.head = []          # (t, (giro, cabeceo, alabeo))
        self.jaw = []           # (t, abertura rad)
        self.glow = []          # (t, (ojos 0..1, boca 0..1))
        self.legs = {n: Limb(n) for n, s, ya in LEGS}
        self.air = []           # (t0, t1) en el aire: patas sueltas

    def key(self, t, pos, fwd, up=(0, 0, 1)):
        self.keys.append((t, Vector(pos), Vector(fwd).normalized(), Vector(up).normalized()))


def chase_keys(mo, t0, t1, table, accel_t=1.6):
    """Recorrido por el túnel: table = [(y, u)]; arranca acelerando y sigue a velocidad constante."""
    ys = np.array([y for y, u in table])
    uu = np.array([u for y, u in table])
    D = ys[-1] - ys[0]
    T = t1 - t0
    v = D / (T - accel_t / 2)
    for f in A.frames_range(t0, t1):
        t = A.time_of(f)
        tt = min(max(t - t0, 0.0), T)
        d = 0.5 * v / accel_t * tt * tt if tt < accel_t else v * (tt - accel_t / 2)
        y = ys[0] + min(D, d)
        u = float(np.interp(y, ys, uu))
        pos, up = tunnel_body(y, u)
        mo.key(t, pos, (0, 1, 0), up)


def monster_story(MR, ctx):
    mo = Monster(MR)
    hx, hy = H4
    t_peek = EV['asoma']
    vault = cfg.vault_z(hx)
    gtop = ground_at(hx, hy - 6.0, 200.0)
    # bajo tierra (invisible) hasta poco antes de asomarse; sube detrás del hundimiento
    mo.key(-1.0, (hx, hy - 7.0, gtop - 8.0), (0, 1, 0))
    mo.key(t_peek - 4.0, (hx, hy - 7.0, gtop - 8.0), (0, 1, 0))
    mo.key(t_peek - 1.0, (hx, hy - 6.0, gtop + 2.2), (0, 1, 0))

    def dn(a):
        return Vector((0, math.cos(a), -math.sin(a))), Vector((0, math.sin(a), math.cos(a)))
    a1, a2 = math.radians(25), math.radians(66)
    mo.key(t_peek + 1.5, (hx, hy - 3.6, gtop + 2.0), *dn(a1))
    mo.key(t_peek + 5.5, (hx + 0.1, hy - 1.7, vault + 2.05), *dn(a2))
    mo.key(t_peek + 10.0, (hx + 0.12, hy - 1.55, vault + 1.9), *dn(a2 + 0.04))
    mo.key(t_peek + 11.6, (hx, hy - 4.0, gtop + 2.3), *dn(a1))
    mo.head += [(t_peek + 2.0, (0, 0, 0)), (t_peek + 5.5, (0.0, 0.0, 0.45)), (t_peek + 8.0, (0.05, 0.1, 0.6)),
                (t_peek + 10.2, (0.0, 0.05, 0.55)), (t_peek + 11.6, (0, 0, 0))]
    mo.jaw += [(t_peek + 6.0, 0.0), (t_peek + 8.5, 0.12), (t_peek + 10.0, 0.05), (t_peek + 11.0, 0.0)]
    mo.glow += [(-1.0, (0.1, 0.05)), (t_peek + 4.5, (0.15, 0.1)), (t_peek + 6.5, (1.0, 0.3)), (t_peek + 10.5, (1.0, 0.3)),
                (t_peek + 11.6, (0.3, 0.1))]
    # cae por el hundimiento
    t_drop = EV['cae']
    land = t_drop + 1.25
    EV['aterriza'] = land
    mo.key(t_drop - 0.8, (hx, hy - 3.0, gtop + 2.3), *dn(a1))
    mo.key(t_drop, (hx, hy - 0.6, vault + 2.6), *dn(math.radians(50)))
    mo.key(t_drop + 0.6, (hx + 0.2, hy + 0.5, vault - 1.6), *dn(math.radians(20)))
    mo.key(land, (hx + 0.3, hy + 1.2, ZF + 1.3), (0, 1, 0))
    mo.key(land + 0.3, (hx + 0.3, hy + 1.3, ZF + 1.0), (0, 1, 0))
    mo.key(land + 1.1, (hx + 0.2, hy + 1.4, ZF + 2.1), (0, 1, 0.08))
    mo.air.append((t_drop - 0.2, land - 0.05))
    # ruge
    roar0 = land + 0.6
    EV['ruge'] = roar0
    mo.jaw += [(roar0 - 0.2, 0.0), (roar0 + 0.3, 0.55), (roar0 + 1.9, 0.6), (roar0 + 2.4, 0.1)]
    mo.head += [(land, (0, 0, 0)), (roar0 + 0.3, (0, -0.25, 0)), (roar0 + 1.9, (0.08, -0.3, 0.05)), (roar0 + 2.5, (0, 0, 0))]
    mo.glow += [(land, (0.6, 0.3)), (roar0 + 0.3, (1.0, 1.0)), (roar0 + 2.0, (1.0, 1.0)), (roar0 + 2.6, (0.9, 0.35))]
    mo.key(roar0 + 2.4, (hx + 0.2, hy + 1.6, ZF + 2.1), (0, 1, 0))
    # persecución: suelo, muro derecho, bóveda (boca abajo, sorteando el hundimiento 3) y abajo
    # otra vez por el muro derecho, detrás del ténder
    t0 = roar0 + 2.6
    EV['persigue'] = t0
    t_door = EV['llega_loco']
    table = [(hy + 1.8, 0.2), (-66.0, 0.3), (-56.0, U_RWALL), (-46.0, HW + WALL + 3.0), (-30.0, U_TOP - 1.2),
             (-12.0, U_TOP - 3.4), (12.0, U_TOP - 3.4), (24.0, HW + WALL + 2.0), (30.0, U_RWALL), (34.0, 3.4)]
    EV['techo'] = t0 + (t_door + 1.5 - t0) * 0.45
    chase_keys(mo, t0, t_door + 1.5, table)
    # acecha detrás del ténder mientras arranca
    t_reg = EV['regulador']
    pos, up = tunnel_body(35.0, 3.0)
    mo.key(t_reg - 0.4, pos, (0, 1, 0), up)
    mo.head += [(t_reg - 1.5, (0, 0, 0)), (t_reg - 0.4, (0.0, 0.1, 0.4))]
    mo.jaw += [(t_reg - 0.6, 0.05), (t_reg + 0.4, 0.4), (t_reg + 1.6, 0.1)]
    mo.glow += [(t_reg - 0.6, (1.0, 0.4)), (t_reg + 0.4, (1.0, 1.0)), (t_reg + 1.8, (1.0, 0.4))]
    # persigue al tren: detrás del ténder, se va quedando atrás y se acerca cuando frena
    P = tren.P
    edge = cfg.GAP[0] - 2.8
    t_stop_follow = P.get('t_tip', P['te'] + 1.5) + 3.0
    ts_ = np.arange(t_reg + 0.6, t_stop_follow, 1 / FPS)
    want = []
    for t in ts_:
        s_rear = cfg.LOCO_FRONT - 17.6 + tren.s_of_t(t)
        gap = 6.0 + 1.5 * min(10.0, t - t_reg) - 8.0 * smoothstep(P['tb'], P['te'], t)
        want.append(min(s_rear - max(5.5, gap), edge))
    # sin saltos: velocidad máxima y frenada limitadas
    y = 35.0
    vy = 0.0
    ys = []
    for w in want:
        dv = float(np.clip((w - y) * 2.0 - vy, -9.0 / FPS, 6.0 / FPS))
        vy = min(13.0, max(0.0, vy + dv))
        y = min(y + vy / FPS, edge)
        if y >= edge - 1e-3:
            vy = 0.0
        ys.append(y)
    t_edge = None
    for t, y in zip(ts_, ys):
        t = float(t)
        if y < cfg.Y1 - 3:
            u = lerp(3.0, 0.6, smoothstep(t_reg + 0.6, t_reg + 3.0, t))
            pos, up = tunnel_body(y, u)
        else:
            pos, up = Vector((0, y, cfg.RAIL_TOP + 2.0)), Vector((0, 0, 1))
        mo.key(t, pos, (0, 1, 0), up)
        if t_edge is None and y >= edge - 0.5:
            t_edge = t
    if t_edge is None:
        t_edge = float(ts_[-1])
    EV['monstruo_borde'] = t_edge
    t_k = max(t_edge, float(ts_[-1])) + 0.8
    mo.key(t_k, (0, edge - 0.3, 2.3), (0, 1, -0.35), (0, 0.35, 1))
    t_imp = P.get('t_impacto', t_k + 3.0)
    t_fin = t_imp + 12.0
    mo.key(max(t_k + 1.0, t_imp + 2.0), (0, edge - 0.2, 2.2), (0, 1, -0.5), (0, 0.5, 1))
    mo.key(t_fin, (0.05, edge - 0.25, 2.25), (0, 1, -0.45), (0, 0.45, 1))
    # mira abajo al valle; tras el estruendo lejano ruge y luego se vuelve despacio hacia la cámara
    t_g = t_imp + 2.2
    mo.head += [(t_edge, (0, 0, 0)), (t_edge + 1.0, (0, 0.35, 0)), (t_g - 0.5, (0, 0.45, 0.1)),
                (t_g + 2.6, (0, 0.3, 0.05)), (t_g + 4.4, (-0.62, 0.08, 0.28)), (t_fin, (-0.66, 0.05, 0.3))]
    mo.jaw += [(t_edge + 0.5, 0.05), (t_g - 0.2, 0.05), (t_g + 0.4, 0.62), (t_g + 2.2, 0.66), (t_g + 2.8, 0.12),
               (t_g + 5.0, 0.08), (t_g + 5.8, 0.3), (t_fin, 0.28)]
    mo.glow += [(t_edge, (1.0, 0.5)), (t_g, (1.0, 0.5)), (t_g + 0.4, (1.0, 1.0)), (t_g + 2.5, (1.0, 1.0)),
                (t_g + 3.2, (1.0, 0.4)), (t_g + 5.8, (1.0, 0.7))]
    EV['grito_final'] = t_g + 0.4
    EV['mira_camara'] = t_g + 4.4
    return mo


def monster_bake(mo, t_from, t_to):
    MR = mo.MR
    arm = MR['arm']
    mo.keys.sort(key=lambda k: k[0])
    keys = []
    for k in mo.keys:
        if keys and k[0] - keys[-1][0] < 1e-3:
            keys[-1] = k
        else:
            keys.append(k)
    tr_pos = Track([(t, tuple(p)) for t, p, f, u in keys])
    tr_f = Track([(t, tuple(f)) for t, p, f, u in keys], smooth=False)
    tr_u = Track([(t, tuple(u)) for t, p, f, u in keys], smooth=False)
    frames = A.frames_range(t_from, t_to)
    ts = [A.time_of(f) for f in frames]
    locs, quats, mats, clean = [], [], [], []
    for t in ts:
        p = tr_pos(t)
        f = tr_f(t)
        u = tr_u(t)
        clean.append(p.copy())
        p = p + u.normalized() * (0.05 * math.sin(t * 2.2)) + Vector((nz(t, 31, 3), nz(t, 32, 3), nz(t, 33, 3))) * 0.025
        q = A._basis_quat(f, u, 'Y')
        locs.append(p)
        quats.append(q)
        mats.append(Matrix.Translation(p) @ q.to_matrix().to_4x4())
    mo.samples = dict(ts=ts, locs=locs, quats=quats)
    A.bake_obj(arm, frames, locs, quats)
    hd = Track(mo.head or [(0, (0, 0, 0))])
    jw = Track(mo.jaw or [(0, 0.0)])
    rh = arm.data.bones['cabeza'].matrix_local.to_3x3()
    rj = arm.data.bones['mandibula'].matrix_local.to_3x3()
    hq, jq = [], []
    for t in ts:
        y, p_, r_ = hd(t)
        e = Euler((p_ + nz(t, 41, 1.5) * 0.04, r_, y + nz(t, 42, 1.2) * 0.05), 'ZXY')
        hq.append((rh.inverted() @ e.to_matrix() @ rh).to_quaternion())
        j = jw(t) + max(0.0, nz(t, 43, 9)) * 0.03
        jq.append((rj.inverted() @ Euler((-j, 0, 0)).to_matrix() @ rj).to_quaternion())
    A.bake_pose(arm, 'cabeza', frames, quats=hq)
    A.bake_pose(arm, 'mandibula', frames, quats=jq)
    gl = Track(mo.glow or [(0, (0.5, 0.2))])
    gk = [(t, gl(t)) for t in ts[::2]]
    for e in MR['eyes']:
        A.bake_prop(e, 'color', [(t, (1, 1, 1, 0.2 + 0.8 * g[0] * (0.9 + 0.1 * nz(t, 44, 8)))) for t, g in gk])
    for key in ('ojo.L', 'ojo.R'):
        A.bake_prop(MR['lights'][key].data, 'energy', [(t, 0.3 + 4.0 * g[0]) for t, g in gk])
    A.bake_prop(MR['lights']['boca'].data, 'energy', [(t, 0.5 + 60.0 * g[1] * (0.8 + 0.2 * nz(t, 45, 10))) for t, g in gk])
    A.bake_prop(MR['inner'], 'color', [(t, (1, 1, 1, 0.15 + 1.6 * g[1])) for t, g in gk])
    legs_bake(mo, ts, frames, mats, quats, clean)


def legs_bake(mo, ts, frames, mats, quats, clean):
    from .monstruo import LEGS, GROUP_A
    MR = mo.MR
    rest = MR['legs']
    s = [0.0]
    for a, b in zip(clean, clean[1:]):
        s.append(s[-1] + (b - a).length)
    s = np.array(s)
    Lg, beta, lift = 1.7, 0.6, 0.85

    def i_at_s(x):
        return min(int(np.searchsorted(s, x)), len(ts) - 1)

    def in_air(t):
        return any(a <= t <= b for a, b in mo.air)
    for name, sd, ya in LEGS:
        F = rest[name][3]
        off = (0.25 if name in GROUP_A else 0.75) + 0.06 * (int(name[1]) - 2.5)
        lim = mo.legs[name]
        n = -1
        while 2 * Lg * (n + off) <= s[-1] + 2 * Lg:
            sc = 2 * Lg * (n + off)
            i_c = i_at_s(max(0.0, sc))
            t_land = ts[i_at_s(max(0.0, sc - beta * Lg))]
            t_lift = ts[i_at_s(sc + beta * Lg)] if sc + beta * Lg <= s[-1] else ts[-1] + 100
            p, nrm = surf_project(mats[i_c] @ F)
            lim.plant(t_land, t_lift, p, Quaternion(), lift=0.0)
            n += 1
        lim.sort()
        for a, b in zip(lim.ev, lim.ev[1:]):
            if b['t0'] - a['t1'] > 0.45:
                a['t1'] = b['t0'] - 0.45
        pos = []
        for i, t in enumerate(ts):
            Mb = mats[i]
            if in_air(t):
                fl = Vector((nz(t, 60 + int(name[1]) * 2 + (sd > 0), 4) * 0.5, nz(t, 70 + int(name[1]), 4) * 0.5, 0.9))
                pos.append(Mb @ (F * 0.8 + fl))
                continue
            p, q, u, sp = lim.at(t, lambda sp_, tt, pp: pp)
            if 0 < u < 1:
                p = p + (quats[i] @ Vector((0, 0, 1))) * lift * math.sin(math.pi * u)
            pos.append(p)
        A.bake(MR['targets'][name], 'location', frames, pos)
        for e in lim.ev:
            if ts[0] <= e['t0'] <= ts[-1]:
                MSTEPS.append((e['t0'], e['p'].x, e['p'].y, e['p'].z))


# ------------------------------------------------------------------ montaje
def build(main, ctx):
    global GROUND, WALLS
    EV.clear()
    del STEPS[:], MSTEPS[:], RUNGS[:]
    try:
        from .tunel import HOLES
        for name, pts, c in HOLES:
            if name == 'Hundimiento 4':
                H4[0], H4[1] = c
    except Exception:
        pass
    floor = ('Traviesas', 'Balasto', 'Suelo tunel', 'Escombros tierra', 'Bloques caidos', 'Terreno sobre el tunel',
             'Monte', 'Brocal', 'Marco tapa', 'Tapa registro')
    GROUND = bvh_from(floor)
    WALLS = bvh_from(floor + ('Tunel', 'Viaducto', 'Pretiles', 'Cornisa viaducto', 'Acantilado'))
    pe, stand, yaw_in = person_story(ctx['personaje'], ctx)
    tren.plan(EV['regulador'], v_max=8.0)
    for k in ('t0', 't1', 'tb', 'te', 't_boca', 't_tip', 't_caida', 't_impacto', 'ten_edge'):
        if k in tren.P:
            EV['tren_' + k] = float(tren.P[k])
    person_train(pe, stand, yaw_in)
    t_end = tren.P.get('t_impacto', tren.P['te'] + 8) + 12.0
    EV['fin'] = t_end
    mo = monster_story(ctx['monstruo'], ctx)
    pe.bake(-1.0, t_end)
    monster_bake(mo, -1.0, t_end)
    tren.bake(t_end)
    print('  eventos:', ', '.join('%s=%.1f' % (k, v) for k, v in EV.items() if isinstance(v, float)))
    return {'EV': EV, 'steps': STEPS, 'msteps': MSTEPS, 'rungs': RUNGS, 'pers': pe.samples, 'mon': mo.samples}
