"""Exterior: viaducto de piedra de dos órdenes de arcos con un tramo hundido,
la vía que sigue por encima (con los carriles colgando sobre el vacío), el valle con
su río y su bosque, la ladera de enfrente, montañas lejanas y una bandada de pájaros."""
import bpy, bmesh, math
import numpy as np
from mathutils import Vector, noise
from . import cfg
from .cfg import Y1, VIA_END, VALLEY_Z
from .util import coll, box, bm_obj, mesh_obj, grid_mesh, adaptive, apply_mods, rng, bevel, join, hidden_coll
from . import materiales as M
from . import tunel as T
from . import plantas as P

PIER = 20.0
PIER_T = 3.6
HALF = 3.0


def yz_prism(name, pts, c, x0=-HALF - 1, x1=HALF + 1):
    """Prisma a lo largo de X con sección pts (y, z)."""
    bm = bmesh.new()
    a = [bm.verts.new((x0, y, z)) for y, z in pts]
    b = [bm.verts.new((x1, y, z)) for y, z in pts]
    bm.faces.new(a)
    bm.faces.new(b[::-1])
    n = len(pts)
    for i in range(n):
        bm.faces.new((a[i], b[i], b[(i + 1) % n], a[(i + 1) % n]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm_obj(bm, name, c)


def arch_void(ya, yb, z_bot, z_spring, seg=40):
    r = (yb - ya) / 2
    yc = (ya + yb) / 2
    pts = [(ya, z_bot), (yb, z_bot)]
    for i in range(seg + 1):
        a = math.pi * i / seg
        pts.append((yc + r * math.cos(a), z_spring + r * math.sin(a)))
    pts.append((ya, z_bot))
    pts = pts[:-1]
    # orden: abajo-izq, abajo-der, arco de der a izq
    return pts


def gap_polygon(seed=3):
    r = rng(seed)
    g0, g1 = cfg.GAP
    base = [(g0 - 3, 8), (g0 + 0.5, -1.5), (g0 + 3.5, -8), (g0 + 7, -17), (g0 + 8.5, -26), (g0 + 11.5, -30.5),
            (g1 - 9.5, -29.5), (g1 - 7.5, -23), (g1 - 5.5, -14), (g1 - 2.5, -6), (g1 - 0.2, -0.8), (g1 + 3, 8)]
    pts = []
    for (y0, z0), (y1, z1) in zip(base, base[1:]):
        for k in range(5):
            t = k / 5
            y, z = y0 + (y1 - y0) * t, z0 + (z1 - z0) * t
            if z < 7:
                y += r.uniform(-0.7, 0.7)
                z += r.uniform(-0.6, 0.6)
            pts.append((y, z))
    pts.append(base[-1])
    return pts


def viaduct(c, stone, cut_c):
    y0, y1 = Y1 - 0.3, VIA_END
    body = box('Viaducto', c, (2 * HALF, y1 - y0, 95), (0, (y0 + y1) / 2, -47.5), stone)
    voids = []
    piers = [Y1 + PIER * k for k in range(1, int((y1 - Y1) / PIER) + 1)]
    edges = [Y1] + piers
    for ya, yb in zip(edges, edges[1:]):
        a, b = ya + PIER_T / 2, yb - PIER_T / 2
        if ya == Y1:
            a = Y1 + 1.2
        voids.append(yz_prism('Arco alto', arch_void(a, b, -29.0, -14.0), cut_c))
        voids.append(yz_prism('Arco bajo', arch_void(a, b, -100.0, -42.0), cut_c))
    gap = yz_prism('Hueco', gap_polygon(), cut_c, -HALF - 2, HALF + 2)
    for v in voids + [gap]:
        v.hide_render = True
    m = body.modifiers.new('arcos', 'BOOLEAN')
    m.operation = 'DIFFERENCE'
    m.solver = 'EXACT'
    m.operand_type = 'COLLECTION'
    m.collection = cut_c
    apply_mods(body)
    adaptive(body)
    # cornisa e impostas
    parts = []
    r = rng(8)
    cor = box('Cornisa viaducto', c, (2 * HALF + 0.7, y1 - y0, 0.4), (0, (y0 + y1) / 2, -0.25), stone)
    imp = [box('Imposta', c, (2 * HALF + 0.5, y1 - y0, 0.5), (0, (y0 + y1) / 2, z), stone) for z in (-29.25, -14.0, -42.0)]
    # pretiles rotos a trozos
    pre = []
    for s in (-1, 1):
        y = y0 + 0.5
        while y < y1 - 1:
            L = r.uniform(1.5, 4.0)
            if r.random() > 0.18:
                h = 0.95 if r.random() > 0.25 else r.uniform(0.3, 0.8)
                pre.append(box('Pretil', c, (0.42, L - 0.02, h), (s * (HALF - 0.21), y + L / 2, h / 2), stone,
                               rot=(0, 0, r.uniform(-0.01, 0.01))))
            y += L
    pre = join(pre, 'Pretiles')
    for o in [cor, pre] + imp:
        mm = o.modifiers.new('hueco', 'BOOLEAN')
        mm.operation = 'DIFFERENCE'
        mm.solver = 'EXACT'
        mm.object = gap
        apply_mods(o)
        bevel(o, 0.03, 2)
    # zócalos de las pilas (ensanchados en la base)
    for yp in piers:
        b = box('Zocalo pila', c, (2 * HALF + 2.5, PIER_T + 2.2, 14), (0, yp, VALLEY_Z - 2), stone, bevel=0.05)
    for o in list(cut_c.objects):
        bpy.data.objects.remove(o)
    bpy.data.collections.remove(cut_c)
    return body


def valley_z(x, y):
    z = VALLEY_Z
    z += max(0.0, 128 - y) ** 1.35 * 0.32                       # canchal al pie del acantilado
    # ladera de enfrente: sube hasta el nivel de la vía, meseta y luego baja hacia una cuenca abierta
    z += min(74.0, max(0.0, y - 282) * 1.15)
    z -= max(0.0, y - 520) * 0.16
    z += max(0.0, abs(x) - 300) * 0.05
    yr = 196 + 26 * math.sin(x / 95.0) + 9 * math.sin(x / 31.0)
    z -= 3.2 * math.exp(-((y - yr) / 9.0) ** 2)                 # cauce del río
    z += noise.fractal(Vector((x / 70.0, y / 70.0, 1.3)), 0.55, 2.0, 5) * 5.0
    z += noise.fractal(Vector((x / 9.0, y / 9.0, 4.4)), 0.5, 2.0, 3) * 0.5
    return z


def river_y(x):
    return 196 + 26 * math.sin(x / 95.0) + 9 * math.sin(x / 31.0)


def valley(c, mat):
    us = np.sign(np.linspace(-1, 1, 301)) * np.abs(np.linspace(-1, 1, 301)) ** 1.6 * 1100
    vs = np.linspace(Y1 - 6, 1300, 300)
    verts, faces, uvs = [], [], []
    W = len(us)
    for y in vs:
        for x in us:
            verts.append((x, y, valley_z(x, y)))
    for j in range(len(vs) - 1):
        for i in range(W - 1):
            a = j * W + i
            f = (a, a + 1, a + 1 + W, a + W)
            faces.append(f)
            uvs.append([(verts[k][0] / 6, verts[k][1] / 6) for k in f])
    ob = mesh_obj('Valle', verts, faces, c, uv=uvs, mat=mat)
    adaptive(ob, 1.5)
    return ob


def river(c):
    m, nb = M.new_material('Rio')
    if nb:
        geo = nb.n('ShaderNodeNewGeometry')
        n = nb.noise(nb.out(geo, 'Position'), scale=0.25, detail=6, dist=0.5)
        b = nb.n('ShaderNodeBump', {'Height': nb.out(n, 'Factor'), 'Strength': 0.08})
        p = M.principled(nb, (0.02, 0.03, 0.025), 0.04, nb.out(b), IOR=1.33)
        M.output(nb, nb.out(p))
    xs = np.linspace(-1100, 1100, 441)
    verts, faces = [], []
    for x in xs:
        yr = river_y(x)
        for d in (-11, 11):
            verts.append((x, yr + d, VALLEY_Z - 1.9))
    for i in range(len(xs) - 1):
        faces.append((2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1))
    return mesh_obj('Rio', verts, faces, c, mat=m)


def mountains(c, mat):
    def f(u, v):
        x = -6000 + 12000 * u
        y = 1250 + 5000 * v
        ridge = 1 - abs(noise.noise(Vector((x / 900, y / 900, 2.0))))
        h = ridge ** 2.2 * 520 + noise.fractal(Vector((x / 400, y / 400, 7.0)), 0.55, 2.0, 6) * 110
        h *= min(1.0, (y - 1250) / 1500 + 0.15)
        return (x, y, h - 80 + max(0.0, abs(x) - 2500) * 0.08)
    ob = grid_mesh('Montanas', 240, 120, f, c, uvscale=40.0, mat=mat)
    return ob


def birds(c, n=22, seed=31):
    """Bandada que sale de los árboles del valle cuando la cámara deja el túnel."""
    r = rng(seed)
    m, nb = M.new_material('Pajaro')
    if nb:
        p = M.principled(nb, (0.015, 0.014, 0.013), 0.6, None)
        M.output(nb, nb.out(p))
    obs = []
    for i in range(n):
        body = bpy.data.objects.new('Pajaro %d' % i, None)
        c.objects.link(body)
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=8, v_segments=6, radius=0.09)
        for v in bm.verts:
            v.co.y *= 2.6
        b = bm_obj(bm, 'Pajaro cuerpo', c, m, smooth=True)
        b.parent = body
        wings = []
        for s in (-1, 1):
            bm = bmesh.new()
            vs = [bm.verts.new(p) for p in ((0, 0.08, 0), (s * 0.55, -0.02, 0), (s * 0.5, -0.12, 0), (0, -0.08, 0))]
            bm.faces.new(vs if s > 0 else vs[::-1])
            w = bm_obj(bm, 'Pajaro ala', c, m)
            w.parent = body
            w.data.materials.append(m)
            ph = r.uniform(0, 8)
            per = r.uniform(7, 10)
            for k in range(3):
                f = 1 + k * per / 2 + ph
                w.rotation_euler = (0, s * (0.55 if k % 2 == 0 else -0.65), 0)
                w.keyframe_insert('rotation_euler', frame=f)
            from .camaras import fcurves_of
            for fc in fcurves_of(w):
                fc.modifiers.new('CYCLES')
        # trayectoria: desde los árboles bajo el viaducto, subiendo y alejándose hacia el sol
        p0 = Vector((r.uniform(-30, 20), r.uniform(150, 200), r.uniform(-55, -40)))
        p1 = p0 + Vector((r.uniform(-30, 30), r.uniform(90, 160), r.uniform(45, 70)))
        f0 = 1250 + int(r.uniform(0, 40))
        body.location = p0
        body.keyframe_insert('location', frame=f0)
        body.location = p1
        body.keyframe_insert('location', frame=f0 + 360)
        d = p1 - p0
        body.rotation_euler = d.to_track_quat('Y', 'Z').to_euler()
        body.scale = (1.6, 1.6, 1.6)
        obs.append(body)
    return obs


def build(main, ctx):
    c = coll('Exterior', main)
    cut_c = coll('Cortes viaducto', main)
    tmats = ctx.get('tunel', {})
    stone = tmats.get('stone') or M.mat_generic('Sillar', 'sillar', 0.33, moss=0.55)
    stone_v = M.mat_generic('Sillar viaducto', 'sillar', 0.3, moss=0.6, disp_scale=0.05)
    viaduct(c, stone_v, cut_c)
    # vía sobre el viaducto: hasta el hundimiento (con los carriles colgando) y después del hueco
    mats = (tmats.get('rail') or M.mat_rail(), tmats.get('wood') or M.mat_generic('Madera traviesas', 'madera', 0.8),
            tmats.get('ballast') or M.mat_generic('Balasto', 'balasto', 0.7, moss=0.3))
    T.track(c, Y1 + 0.4, cfg.GAP[0] + 0.2, mats, seed=5, gap=True, missing=0.1)
    T.track(c, cfg.GAP[1] + 0.5, VIA_END + 15, mats, seed=6, missing=0.1)
    # escombros del tramo hundido en el fondo del valle
    g = (cfg.GAP[0] + cfg.GAP[1]) / 2
    T.rubble(c, (stone_v, tmats.get('soil') or stone_v), (0.0, g), 12.0, 7.0, 90, 71, z0=valley_z(0, g) - 0.5)
    ground = M.mat_generic('Suelo valle', 'pradera', 0.08, moss=0.2, disp_scale=0.4, bump=1.0)
    val = valley(c, ground)
    river(c)
    mnt = M.mat_generic('Montana', 'roca', 0.01, moss=0.6, bump=0.5)
    mountains(c, mnt)
    # bosque del valle y arbustos
    from .vegetacion import scatter, set_density
    trees = P.library('arbol', P.small_tree, n_fallback=3)
    shrubs = P.library('arbusto', P.shrub)

    def forest(x, y, z):
        d_river = abs(y - river_y(x))
        if d_river < 14 or y < 112:
            return 0.0
        n = noise.fractal(Vector((x / 120, y / 120, 5.5)), 0.6, 2.0, 3)
        return max(0.0, min(1.0, 0.55 + n * 1.2)) * min(1.0, (d_river - 14) / 15)
    set_density(val, forest)
    mon = bpy.data.objects.get('Monte')
    if mon:
        set_density(mon, lambda x, y, z: max(0.0, min(1.0, 0.6 + noise.fractal(Vector((x / 90, y / 90, 2.2)), 0.6, 2.0, 3) * 1.3)))
        scatter('Bosque monte', mon, trees, 0.006, c, scale=(0.8, 1.6), seed=510, tilt=0.06, sway=0.015)
        scatter('Arbustos monte lejos', mon, shrubs, 0.02, c, scale=(1.2, 2.4), seed=511, sway=0.02)
    scatter('Bosque', val, trees, 0.0065, c, scale=(0.8, 1.5), seed=500, tilt=0.06, sway=0.015)
    scatter('Arbustos valle', val, shrubs, 0.03, c, scale=(1.0, 2.2), seed=501, sway=0.02)
    lib_h = P.library('hierba', P.grass)
    scatter('Hierba valle', val, lib_h, 0.5, c, scale=(1.0, 1.8), seed=502)
    birds(c)
    return {}
