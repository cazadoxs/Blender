"""Herramientas de animación: curvas por fotograma escritas de golpe (rápido), interpolación
suave de pistas, cuaterniones y ruido determinista."""
import bpy, math
import numpy as np
from mathutils import Vector, Quaternion, Matrix, Euler, noise
from . import cfg

FPS = cfg.FPS


def frame_of(t):
    return 1 + t * FPS


def time_of(f):
    return (f - 1) / FPS


def action_of(id_data):
    ad = id_data.animation_data or id_data.animation_data_create()
    if ad.action is None:
        ad.action = bpy.data.actions.new(id_data.name + ' accion')
    return ad.action


def bake(id_data, path, frames, values, interp='LINEAR'):
    """Escribe una curva por canal. values: array (n,) o (n, k) -> canales index 0..k-1."""
    act = action_of(id_data)
    vals = np.asarray(values, dtype=np.float64)
    if vals.ndim == 1:
        vals = vals[:, None]
    frames = np.asarray(frames, dtype=np.float64)
    code = {'CONSTANT': 0, 'LINEAR': 1, 'BEZIER': 2}[interp]
    for i in range(vals.shape[1]):
        fc = act.fcurve_ensure_for_datablock(id_data, path, index=i)
        kp = fc.keyframe_points
        if len(kp):
            # se mezcla con lo que ya hubiera (otros tramos): se reescribe todo ordenado
            old = np.empty(len(kp) * 2)
            kp.foreach_get('co', old)
            old = old.reshape(-1, 2)
            keep = old[(old[:, 0] < frames.min() - 0.01) | (old[:, 0] > frames.max() + 0.01)]
            allk = np.concatenate([keep, np.stack([frames, vals[:, i]], 1)])
            allk = allk[np.argsort(allk[:, 0])]
            fc.keyframe_points.clear()
        else:
            allk = np.stack([frames, vals[:, i]], 1)
        kp.add(len(allk))
        kp.foreach_set('co', allk.ravel())
        kp.foreach_set('interpolation', [code] * len(allk))
        fc.update()


def bake_obj(ob, frames, locs=None, quats=None, scales=None):
    if locs is not None:
        bake(ob, 'location', frames, locs)
    if quats is not None:
        ob.rotation_mode = 'QUATERNION'
        bake(ob, 'rotation_quaternion', frames, fix_quats(quats))
    if scales is not None:
        bake(ob, 'scale', frames, scales)


def fix_quats(qs):
    """Que los cuaterniones seguidos no cambien de signo (si no, la interpolación da la vuelta)."""
    qs = np.array(qs, dtype=np.float64)
    for i in range(1, len(qs)):
        if np.dot(qs[i], qs[i - 1]) < 0:
            qs[i] = -qs[i]
    return qs


def bake_pose(arm_ob, bone, frames, quats=None, locs=None):
    pb = arm_ob.pose.bones[bone]
    if quats is not None:
        pb.rotation_mode = 'QUATERNION'
        bake(arm_ob, 'pose.bones["%s"].rotation_quaternion' % bone, frames, fix_quats(quats))
    if locs is not None:
        bake(arm_ob, 'pose.bones["%s"].location' % bone, frames, locs)


def bake_prop(id_data, path, keys, interp='LINEAR'):
    """keys: [(t_segundos, valor)]"""
    fr = [frame_of(t) for t, _ in keys]
    bake(id_data, path, fr, [v for _, v in keys], interp)


# ------------------------------------------------------------------ pistas suaves
class Track:
    """Pista de valores (escalares o vectores) en el tiempo, con interpolación suave
    (Hermite monótona por tramos, sin rebotes) o lineal."""

    def __init__(self, keys, smooth=True):
        keys = sorted(keys, key=lambda k: k[0])
        self.t = np.array([k[0] for k in keys], dtype=np.float64)
        self.v = np.array([np.atleast_1d(np.asarray(k[1], dtype=np.float64)) for k in keys])
        self.smooth = smooth

    def __call__(self, t):
        ts, vs = self.t, self.v
        if t <= ts[0]:
            return self._out(vs[0])
        if t >= ts[-1]:
            return self._out(vs[-1])
        i = int(np.searchsorted(ts, t) - 1)
        t0, t1 = ts[i], ts[i + 1]
        u = (t - t0) / (t1 - t0)
        if not self.smooth:
            return self._out(vs[i] * (1 - u) + vs[i + 1] * u)
        # tangentes tipo Catmull-Rom limitadas (no se pasan de los valores vecinos)
        def tang(k):
            if k <= 0 or k >= len(ts) - 1:
                return np.zeros_like(vs[0])
            d0 = (vs[k] - vs[k - 1]) / (ts[k] - ts[k - 1])
            d1 = (vs[k + 1] - vs[k]) / (ts[k + 1] - ts[k])
            m = 0.5 * (d0 + d1)
            m = np.where(d0 * d1 <= 0, 0.0, m)
            return m
        m0, m1 = tang(i) * (t1 - t0), tang(i + 1) * (t1 - t0)
        h00 = 2 * u ** 3 - 3 * u ** 2 + 1
        h10 = u ** 3 - 2 * u ** 2 + u
        h01 = -2 * u ** 3 + 3 * u ** 2
        h11 = u ** 3 - u ** 2
        return self._out(h00 * vs[i] + h10 * m0 + h01 * vs[i + 1] + h11 * m1)

    @staticmethod
    def _out(v):
        return float(v[0]) if len(v) == 1 else Vector(v)


def smoothstep(a, b, x):
    if b == a:
        return 1.0 if x >= b else 0.0
    u = min(1.0, max(0.0, (x - a) / (b - a)))
    return u * u * (3 - 2 * u)


def lerp(a, b, u):
    return a + (b - a) * u


def nz(t, seed, freq=1.0):
    """Ruido suave determinista en [-1, 1]."""
    return noise.noise(Vector((t * freq, seed * 7.31, seed * 1.17)))


def look_quat(forward, up=Vector((0, 0, 1)), fwd_axis='-Y', up_axis='Z'):
    """Cuaternión que lleva el eje fwd_axis del objeto a 'forward' manteniendo 'up' arriba."""
    return Vector(forward).to_track_quat(fwd_axis, up_axis) if up is None else _basis_quat(forward, up, fwd_axis)


def _basis_quat(forward, up, fwd_axis):
    f = Vector(forward).normalized()
    u = Vector(up)
    u = (u - f * u.dot(f))
    if u.length < 1e-6:
        u = Vector((0, 0, 1)) if abs(f.z) < 0.9 else Vector((0, 1, 0))
        u = (u - f * u.dot(f))
    u.normalize()
    r = f.cross(u)
    # columnas = ejes locales X, Y, Z en el mundo
    if fwd_axis == '-Y':
        X, Y, Z = -r, -f, u
        X = Y.cross(Z)
    elif fwd_axis == 'Y':
        Y, Z = f, u
        X = Y.cross(Z)
    elif fwd_axis == '-Z':
        Z = -f
        Y = u
        X = Y.cross(Z)
    else:
        raise ValueError(fwd_axis)
    m = Matrix((X, Y, Z)).transposed()
    return m.to_quaternion()


def frames_range(t0, t1):
    f0 = int(math.floor(frame_of(t0)))
    f1 = int(math.ceil(frame_of(t1)))
    return list(range(f0, f1 + 1))
