"""El pozo de ventilación por el que baja el personaje: brocal de hormigón con la tapa de
hierro apartada, el tubo del pozo, la escalera de pates oxidada (que sigue por el muro del
túnel hasta el suelo), un cartel viejo y el camino de tierra que llega hasta él por el monte."""
import bpy, bmesh, math
import numpy as np
from mathutils import Vector, noise
from . import cfg
from .util import coll, box, cyl, bm_obj, bevel, rng, join, mesh_obj, apply_mods, adaptive
from . import materiales as M

SX, SY = cfg.SHAFT
R_IN = cfg.SHAFT_R
R_OUT = cfg.SHAFT_R + 0.18
COLLAR = 1.2                  # medio lado de la losa del brocal

# Camino de tierra: llega desde el bosque (-X) y acaba junto al brocal
PATH = [(-78.0, -76.0), (-64.0, -84.0), (-50.0, -93.0), (-38.0, -100.0), (-27.0, -106.5), (-18.0, -111.0),
        (-11.0, -114.6), (-7.2, -116.9), (-5.3, -117.7)]
PATH_W = 1.25


def ground_z(x, y):
    from .tunel import top_z
    return top_z(x, y)


GZ = None   # cota del terreno en el brocal (se calcula al construir)


def in_collar(x, y):
    # se borran las caras del terreno que tocan el hueco; las que quedan las tapa la losa
    return math.hypot(x - SX, y - SY) < 0.93


# ------------------------------------------------------------------ camino
def path_samples(step=0.2):
    """Puntos del eje del camino cada 'step' metros (curva suave por Catmull-Rom)."""
    P = [Vector((x, y, 0)) for x, y in PATH]
    P = [P[0] * 2 - P[1]] + P + [P[-1] * 2 - P[-2]]
    pts = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        n = max(2, int((p2 - p1).length / step))
        for k in range(n):
            t = k / n
            t2, t3 = t * t, t * t * t
            q = 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)
            pts.append(q)
    pts.append(P[-2])
    return pts


_PATH_NP = None


def path_dist(x, y):
    """Distancia (m) al eje del camino (para que no crezca hierba encima)."""
    global _PATH_NP
    if _PATH_NP is None:
        _PATH_NP = np.array([(p.x, p.y) for p in path_samples(0.5)])
    d = np.hypot(_PATH_NP[:, 0] - x, _PATH_NP[:, 1] - y)
    return float(d.min())


def clearance(x, y):
    """0 sobre el camino y junto al brocal, 1 lejos (multiplica la densidad de la vegetación)."""
    d = path_dist(x, y)
    k = min(1.0, max(0.0, (d - PATH_W * 0.45) / 0.9))
    dc = math.hypot(x - SX, y - SY)
    k = min(k, min(1.0, max(0.0, (dc - 1.6) / 1.2)))
    # un claro pisado alrededor del pozo
    return k


def mat_camino():
    m, nb = M.new_material('Camino de tierra')
    if nb is None:
        return m
    tc = nb.n('ShaderNodeTexCoord')
    uv = nb.out(tc, 'UV')
    sep = nb.separate(uv)
    u = nb.out(sep, 'X')                     # -1..1 a lo ancho
    vec = M.coords(nb, 0.45)
    mud = M.texset(nb, 'tierra', vec, box=True, tint=(0.8, 0.72, 0.62))
    stones = M.texset(nb, 'balasto', M.coords(nb, 0.9), box=True, tint=(0.75, 0.72, 0.68))
    geo = nb.n('ShaderNodeNewGeometry')
    pos = nb.out(geo, 'Position')
    n1 = nb.out(nb.noise(pos, scale=0.7, detail=6, rough=0.6), 'Factor')
    s = M.mix_sets(nb, nb.maprange(n1, 0.55, 0.7), mud, stones)
    # rodadas: dos surcos húmedos y oscuros, con charcos
    ru = nb.math('ABSOLUTE', nb.math('SUBTRACT', nb.math('ABSOLUTE', u), 0.48))
    n2 = nb.out(nb.noise(pos, scale=1.6, detail=3, rough=0.5), 'Factor')
    rut = nb.math('MULTIPLY', nb.maprange(ru, 0.2, 0.05), nb.maprange(n2, 0.35, 0.6))
    puddle = nb.math('MULTIPLY', rut, nb.maprange(n2, 0.58, 0.62))
    color = nb.mix(nb.math('MULTIPLY', rut, 0.6), s.color, (0.03, 0.022, 0.015))
    color = nb.mix(puddle, color, (0.01, 0.01, 0.01))
    rough = nb.mix(rut, s.rough, 0.35, kind='FLOAT')
    rough = nb.mix(puddle, rough, 0.04, kind='FLOAT')
    # bordes deshilachados: el camino se funde con la hierba
    n3 = nb.out(nb.noise(pos, scale=2.2, detail=6, rough=0.65), 'Factor')
    edge = nb.math('ADD', nb.math('ABSOLUTE', u), nb.math('MULTIPLY', nb.math('SUBTRACT', n3, 0.5), 0.7))
    alpha = nb.maprange(edge, 0.95, 0.72)
    p = M.principled(nb, color, rough, s.normal)
    tr = nb.n('ShaderNodeBsdfTransparent')
    mix = nb.n('ShaderNodeMixShader', {0: alpha, 1: nb.out(tr), 2: nb.out(p)})
    M.output(nb, nb.out(mix), None, m)
    return m


