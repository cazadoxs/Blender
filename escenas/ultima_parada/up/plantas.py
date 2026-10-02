"""Plantas: carga los modelos escaneados de Poly Haven y, si faltan, genera
sustitutos procedurales (helechos, matas de hierba, arbustos, árboles)."""
import bpy, bmesh, math, os
import numpy as np
from mathutils import Vector, Matrix, Euler
from .util import MAN, res_path, hidden_coll, put, rng, mesh_obj, bm_obj
from . import materiales as M

LIB = {}     # papel -> colección con las variantes (para instanciar)


def _fix_images(root_dir):
    """Las texturas de los .blend de Poly Haven son relativas a su carpeta: se resuelven."""
    for img in bpy.data.images:
        p = bpy.path.abspath(img.filepath)
        if img.filepath and not os.path.exists(p):
            name = os.path.basename(img.filepath.replace('\\', '/'))
            for dp, dn, fn in os.walk(root_dir):
                if name in fn:
                    img.filepath = os.path.join(dp, name)
                    break


COMPOSITE = ('arbol', 'arbusto', 'helecho', 'tronco')   # cada archivo es una sola planta (varias piezas)


import re
HELPER = re.compile(r'geometry_nodes|geonodes|_geo$|_geo[._]|_geometry_')


def _lod(name):
    import re
    m = re.search(r'lod[_ ]?(\d+)', name.lower())
    return int(m.group(1)) if m else None


def load_models(role):
    """Devuelve una lista de grupos (uno por archivo): cada grupo es una lista de objetos."""
    items = MAN.get('modelos', {}).get(role, [])
    groups = []
    for it in items:
        path = res_path(it['blend'])
        if not os.path.exists(path):
            continue
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            dst.objects = list(src.objects)
        obs = [o for o in dst.objects if o is not None]
        # fuera los objetos auxiliares de Poly Haven: los que dispersan copias con nodos
        # (instanciarlos miles de veces anida millones de instancias) y sus duplicados ocultos
        junk = [o for o in obs if o.hide_render or HELPER.search(o.name.lower())]
        if role == 'arbol':
            ms = [o for o in obs if o.type == 'MESH' and o not in junk]
            if ms:
                big = max(ms, key=lambda o: len(o.data.polygons))
                junk += [o for o in ms if o is not big]
        obs = [o for o in obs if o not in junk]
        for o in junk:
            bpy.data.objects.remove(o)
        for o in obs:
            if len(o.modifiers):
                print('      %s: quitando modificadores %s' % (o.name, [m.type for m in o.modifiers if m.type == 'NODES']))
            for m in [m for m in o.modifiers if m.type == 'NODES']:
                o.modifiers.remove(m)
        meshes = [o for o in obs if o.type == 'MESH']
        others = [o for o in obs if o.type != 'MESH']
        lods = [_lod(o.name) for o in meshes]
        if any(l is not None for l in lods):
            best = min(l for l in lods if l is not None)
            drop = [o for o, l in zip(meshes, lods) if l is not None and l != best]
            for o in drop:
                bpy.data.objects.remove(o)
            meshes = [o for o, l in zip(meshes, lods) if l is None or l == best]
        print('    %s: %s' % (os.path.basename(path), ', '.join('%s(%d, %.1fm)' % (o.name, len(o.data.polygons), max(o.dimensions)) for o in meshes)))
        groups.append((meshes, others))
        _fix_images(os.path.dirname(path))
    return groups


def library(role, fallback, n_fallback=3):
    """Colección oculta con las variantes de un papel (para instanciar con nodos)."""
    if role in LIB:
        return LIB[role]
    c = hidden_coll('LIB ' + role)
    groups = load_models(role)
    if groups:
        n = 0
        for k, (meshes, others) in enumerate(groups):
            if role in COMPOSITE:
                sub = bpy.data.collections.new('%s %d' % (role, k))
                c.children.link(sub)
                for o in meshes + others:
                    sub.objects.link(o)
                n += 1
            else:
                for o in meshes:
                    mw = o.matrix_world.copy()
                    o.parent = None
                    o.matrix_world = mw
                    o.location = (0, 0, 0)
                    c.objects.link(o)
                    n += 1
                for o in others:
                    bpy.data.objects.remove(o)
        print('  %s: %d modelos escaneados' % (role, n))
    else:
        for i in range(n_fallback):
            o = fallback(i)
            put(o, c)
        print('  %s: %d sustitutos procedurales' % (role, n_fallback))
    LIB[role] = c
    return c