def path_ribbon(c):
    pts = path_samples(0.18)
    verts, faces, uvs = [], [], []
    nx = 12
    for i, p in enumerate(pts):
        a = pts[max(0, i - 1)]
        b = pts[min(len(pts) - 1, i + 1)]
        t = (b - a).normalized()
        side = Vector((-t.y, t.x, 0))
        # más ancho junto al brocal (zona pisada)
        w = PATH_W * (1.0 + 0.6 * max(0.0, 1 - (p - Vector((SX, SY, 0))).length / 4.0))
        for k in range(nx + 1):
            s = -1 + 2 * k / nx
            q = p + side * s * w / 2
            z = ground_z(q.x, q.y) + 0.012
            verts.append((q.x, q.y, z))
    W = nx + 1
    L = 0.0
    for i in range(len(pts) - 1):
        L1 = L + (pts[i + 1] - pts[i]).length
        for k in range(nx):
            a = i * W + k
            faces.append((a, a + 1, a + 1 + W, a + W))
            u0, u1 = -1 + 2 * k / nx, -1 + 2 * (k + 1) / nx
            uvs.append([(u0, L), (u1, L), (u1, L1), (u0, L1)])
        L = L1
    ob = mesh_obj('Camino', verts, faces, c, uv=uvs, mat=mat_camino())
    ob.visible_shadow = False
    return ob


# ------------------------------------------------------------------ pozo
def cut_shell(shell):
    """Abre el pozo en la bóveda del túnel (las caras del corte llevan el hormigón del pozo)."""
    conc = mat_hormigon()
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=48, radius1=R_OUT, radius2=R_OUT, depth=40)
    ct = bm_obj(bm, 'Corte pozo', bpy.context.scene.collection, conc)
    ct.location = (SX, SY, 3.45 + 20)
    m = shell.modifiers.new('pozo', 'BOOLEAN')
    m.operation = 'DIFFERENCE'
    m.solver = 'EXACT'
    m.object = ct
    m.material_mode = 'TRANSFER'
    apply_mods(shell)
    bpy.data.objects.remove(ct)


def mat_hormigon():
    m = bpy.data.materials.get('Hormigon pozo')
    if m:
        return m
    return M.mat_generic('Hormigon pozo', 'hormigon', 0.5, moss=0.35, wet=0.6, bump=1.3, weather=0.7,
                         weather_z=(cfg.CROWN + 3.0, 0.0))


def mat_hierro():
    """Hierro de los pates: óxido escamado, y brillo de metal gastado donde se pisa y se agarra."""
    m, nb = M.new_material('Hierro escalera')
    if nb is None:
        return m
    rust = M.texset(nb, 'oxido', M.coords(nb, 3.0), box=True, bump=1.8)
    geo = nb.n('ShaderNodeNewGeometry')
    nz = nb.out(nb.separate(nb.out(geo, 'Normal')), 'Z')
    n = nb.out(nb.noise(nb.out(geo, 'Position'), scale=14, detail=6, rough=0.6), 'Factor')
    worn = nb.math('MULTIPLY', nb.maprange(nz, 0.6, 0.95), nb.maprange(n, 0.35, 0.6))
    color = nb.mix(worn, rust.color, (0.16, 0.15, 0.14))
    rough = nb.mix(worn, rust.rough, 0.38, kind='FLOAT')
    p = M.principled(nb, color, rough, rust.normal, Metallic=nb.math('MULTIPLY', worn, 0.85))
    M.output(nb, nb.out(p), None, m)
    return m


def tube(name, c, r_in, r_out, z0, z1, mat, seg=48):
    bm = bmesh.new()
    rings = []
    for z in (z0, z1):
        ri = [bm.verts.new((r_in * math.cos(2 * math.pi * k / seg), r_in * math.sin(2 * math.pi * k / seg), z)) for k in range(seg)]
        ro = [bm.verts.new((r_out * math.cos(2 * math.pi * k / seg), r_out * math.sin(2 * math.pi * k / seg), z)) for k in range(seg)]
        rings.append((ri, ro))
    (i0, o0), (i1, o1) = rings
    for k in range(seg):
        k2 = (k + 1) % seg
        bm.faces.new((i0[k], i1[k], i1[k2], i0[k2]))          # cara interior
        bm.faces.new((o0[k], o0[k2], o1[k2], o1[k]))          # exterior
        bm.faces.new((i1[k], o1[k], o1[k2], i1[k2]))          # arriba
        bm.faces.new((i0[k], i0[k2], o0[k2], o0[k]))          # abajo
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = bm_obj(bm, name, c, mat)
    ob.location = (SX, SY, 0)
    return ob


def shaft(c):
    """Tubo de anillos de hormigón desde la bóveda hasta el brocal."""
    from .tunel import prism_profile, profile
    conc = mat_hormigon()
    obs = []
    z = 2.6
    k = 0
    r = rng(71)
    while z < GZ - 0.05:
        h = min(1.0, GZ - 0.05 - z)
        ring = tube('Anillo pozo', c, R_IN + r.uniform(-0.004, 0.004), R_OUT, z, z + h - 0.012, conc)
        obs.append(ring)
        z += h
        k += 1
    sh = join(obs, 'Pozo')
    # se recorta por la bóveda (el tubo acaba en el intradós)
    inner = prism_profile('tmp', profile(0.0), SY - 3, SY + 3, c)
    m = sh.modifiers.new('boveda', 'BOOLEAN')
    m.operation = 'DIFFERENCE'
    m.solver = 'EXACT'
    m.object = inner
    apply_mods(sh)
    bpy.data.objects.remove(inner)
    bevel(sh, 0.01, 1)
    return sh


def collar(c):
    conc = mat_hormigon()
    # brocal: losa cuadrada con el hueco redondo
    b = box('Brocal', c, (2 * COLLAR, 2 * COLLAR, 0.75), (SX, SY, GZ - 0.25), conc)
    hole = cyl('tmp', c, R_IN, 2.0, (SX, SY, GZ), None, seg=48)
    m = b.modifiers.new('hueco', 'BOOLEAN')
    m.operation = 'DIFFERENCE'
    m.solver = 'EXACT'
    m.object = hole
    apply_mods(b)
    bpy.data.objects.remove(hole)
    bevel(b, 0.025, 2)
    # marco de hierro del registro
    iron = mat_hierro()
    fr = tube('Marco tapa', c, R_IN, R_IN + 0.07, GZ + 0.11, GZ + 0.135, iron)
    fr.location = (SX, SY, 0)
    # la tapa de fundición, apartada y apoyada en el borde del brocal
    cover = cast_iron_cover(c, iron)
    cover.location = (SX + 1.25, SY + 0.55, GZ + 0.03)
    cover.rotation_euler = (math.radians(-6), math.radians(9), math.radians(23))
    return [b, fr, cover]


def cast_iron_cover(c, mat):
    """Tapa de registro de fundición: disco con nervios en rejilla y letras en relieve."""
    rr = 0.66
    obs = [cyl('Tapa registro', c, rr, 0.045, (0, 0, 0), mat, seg=64)]
    # nervios en rejilla (dibujo antideslizante)
    for k in range(-6, 7):
        L = 2 * math.sqrt(max(0.0, (rr - 0.06) ** 2 - (k * 0.09) ** 2))
        if L > 0.05:
            obs.append(box('Nervio', c, (L, 0.018, 0.014), (0, k * 0.09, 0.028), mat))
            obs.append(box('Nervio', c, (0.018, L, 0.014), (k * 0.09, 0, 0.028), mat))
    ring = cyl('Aro tapa', c, rr - 0.015, 0.02, (0, 0, 0.031), mat, seg=64)
    obs.append(ring)
    cover = join(obs, 'Tapa registro')
    bevel(cover, 0.004, 1)
    return cover