# ------------------------------------------------------------------ sustitutos procedurales
def leaf_quad(bm, base, direction, normal, length, width, uvlayer, bend=0.15, segs=3):
    """Hoja como tira de quads (curvada) con UV 0..1 para el material de hoja."""
    direction = direction.normalized()
    side = direction.cross(normal).normalized() * (width / 2)
    rows = []
    for i in range(segs + 1):
        t = i / segs
        p = base + direction * length * t - normal * bend * length * t * t
        rows.append((bm.verts.new(p - side), bm.verts.new(p + side), t))
    faces = []
    for i in range(segs):
        a, b, ta = rows[i]
        c, d, tb = rows[i + 1]
        f = bm.faces.new((a, b, d, c))
        for loop, uv in zip(f.loops, ((0, ta), (1, ta), (1, tb), (0, tb))):
            loop[uvlayer].uv = uv
        faces.append(f)
    return faces


def fern(i, mat=None):
    r = rng(500 + i)
    mat = mat or M.mat_hoja('Hoja helecho', base=(0.035, 0.09, 0.015), autumn=0.05)
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new('UVMap')
    n_fronds = int(r.integers(7, 12))
    for k in range(n_fronds):
        az = 2 * math.pi * k / n_fronds + r.uniform(-0.3, 0.3)
        el = r.uniform(0.5, 1.1)
        L = r.uniform(0.55, 0.95)
        pts = []
        for j in range(12):
            t = j / 11
            ang = el - t * t * 1.6
            pts.append(Vector((math.cos(az) * math.cos(ang) * L * t, math.sin(az) * math.cos(ang) * L * t,
                               math.sin(ang) * L * t * 0.9)))
        for j in range(1, 11):
            t = j / 11
            p = pts[j]
            d = (pts[j + 1] - pts[j - 1]).normalized()
            side = d.cross(Vector((0, 0, 1))).normalized()
            ln = 0.16 * math.sin(math.pi * min(1, t * 1.15)) + 0.02
            for s in (-1, 1):
                dirl = (side * s + d * 0.35).normalized()
                nrm = dirl.cross(d).normalized() * s
                if nrm.z < 0:
                    nrm = -nrm
                leaf_quad(bm, p, dirl, nrm, ln, ln * 0.38, uv, bend=0.25, segs=2)
        # raquis
    me_ob = bm_obj(bm, 'Helecho proc %d' % i, bpy.context.scene.collection, mat)
    return me_ob


def grass(i, mat=None):
    r = rng(600 + i)
    mat = mat or M.mat_hoja('Hoja hierba', base=(0.06, 0.1, 0.02), var=(0.03, 0.04, 0.015), autumn=0.25)
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new('UVMap')
    for k in range(int(r.integers(40, 70))):
        a = r.uniform(0, 2 * math.pi)
        rr = r.uniform(0, 0.12)
        base = Vector((math.cos(a) * rr, math.sin(a) * rr, 0))
        out = Vector((math.cos(a), math.sin(a), 0)) * r.uniform(0.1, 0.6)
        d = (Vector((0, 0, 1)) + out).normalized()
        nrm = d.cross(Vector((-math.sin(a), math.cos(a), 0))).normalized()
        leaf_quad(bm, base, d, nrm, r.uniform(0.18, 0.5), r.uniform(0.012, 0.02), uv, bend=r.uniform(0.1, 0.5), segs=4)
    return bm_obj(bm, 'Hierba proc %d' % i, bpy.context.scene.collection, mat)


def shrub(i, mat=None):
    r = rng(700 + i)
    mat = mat or M.mat_hoja('Hoja arbusto', base=(0.04, 0.085, 0.02), autumn=0.1)
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new('UVMap')
    for k in range(int(r.integers(160, 260))):
        p = Vector(r.normal(0, 1, 3))
        p.normalize()
        p *= r.uniform(0.25, 1.0) ** 0.5
        p = Vector((p.x * 0.7, p.y * 0.7, abs(p.z) * 0.8 + 0.15))
        d = Vector(r.normal(0, 1, 3)).normalized()
        nrm = (p + Vector((0, 0, 0.5))).normalized()
        d = (d - nrm * d.dot(nrm)).normalized()
        leaf_quad(bm, p, d, nrm, r.uniform(0.07, 0.12), r.uniform(0.04, 0.06), uv, bend=0.2, segs=2)
    return bm_obj(bm, 'Arbusto proc %d' % i, bpy.context.scene.collection, mat)


def rock(i, mat=None):
    r = rng(800 + i)
    from .util import MAN as _m
    mat = mat or M.mat_generic('Roca suelta', 'roca', 0.6, moss=0.6)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=4, radius=0.5)
    off = r.uniform(0, 100, 3)
    from mathutils import noise
    for v in bm.verts:
        n = noise.fractal(v.co * 1.4 + Vector(off), 0.6, 2.0, 4)
        v.co *= 1 + 0.35 * n
        v.co.z *= 0.55
        if v.co.z < -0.1:
            v.co.z = -0.1
    return bm_obj(bm, 'Roca proc %d' % i, bpy.context.scene.collection, mat, smooth=True)