def ladder(c):
    """Pates: dos largueros con peldaños redondos cada 30 cm, del suelo del túnel al brocal,
    con los anclajes al muro (o al pozo) y el pasamanos que asoma por encima."""
    iron = mat_hierro()
    x = cfg.LADDER_X
    top = GZ + 1.05
    obs = []
    for s in (-1, 1):
        y = SY + s * 0.215
        obs.append(box('Larguero escalera', c, (0.012, 0.065, top - 0.05), (x - 0.03, y, (top + 0.05) / 2), iron))
    rungs = []
    z = 0.42
    while z < GZ + 0.95:
        rungs.append(z)
        obs.append(cyl('Peldano', c, 0.0135, 0.43, (x, SY, z), iron, rot=(math.pi / 2, 0, 0), seg=12))
        z += cfg.RUNG_STEP
    # anclajes: al muro del túnel por debajo de los arranques, al pozo por encima
    z = 0.6
    while z < GZ:
        wall_x = -cfg.HALF_W if z < cfg.WALL_H else SX - R_IN
        for s in (-1, 1):
            L = (x - 0.03) - wall_x
            obs.append(box('Anclaje', c, (L, 0.05, 0.012), ((x - 0.03 + wall_x) / 2, SY + s * 0.215, z), iron))
        z += 1.5
    # pasamanos curvo por encima del brocal
    hoop = []
    for i in range(13):
        a = math.pi * i / 12
        yy = SY + 0.215 * math.cos(a)
        zz = top + 0.18 * math.sin(a)
        hoop.append((x - 0.03, yy, zz))
    from .tunel import sweep
    prof = [(0.015 * math.cos(2 * math.pi * k / 10), 0.015 * math.sin(2 * math.pi * k / 10)) for k in range(10)]
    obs.append(sweep('Pasamanos', prof, hoop, c, iron))
    lad = join(obs, 'Escalera de pates')
    bevel(lad, 0.003, 1)
    return lad, rungs


def sign(c):
    """Cartel viejo de RENFE en un poste junto al pozo."""
    paint = M.mat_metal_loco('Cartel chapa', paint=(0.55, 0.5, 0.42))
    wood = bpy.data.materials.get('Madera traviesas') or M.mat_generic('Madera traviesas', 'madera', 0.8)
    px, py = SX - 1.9, SY - 1.45
    gz = ground_z(px, py)
    post = box('Poste cartel', c, (0.1, 0.1, 1.9), (px, py, gz + 0.8), wood, rot=(0.03, -0.05, 0.2))
    bevel(post, 0.01, 1)
    plate = box('Cartel', c, (0.62, 0.02, 0.42), (px + 0.02, py + 0.07, gz + 1.45), paint,
                rot=(0.03, -0.12, 0.2))
    texts = []
    red = M.mat_metal_loco('Cartel letras', paint=(0.35, 0.03, 0.02))
    for k, (t, sz, dz) in enumerate((('PELIGRO', 0.085, 0.12), ('POZO DE VENTILACIÓN Nº 4', 0.036, 0.0),
                                      ('PROHIBIDO EL PASO', 0.04, -0.08), ('RENFE', 0.05, -0.15))):
        cu = bpy.data.curves.new('cartel', 'FONT')
        cu.body = t
        cu.size = sz
        cu.extrude = 0.001
        cu.align_x = 'CENTER'
        cu.align_y = 'CENTER'
        ob = bpy.data.objects.new('Texto cartel', cu)
        c.objects.link(ob)
        ob.parent = plate
        ob.location = (0, 0.011, dz)
        ob.rotation_euler = (math.pi / 2, 0, 0)
        cu.materials.append(red)
        texts.append(ob)
    # un trozo de valla caída
    for k in range(3):
        fx, fy = SX - 3.2 + k * 1.6, SY + 2.6 + k * 0.3
        fz = ground_z(fx, fy)
        p = box('Poste valla', c, (0.07, 0.07, 1.2), (fx, fy, fz + 0.45), wood,
                rot=(0.05 * (k - 1), 0.25 if k == 2 else 0.04, 0.1 * k))
        bevel(p, 0.008, 1)
    return [post, plate]


def build(main, ctx):
    global GZ
    c = coll('Pozo', main)
    GZ = ground_z(SX, SY) + 0.05
    sh = shaft(c)
    col = collar(c)
    lad, rungs = ladder(c)
    sign(c)
    path_ribbon(c)
    return {'gz': GZ, 'rungs': rungs, 'ladder': lad}