# ------------------------------------------------------------------ árbol procedural
def tree_skeleton(seed, base, height, trunk_r, lean=(0, 0), crown_start=0.45, branches=7, depth=3, up_bias=0.55):
    """Devuelve lista de ramas: cada rama = lista de (punto, radio). Y puntas para hojas."""
    r = rng(seed)
    out, tips = [], []

    def grow(p0, d0, length, rad, level):
        pts = []
        p = Vector(p0)
        d = Vector(d0).normalized()
        n = max(4, int(length / 0.25))
        for i in range(n + 1):
            t = i / n
            pts.append((p.copy(), rad * (1 - 0.75 * t) + 0.004))
            d = (d + Vector(r.normal(0, 0.12, 3)) + Vector((0, 0, up_bias * 0.08))).normalized()
            p = p + d * (length / n)
        out.append(pts)
        if level >= depth:
            tips.append((p.copy(), d.copy()))
            return
        nb = branches if level == 0 else max(2, branches - 2 - level)
        for k in range(nb):
            t = (crown_start if level == 0 else 0.25) + (1 - (crown_start if level == 0 else 0.25)) * (k + r.uniform(0.2, 0.8)) / nb
            idx = min(len(pts) - 2, int(t * n))
            q, rr = pts[idx]
            dd = (pts[idx + 1][0] - q).normalized()
            az = r.uniform(0, 2 * math.pi)
            perp = dd.orthogonal().normalized()
            perp.rotate(Matrix.Rotation(az, 3, dd))
            nd = (dd * 0.5 + perp * r.uniform(0.6, 1.0)).normalized()
            grow(q, nd, length * r.uniform(0.38, 0.55) * (1.0 - t * 0.4), rr * 0.62, level + 1)

    grow(base, (lean[0], lean[1], 1), height, trunk_r, 0)
    return out, tips


def branches_to_curve(name, skel, c, mat):
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    cu.bevel_depth = 1.0
    cu.bevel_resolution = 3
    cu.use_fill_caps = True
    cu.resolution_u = 3
    for pts in skel:
        sp = cu.splines.new('POLY')
        sp.points.add(len(pts) - 1)
        for k, (p, rad) in enumerate(pts):
            sp.points[k].co = (p.x, p.y, p.z, 1)
            sp.points[k].radius = rad
    ob = bpy.data.objects.new(name, cu)
    c.objects.link(ob)
    cu.materials.append(mat)
    return ob


def leaves_at(name, tips, c, mat, per_tip=(30, 50), spread=0.6, size=(0.08, 0.14), seed=0):
    r = rng(seed)
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new('UVMap')
    for p, d in tips:
        for k in range(int(r.integers(*per_tip))):
            q = p + Vector(r.normal(0, spread, 3)) + d * r.uniform(-0.3, 0.3)
            q.z -= abs(r.normal(0, spread * 0.3))
            dd = Vector(r.normal(0, 1, 3)).normalized()
            nrm = Vector((r.normal(0, 0.4), r.normal(0, 0.4), 1)).normalized()
            dd = (dd - nrm * dd.dot(nrm)).normalized()
            L = r.uniform(*size)
            leaf_quad(bm, q, dd, nrm, L, L * 0.55, uv, bend=0.2, segs=2)
    return bm_obj(bm, name, c, mat)


def small_tree(i):
    """Árbol de fondo (valle) para cuando no hay modelos escaneados."""
    c = bpy.context.scene.collection
    bark = M.mat_generic('Corteza', 'corteza', 1.0, box=True)
    leaf = M.mat_hoja('Hoja arbol', base=(0.035, 0.075, 0.018), autumn=0.18)
    h = 7 + 3 * (i % 3)
    skel, tips = tree_skeleton(900 + i, Vector((0, 0, 0)), h * 0.6, 0.22, branches=6, depth=2)
    tr = branches_to_curve('Arbol tronco %d' % i, skel, c, bark)
    lv = leaves_at('Arbol hojas %d' % i, tips, c, leaf, per_tip=(60, 90), spread=1.1, size=(0.2, 0.32), seed=i)
    # convertir la curva a malla y unir
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(tr.evaluated_get(dg))
    tr_m = bpy.data.objects.new('Arbol %d' % i, me)
    c.objects.link(tr_m)
    bpy.data.objects.remove(tr)
    from .util import join
    return join([tr_m, lv], 'Arbol proc %d' % i)
