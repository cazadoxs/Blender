"""El personaje: un excursionista con chubasquero con capucha, braga al cuello hasta la nariz,
pantalón de montaña, botas, guantes, mochila y una linterna frontal. Se modela con metabolas
(formas blandas que se funden como un cuerpo con ropa), se convierte en malla y se le pone un
esqueleto con cinemática inversa en piernas y brazos.

En reposo mira hacia -Y (convención de Blender: .L es el lado +X, su izquierda)."""
import bpy, bmesh, math
import numpy as np
from mathutils import Vector, Matrix, Quaternion, Euler, noise
from . import cfg
from .util import coll, box, cyl, bm_obj, bevel, rng, join, NB, apply_mods
from . import materiales as M

# ------------------------------------------------------------------ esqueleto (metros, mirando a -Y)
BONES = [
    # nombre, cabeza, cola, padre, deforma, radio (para los pesos)
    ('cadera', (0, 0.0, 0.95), (0, 0.0, 1.06), None, True, 0.16),
    ('columna', (0, 0.0, 1.06), (0, 0.0, 1.24), 'cadera', True, 0.15),
    ('pecho', (0, 0.0, 1.24), (0, 0.01, 1.44), 'columna', True, 0.17),
    ('cuello', (0, 0.01, 1.44), (0, 0.0, 1.55), 'pecho', True, 0.06),
    ('cabeza', (0, 0.0, 1.55), (0, 0.0, 1.76), 'cuello', True, 0.1),
]
for s, X in (('L', 1), ('R', -1)):
    BONES += [
        ('clavicula.' + s, (X * 0.02, 0.0, 1.42), (X * 0.17, 0.03, 1.43), 'pecho', True, 0.05),
        ('brazo.' + s, (X * 0.18, 0.03, 1.42), (X * 0.345, 0.05, 1.18), 'clavicula.' + s, True, 0.058),
        ('antebrazo.' + s, (X * 0.345, 0.05, 1.18), (X * 0.49, 0.02, 0.97), 'brazo.' + s, True, 0.048),
        ('mano.' + s, (X * 0.49, 0.02, 0.97), (X * 0.545, 0.0, 0.88), 'antebrazo.' + s, True, 0.04),
        ('muslo.' + s, (X * 0.095, 0.0, 0.93), (X * 0.10, -0.018, 0.50), 'cadera', True, 0.085),
        ('pierna.' + s, (X * 0.10, -0.018, 0.50), (X * 0.105, 0.03, 0.095), 'muslo.' + s, True, 0.06),
        ('pie.' + s, (X * 0.105, 0.03, 0.095), (X * 0.11, -0.11, 0.035), 'pierna.' + s, True, 0.05),
    ]
HEIGHT = 1.76
LEG = 0.93 - 0.095          # cadera-tobillo en reposo (estirada ~0.86)

R = {}   # referencias que usa la animación


# ------------------------------------------------------------------ materiales
def _fabric(name, color, rough, scale=40.0, wrinkle=0.6, sheen=0.0, coat=0.0, role='tela', mud=0.0):
    m, nb = M.new_material(name)
    if nb is None:
        return m
    vec = M.coords(nb, scale)
    t = M.texset(nb, role, vec, box=True, bump=0.6, antitile=False, macro=0.0)
    bw = nb.out(nb.n('ShaderNodeRGBToBW', {0: t.color}))
    k = nb.maprange(bw, 0.0, 0.6, 0.75, 1.2)
    col = nb.mix(1.0, color, nb.combine(k, k, k), blend='MULTIPLY')
    geo = nb.n('ShaderNodeNewGeometry')
    tc = nb.n('ShaderNodeTexCoord')
    obj = nb.out(tc, 'Object')
    # pliegues: ruido estirado + crestas de voronoi
    st = nb.out(nb.n('ShaderNodeMapping', {'Vector': obj, 'Scale': (14, 14, 5)}))
    n1 = nb.out(nb.noise(st, scale=1.0, detail=3, rough=0.5, dist=0.6), 'Factor')
    vo = nb.n('ShaderNodeTexVoronoi', {'Vector': obj, 'Scale': 9.0}, feature='DISTANCE_TO_EDGE')
    h = nb.math('ADD', nb.math('MULTIPLY', n1, 0.7), nb.math('MULTIPLY', nb.maprange(nb.out(vo, 'Distance'), 0.0, 0.08), 0.3))
    # suciedad y barro en la parte de abajo (coordenadas del objeto: z = altura)
    z = nb.out(nb.separate(obj), 'Z')
    dirt_n = nb.out(nb.noise(obj, scale=6, detail=6, rough=0.65), 'Factor')
    if mud > 0:
        mm = nb.math('MULTIPLY', nb.maprange(nb.math('ADD', z, nb.math('MULTIPLY', dirt_n, 0.25)), 0.42, 0.18), mud)
        col = nb.mix(mm, col, (0.06, 0.042, 0.025))
        rough_v = nb.mix(mm, rough, 0.9, kind='FLOAT')
    else:
        rough_v = rough
    col = nb.mix(nb.math('MULTIPLY', nb.maprange(dirt_n, 0.5, 0.8), 0.25), col, (0.05, 0.045, 0.04))
    b1 = nb.n('ShaderNodeBump', {'Height': h, 'Strength': 0.35 * wrinkle, 'Distance': 0.02})
    if t.normal is not None:
        nb.set(b1.inputs['Normal'], t.normal)
    p = M.principled(nb, col, rough_v, nb.out(b1), Sheen_Weight=sheen, Sheen_Roughness=0.4, Coat_Weight=coat,
                     Coat_Roughness=0.25)
    M.output(nb, nb.out(p), None, m)
    return m


def mat_piel():
    m, nb = M.new_material('Piel')
    if nb is None:
        return m
    tc = nb.n('ShaderNodeTexCoord')
    n = nb.out(nb.noise(nb.out(tc, 'Object'), scale=180, detail=6, rough=0.6), 'Factor')
    n2 = nb.out(nb.noise(nb.out(tc, 'Object'), scale=25, detail=3), 'Factor')
    col = nb.mix(nb.maprange(n2, 0.3, 0.7), (0.42, 0.26, 0.19), (0.55, 0.36, 0.28))
    b = nb.n('ShaderNodeBump', {'Height': n, 'Strength': 0.12, 'Distance': 0.002})
    p = M.principled(nb, col, nb.maprange(n, 0.3, 0.7, 0.38, 0.55), nb.out(b), Subsurface_Weight=0.35,
                     Subsurface_Radius=(1.0, 0.35, 0.18), Subsurface_Scale=0.008)
    M.output(nb, nb.out(p), None, m)
    return m


def mat_ojo():
    m, nb = M.new_material('Ojo')
    if nb is None:
        return m
    tc = nb.n('ShaderNodeTexCoord')
    # el eje Y del objeto mira hacia delante (-Y): iris y pupila según el ángulo
    sep = nb.separate(nb.out(tc, 'Object'))
    yv = nb.math('MULTIPLY', nb.out(sep, 'Y'), -1.0)
    d = nb.math('SQRT', nb.math('ADD', nb.math('POWER', nb.out(sep, 'X'), 2.0), nb.math('POWER', nb.out(sep, 'Z'), 2.0)))
    front = nb.math('GREATER_THAN', yv, 0.0)
    iris = nb.math('MULTIPLY', nb.math('LESS_THAN', d, 0.0062), front)
    pupil = nb.math('MULTIPLY', nb.math('LESS_THAN', d, 0.0028), front)
    col = nb.mix(iris, (0.75, 0.72, 0.68), (0.12, 0.08, 0.04))
    col = nb.mix(pupil, col, (0.005, 0.005, 0.005))
    p = M.principled(nb, col, 0.05, None, Coat_Weight=1.0, Coat_Roughness=0.02, Subsurface_Weight=0.1)
    M.output(nb, nb.out(p), None, m)
    return m


def materials():
    return {
        'chaqueta': _fabric('Chaqueta', (0.030, 0.048, 0.042), 0.42, scale=60, wrinkle=0.9, sheen=0.15, coat=0.25, mud=0.3),
        'pantalon': _fabric('Pantalon', (0.045, 0.045, 0.048), 0.8, scale=45, wrinkle=0.7, mud=1.0),
        'braga': _fabric('Braga cuello', (0.06, 0.058, 0.062), 0.95, scale=90, wrinkle=0.4, sheen=0.4),
        'guante': _fabric('Guantes', (0.018, 0.018, 0.02), 0.55, scale=70, wrinkle=0.5, coat=0.15, role='cuero', mud=0.3),
        'bota': _fabric('Botas', (0.075, 0.045, 0.024), 0.55, scale=25, wrinkle=0.4, coat=0.2, role='cuero', mud=1.0),
        'suela': _fabric('Suela', (0.02, 0.02, 0.02), 0.85, scale=30, wrinkle=0.2, mud=1.0),
        'mochila': _fabric('Mochila', (0.16, 0.045, 0.018), 0.55, scale=55, wrinkle=0.6, sheen=0.1, coat=0.15),
        'cinta': _fabric('Cintas', (0.012, 0.012, 0.013), 0.6, scale=120, wrinkle=0.2),
        'plastico': M.principled_material('Plastico negro', (0.02, 0.02, 0.022), 0.35) if hasattr(M, 'principled_material') else _plastic(),
        'piel': mat_piel(),
        'ojo': mat_ojo(),
    }


def _plastic():
    m, nb = M.new_material('Plastico negro')
    if nb:
        p = M.principled(nb, (0.02, 0.02, 0.022), 0.35, None, Coat_Weight=0.3)
        M.output(nb, nb.out(p))
    return m


# ------------------------------------------------------------------ metabolas
def meta_object(name, c, res, elements, thresh=0.6):
    mb = bpy.data.metaballs.new(name)
    mb.resolution = res
    mb.render_resolution = res
    mb.threshold = thresh
    ob = bpy.data.objects.new(name, mb)
    c.objects.link(ob)
    for kind, co, radius, rot, size, stiff in elements:
        e = mb.elements.new(type=kind)
        e.co = co
        e.radius = radius
        e.stiffness = stiff
        if rot is not None:
            e.rotation = rot
        if size is not None:
            if kind == 'ELLIPSOID' or kind == 'CUBE':
                e.size_x, e.size_y, e.size_z = size
            elif kind == 'CAPSULE':
                e.size_x = size[0]
    return ob


def to_mesh(ob, name):
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev)
    me.name = name
    mo = bpy.data.objects.new(name, me)
    for c in ob.users_collection:
        c.objects.link(mo)
    bpy.data.objects.remove(ob)
    mo.data.shade_smooth()
    return mo


def seg_balls(p0, p1, r0, r1, n, stiff=2.0):
    """Bolas a lo largo de un segmento con radio interpolado."""
    out = []
    p0, p1 = Vector(p0), Vector(p1)
    for i in range(n):
        u = i / (n - 1)
        out.append(('BALL', p0.lerp(p1, u), r0 + (r1 - r0) * u, None, None, stiff))
    return out


def J(name, end='head'):
    for b in BONES:
        if b[0] == name:
            return Vector(b[1] if end == 'head' else b[2])
    raise KeyError(name)


# ------------------------------------------------------------------ mallas por secciones (loft)
def ring(center, u, v, rx, ry, n=24, ex=2.0):
    """Sección supereliptica: centro y ejes u, v (vectores unitarios)."""
    pts = []
    for k in range(n):
        a = 2 * math.pi * k / n
        ca, sa = math.cos(a), math.sin(a)
        x = math.copysign(abs(ca) ** (2 / ex), ca) * rx
        y = math.copysign(abs(sa) ** (2 / ex), sa) * ry
        pts.append(Vector(center) + Vector(u) * x + Vector(v) * y)
    return pts


def loft(bm, rings_):
    """Une secciones seguidas en un tubo cerrado por los extremos."""
    vs = [[bm.verts.new(p) for p in r] for r in rings_]
    n = len(rings_[0])
    for a, b in zip(vs, vs[1:]):
        for k in range(n):
            bm.faces.new((a[k], a[(k + 1) % n], b[(k + 1) % n], b[k]))
    bm.faces.new(vs[0][::-1])
    bm.faces.new(vs[-1])


def path_frames(pts, up_hint=Vector((0, -1, 0))):
    """Marcos (tangente, u, v) estables a lo largo de una polilínea."""
    out = []
    for i, p in enumerate(pts):
        t = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        u = up_hint - t * up_hint.dot(t)
        if u.length < 1e-4:
            u = Vector((1, 0, 0)) - t * t.x
        u.normalize()
        v = t.cross(u)
        out.append((t, u, v))
    return out


def limb(bm, pts, radii, up_hint, n=20, ex=2.0, ratio=1.0):
    """Tubo por una curva con radios (r, o (ru, rv)) por punto."""
    pts = [Vector(p) for p in pts]
    fr = path_frames(pts, up_hint)
    rings_ = []
    for p, (t, u, v), r in zip(pts, fr, radii):
        ru, rv = (r, r * ratio) if not isinstance(r, tuple) else r
        rings_.append(ring(p, u, v, ru, rv, n, ex))
    loft(bm, rings_)


def resample(points, step):
    """Puntos cada 'step' por una polilínea, con el parámetro 0..1 de cada uno."""
    P = [Vector(p) for p in points]
    L = [0.0]
    for a, b in zip(P, P[1:]):
        L.append(L[-1] + (b - a).length)
    out = []
    n = max(2, int(L[-1] / step) + 1)
    for i in range(n):
        d = L[-1] * i / (n - 1)
        k = max(0, min(len(P) - 2, np.searchsorted(L, d) - 1))
        u = (d - L[k]) / max(1e-9, L[k + 1] - L[k])
        out.append((P[k].lerp(P[k + 1], u), d / L[-1]))
    return out


def prof(u, table):
    """Interpola una tabla [(u, valor)] (valor escalar o tupla)."""
    us = [t[0] for t in table]
    i = max(0, min(len(us) - 2, np.searchsorted(us, u) - 1))
    a, b = table[i], table[i + 1]
    w = (u - a[0]) / max(1e-9, b[0] - a[0])
    w = w * w * (3 - 2 * w)
    if isinstance(a[1], tuple):
        return tuple(x + (y - x) * w for x, y in zip(a[1], b[1]))
    return a[1] + (b[1] - a[1]) * w


def unify(bm, name, c, voxel, smooth=6, smooth_f=0.5):
    """Funde las piezas solapadas en una sola superficie (remallado por vóxeles) y la suaviza."""
    ob = bm_obj(bm, name, c)
    rm = ob.modifiers.new('fundir', 'REMESH')
    rm.mode = 'VOXEL'
    rm.voxel_size = voxel
    rm.use_smooth_shade = True
    if smooth:
        sm = ob.modifiers.new('suavizar', 'LAPLACIANSMOOTH')
        sm.iterations = smooth
        sm.lambda_factor = smooth_f
        sm.use_volume_preserve = True
    apply_mods(ob)
    ob.data.shade_smooth()
    return ob


def body_mesh(c):
    """Cuerpo vestido: tronco con chubasquero, brazos y piernas (sin manos, cabeza ni botas)."""
    bm = bmesh.new()
    # tronco: secciones supereliptícas a distintas alturas (ancho, fondo, desplazamiento en y)
    T = [(0.76, 0.12, 0.085, 0.01), (0.82, 0.155, 0.105, 0.012), (0.88, 0.168, 0.116, 0.012), (0.95, 0.17, 0.118, 0.008),
         (1.02, 0.158, 0.112, 0.004), (1.1, 0.162, 0.115, 0.0), (1.2, 0.176, 0.125, -0.002), (1.3, 0.186, 0.13, 0.0),
         (1.37, 0.19, 0.122, 0.006), (1.42, 0.175, 0.105, 0.012), (1.46, 0.12, 0.085, 0.015), (1.49, 0.075, 0.07, 0.015),
         (1.53, 0.062, 0.062, 0.012), (1.57, 0.06, 0.062, 0.01)]
    rings_ = [ring((0, y, z), (1, 0, 0), (0, 1, 0), rx, ry, 32, 2.6 if z < 1.44 else 2.0) for z, rx, ry, y in T]
    loft(bm, rings_)
    for s, X in (('L', 1), ('R', -1)):
        # pierna: de dentro de la cadera al tobillo (el pantalón se mete en la bota)
        hip = Vector((X * 0.092, 0.005, 0.9))
        knee = J('pierna.' + s)
        ank = Vector((X * 0.105, 0.03, 0.15))
        pts = [p for p, _ in resample([hip, knee, ank], 0.02)]
        rad = []
        for p, u in resample([hip, knee, ank], 0.02):
            rad.append(prof(u, [(0.0, (0.098, 0.105)), (0.25, (0.085, 0.09)), (0.5, (0.066, 0.07)), (0.53, (0.066, 0.07)),
                                (0.7, (0.064, 0.067)), (1.0, (0.058, 0.06))]))
        limb(bm, pts, rad, Vector((1, 0, 0)), n=24)
        # brazo con manga
        sh = Vector((X * 0.15, 0.025, 1.4))
        el = J('antebrazo.' + s)
        wr = J('mano.' + s) + (J('mano.' + s) - el).normalized() * 0.01
        ar = resample([sh, J('brazo.' + s), el, wr], 0.018)
        rad = [prof(u, [(0.0, 0.07), (0.15, 0.064), (0.5, 0.054), (0.56, 0.05), (0.85, 0.047), (0.97, 0.05), (1.0, 0.049)])
               for _, u in ar]
        limb(bm, [p for p, _ in ar], rad, Vector((0, 1, 0)), n=20)
        # hombro redondeado
        limb(bm, [Vector((X * 0.08, 0.02, 1.42)), Vector((X * 0.2, 0.03, 1.405))], [0.06, 0.07], Vector((0, 1, 0)), n=20)
    ob = unify(bm, 'Cuerpo', c, 0.0085, smooth=8, smooth_f=0.6)
    # arrugas y pliegues de la ropa: desplazamiento suave
    tex = bpy.data.textures.new('Pliegues ropa', 'CLOUDS')
    tex.noise_scale = 0.06
    tex.noise_depth = 2
    d = ob.modifiers.new('pliegues', 'DISPLACE')
    d.texture = tex
    d.strength = 0.007
    d.mid_level = 0.5
    d.texture_coords = 'OBJECT'
    return ob


def hand_mesh(c, side):
    """Guante con los dedos medio cerrados (agarre), en el marco de la mano."""
    X = 1 if side == 'L' else -1
    bm = bmesh.new()
    # marco local: x a lo ancho (hacia el pulgar = +x), y a lo largo de la mano, z sale del dorso
    palm = [((0, y, 0), w, t) for y, w, t in ((-0.03, 0.04, 0.03), (0.0, 0.043, 0.026), (0.03, 0.047, 0.022),
                                              (0.06, 0.049, 0.02), (0.085, 0.047, 0.018), (0.095, 0.04, 0.015))]
    rings_ = [ring(cc, (1, 0, 0), (0, 0, 1), w, t, 20, 2.4) for cc, w, t in palm]
    loft(bm, rings_)
    fingers = [(-0.033, 0.072, 0.0085), (-0.011, 0.082, 0.0092), (0.011, 0.079, 0.009), (0.032, 0.066, 0.0082)]
    for off, L, r in fingers:
        pts = [Vector((off, 0.08, 0.0))]
        ang = 0.0
        for j in range(3):
            ang += math.radians(30 + 8 * j)
            pts.append(pts[-1] + Vector((0, math.cos(ang), -math.sin(ang))) * (L / 3))
        pp = resample(pts, 0.004)
        limb(bm, [p for p, _ in pp], [r * (1 - 0.2 * u) for _, u in pp], Vector((1, 0, 0)), n=12)
    tb = [Vector((0.035, 0.005, -0.008)), Vector((0.055, 0.035, -0.02)), Vector((0.06, 0.06, -0.035)), Vector((0.052, 0.08, -0.045))]
    pp = resample(tb, 0.004)
    limb(bm, [p for p, _ in pp], [0.012 * (1 - 0.25 * u) for _, u in pp], Vector((0, 0, 1)), n=12)
    # puño del guante
    limb(bm, [Vector((0, -0.045, 0)), Vector((0, -0.01, 0))], [(0.048, 0.04), (0.046, 0.035)], Vector((1, 0, 0)), n=20)
    me = unify(bm, 'Guante.' + side, c, 0.0032, smooth=4, smooth_f=0.5)
    h0, h1 = J('mano.' + side), J('mano.' + side, 'tail')
    along = (h1 - h0).normalized()
    palm_n = Vector((-X, 0.25, 0)).normalized()          # la palma mira hacia el cuerpo
    palm_n = (palm_n - along * palm_n.dot(along)).normalized()
    thumb = along.cross(palm_n) * (-X)                   # el pulgar hacia delante (-Y)
    if thumb.y > 0:
        thumb = -thumb
    m = Matrix((thumb, along, -palm_n)).transposed()
    if m.determinant() < 0:
        m = Matrix((-thumb, along, -palm_n)).transposed()
        me.data.transform(Matrix.Scale(-1, 4, Vector((1, 0, 0))))
        me.data.flip_normals()
    me.data.transform(m.to_4x4())
    me.location = h0
    return me


def head_mesh(c):
    E = []
    E.append(('ELLIPSOID', (0, 0.008, 1.655), 0.3, None, (0.26, 0.31, 0.33), 2.0))    # cráneo
    E.append(('ELLIPSOID', (0, -0.035, 1.6), 0.3, None, (0.2, 0.2, 0.2), 2.0))       # mandíbula
    E.append(('ELLIPSOID', (0, -0.088, 1.632), 0.3, None, (0.05, 0.06, 0.07), 2.5))   # nariz (bajo la braga)
    E.append(('ELLIPSOID', (0, -0.075, 1.69), 0.3, None, (0.2, 0.06, 0.05), 2.0))    # arco de las cejas
    for X in (1, -1):
        E.append(('ELLIPSOID', (X * 0.045, -0.07, 1.635), 0.3, None, (0.08, 0.06, 0.06), 2.0))   # pómulos
    ob = meta_object('Cabeza meta', c, 0.006, E, thresh=0.6)
    me = to_mesh(ob, 'Cabeza')
    return me


def gaiter_mesh(c, mat):
    """Braga de cuello subida hasta la nariz: un tubo algo holgado sobre la cara y el cuello."""
    E = []
    E += seg_balls((0, 0.012, 1.47), (0, 0.0, 1.6), 0.112, 0.112, 5, stiff=2.0)
    E.append(('ELLIPSOID', (0, -0.045, 1.6), 0.3, None, (0.23, 0.2, 0.16), 2.0))
    E.append(('ELLIPSOID', (0, -0.08, 1.632), 0.3, None, (0.1, 0.075, 0.075), 2.0))
    ob = meta_object('Braga meta', c, 0.008, E)
    me = to_mesh(ob, 'Braga cuello')
    # se corta por arriba (por encima de la nariz queda la cara al aire)
    bm = bmesh.new()
    bm.from_mesh(me.data)
    kill = [v for v in bm.verts if v.co.z > 1.648 + (0.0 if v.co.y < -0.02 else 0.03)]
    bmesh.ops.delete(bm, geom=kill, context='VERTS')
    bm.to_mesh(me.data)
    bm.free()
    sol = me.modifiers.new('grosor', 'SOLIDIFY')
    sol.thickness = 0.006
    me.data.materials.append(mat)
    return me


def hood_mesh(c, mat):
    """Capucha: casquete holgado alrededor de la cabeza, abierto por delante."""
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=96, v_segments=64, radius=1.0)
    for v in bm.verts:
        x, y, z = v.co
        v.co = Vector((x * 0.122, y * 0.138 + 0.022, z * 0.14 + 1.655))
        # la parte de atrás baja hacia la nuca y los hombros
        if y > 0 and z < 0:
            v.co.z -= 0.05 * (-z) * y
    # abertura de la cara: elipse en el frente
    kill = []
    for f in bm.faces:
        cc = f.calc_center_median()
        if cc.y < -0.02:
            ex = cc.x / 0.085
            ez = (cc.z - 1.645) / 0.105
            if ex * ex + ez * ez < 1.0:
                kill.append(f)
        if cc.z < 1.505:
            kill.append(f)
    bmesh.ops.delete(bm, geom=list(set(kill)), context='FACES')
    ob = bm_obj(bm, 'Capucha', c, mat, smooth=True)
    sol = ob.modifiers.new('grosor', 'SOLIDIFY')
    sol.thickness = 0.012
    sol.offset = 1.0
    sub = ob.modifiers.new('suave', 'SUBSURF')
    sub.levels = 1
    sub.render_levels = 2
    # arrugas del tejido
    tex = bpy.data.textures.new('Arrugas capucha', 'CLOUDS')
    tex.noise_scale = 0.05
    d = ob.modifiers.new('arrugas', 'DISPLACE')
    d.texture = tex
    d.strength = 0.006
    d.texture_coords = 'OBJECT'
    return ob


def boot_mesh(c, side, mats):
    X = 1 if side == 'L' else -1
    bm = bmesh.new()
    x0 = X * 0.108
    # pie de la bota: secciones a lo largo de y (talón +y, puntera -y)
    S = [(0.085, 0.036, 0.05, 0.055), (0.07, 0.048, 0.062, 0.07), (0.03, 0.052, 0.07, 0.075), (-0.03, 0.054, 0.062, 0.066),
         (-0.09, 0.055, 0.046, 0.05), (-0.14, 0.05, 0.037, 0.04), (-0.18, 0.04, 0.03, 0.034), (-0.2, 0.022, 0.022, 0.031)]
    rings_ = [ring((x0, y, cz), (1, 0, 0), (0, 0, 1), rx, rz, 24, 3.0) for y, rx, rz, cz in S]
    loft(bm, rings_)
    # caña
    limb(bm, [Vector((x0, 0.03, 0.06)), Vector((x0, 0.028, 0.14)), Vector((x0, 0.025, 0.21))],
         [(0.058, 0.066), (0.06, 0.066), (0.064, 0.07)], Vector((1, 0, 0)), n=24)
    me = unify(bm, 'Bota.' + side, c, 0.005, smooth=4, smooth_f=0.5)
    me.data.materials.append(mats['bota'])
    me.data.materials.append(mats['suela'])
    for p in me.data.polygons:
        p.material_index = 1 if p.center.z < 0.022 else 0
    # suela de goma: una losa algo más ancha
    sole = box('Suela.' + side, c, (0.112, 0.3, 0.024), (x0, -0.055, 0.012), mats['suela'])
    m = sole.modifiers.new('bisel', 'BEVEL')
    m.width = 0.01
    m.segments = 3
    return me, sole


def backpack(c, mats):
    obs = []
    b = box('Mochila', c, (0.3, 0.17, 0.44), (0, 0.205, 1.2), mats['mochila'])
    m = b.modifiers.new('bisel', 'BEVEL')
    m.width = 0.05
    m.segments = 4
    sub = b.modifiers.new('suave', 'SUBSURF')
    sub.levels = 1
    sub.render_levels = 2
    obs.append(b)
    lid = box('Tapa mochila', c, (0.28, 0.16, 0.08), (0, 0.21, 1.43), mats['mochila'], rot=(0.15, 0, 0))
    m = lid.modifiers.new('bisel', 'BEVEL')
    m.width = 0.03
    m.segments = 3
    obs.append(lid)
    for X in (1, -1):
        pk = box('Bolsillo mochila', c, (0.05, 0.12, 0.2), (X * 0.165, 0.2, 1.1), mats['mochila'])
        m = pk.modifiers.new('bisel', 'BEVEL')
        m.width = 0.02
        m.segments = 3
        obs.append(pk)
    # hombreras: tiras planas que pasan por encima del hombro y bajan por el pecho
    from .tunel import sweep
    prof = [(-0.03, 0.0), (0.03, 0.0), (0.03, 0.008), (-0.03, 0.008)]
    for X in (1, -1):
        path = [(X * 0.1, 0.13, 1.4), (X * 0.11, 0.07, 1.47), (X * 0.12, -0.02, 1.47), (X * 0.125, -0.1, 1.38),
                (X * 0.125, -0.12, 1.25), (X * 0.13, -0.1, 1.1), (X * 0.14, 0.1, 1.02)]
        pts = _smooth_path(path, 6)
        obs.append(sweep('Hombrera', prof, pts, c, mats['cinta']))
    # cinturón de pecho
    obs.append(box('Cinta pecho', c, (0.2, 0.012, 0.02), (0, -0.135, 1.27), mats['cinta']))
    return obs


def _smooth_path(pts, k):
    P = [Vector(p) for p in pts]
    P = [P[0] * 2 - P[1]] + P + [P[-1] * 2 - P[-2]]
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for j in range(k):
            t = j / k
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t +
                              (-p0 + 3 * p1 - 3 * p2 + p3) * t * t * t))
    out.append(P[-2])
    return out


def headlamp(c, mats):
    obs = []
    # cinta elástica alrededor de la capucha, a la altura de la frente
    bm = bmesh.new()
    bmesh.ops.create_circle(bm, cap_ends=False, segments=48, radius=1.0)
    ring = bm_obj(bm, 'Cinta frontal', c, mats['cinta'])
    ring.scale = (0.126, 0.146, 1)
    ring.location = (0, 0.016, 1.69)
    ring.rotation_euler = (math.radians(-14), 0, 0)
    sol = ring.modifiers.new('ancho', 'SCREW')
    sol.screw_offset = 0.028
    sol.angle = 0
    sol.steps = 1
    sol.render_steps = 1
    so = ring.modifiers.new('grosor', 'SOLIDIFY')
    so.thickness = 0.004
    obs.append(ring)
    lamp = box('Frontal', c, (0.06, 0.03, 0.038), (0, -0.142, 1.712), mats['plastico'], rot=(math.radians(-8), 0, 0))
    m = lamp.modifiers.new('bisel', 'BEVEL')
    m.width = 0.008
    m.segments = 3
    obs.append(lamp)
    lens = cyl('Frontal cristal', c, 0.013, 0.006, (0, -0.159, 1.71), None, rot=(math.radians(82), 0, 0), seg=24)
    lm, nb = M.new_material('LED frontal')
    if nb:
        oi = nb.n('ShaderNodeObjectInfo')
        em = nb.n('ShaderNodeEmission', {'Color': (0.92, 0.95, 1.0), 'Strength': nb.math('MULTIPLY', nb.out(oi, 'Alpha'), 220.0)})
        M.output(nb, nb.out(em))
    lens.data.materials.append(lm)
    lens.color = (1, 1, 1, 1)
    obs.append(lens)
    # la luz: un foco estrecho y potente y un halo más ancho y débil
    lights = []
    for name, size, blend, energy in (('Frontal haz', 26, 0.45, 30.0), ('Frontal halo', 75, 0.9, 7.0)):
        ld = bpy.data.lights.new(name, 'SPOT')
        ld.spot_size = math.radians(size)
        ld.spot_blend = blend
        ld.energy = energy
        ld.shadow_soft_size = 0.012
        try:
            ld.use_temperature = True
            ld.temperature = 6200
        except AttributeError:
            ld.color = (0.93, 0.96, 1.0)
        lo = bpy.data.objects.new(name, ld)
        c.objects.link(lo)
        lo.location = (0, -0.165, 1.71)
        # los focos miran por su -Z: hacia delante (-Y) y un poco hacia abajo
        lo.rotation_euler = (math.radians(90 - 9), 0, math.pi)
        lights.append(lo)
    R['lamp_lens'] = lens
    R['lamp_lights'] = lights
    return obs, lights


# ------------------------------------------------------------------ esqueleto y pesos
def armature(c):
    ad = bpy.data.armatures.new('Personaje')
    ob = bpy.data.objects.new('Personaje', ad)
    c.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    with bpy.context.temp_override(active_object=ob, object=ob, selected_objects=[ob]):
        bpy.ops.object.mode_set(mode='EDIT')
        for name, h, t, par, deform, _ in BONES:
            eb = ad.edit_bones.new(name)
            eb.head, eb.tail = h, t
            eb.use_deform = deform
            if par:
                eb.parent = ad.edit_bones[par]
                eb.use_connect = (Vector(ad.edit_bones[par].tail) - Vector(h)).length < 1e-4
        # rollo: que el eje X de cada hueso apunte a la derecha del personaje (rodillas y codos doblan bien)
        for eb in ad.edit_bones:
            eb.align_roll(Vector((0, -1, 0)) if not eb.name.startswith(('brazo', 'antebrazo', 'mano', 'clavicula')) else Vector((0, 0, 1)))
        bpy.ops.object.mode_set(mode='OBJECT')
    ob.show_in_front = True
    return ob


def seg_dist(P, a, b):
    """Distancia de los puntos P (n,3) al segmento ab."""
    ab = b - a
    t = np.clip(((P - a) @ ab) / max(1e-9, ab @ ab), 0, 1)
    q = a + t[:, None] * ab
    return np.linalg.norm(P - q, axis=1), t


def skin_weights(me_ob, arm_ob):
    """Pesos tipo envolvente: cada vértice se reparte entre los huesos más cercanos según la
    distancia relativa al grosor del hueso (suave en las articulaciones)."""
    P = np.array([v.co[:] for v in me_ob.data.vertices])
    names, dists = [], []
    for name, h, t, par, deform, rad in BONES:
        if not deform:
            continue
        d, _ = seg_dist(P, np.array(h), np.array(t))
        dn = d / rad
        # los huesos de un lado no influyen en el otro
        if name.endswith('.L'):
            dn = np.where(P[:, 0] < 0.02, 99.0, dn)
        elif name.endswith('.R'):
            dn = np.where(P[:, 0] > -0.02, 99.0, dn)
        names.append(name)
        dists.append(dn)
    D = np.stack(dists, 1)
    W = 1.0 / np.maximum(D, 0.35) ** 6
    # solo los 3 mayores
    idx = np.argsort(-W, axis=1)[:, :3]
    groups = {n: me_ob.vertex_groups.new(name=n) for n in names}
    rows = np.arange(len(P))
    top = W[rows[:, None], idx]
    top = top / top.sum(1, keepdims=True)
    for k in range(3):
        for bi, name in enumerate(names):
            sel = np.where((idx[:, k] == bi) & (top[:, k] > 0.01))[0]
            if len(sel):
                for w in np.unique(np.round(top[sel, k], 3)):
                    ids = sel[np.round(top[sel, k], 3) == w]
                    groups[name].add(ids.tolist(), float(w), 'REPLACE')
    mod = me_ob.modifiers.new('esqueleto', 'ARMATURE')
    mod.object = arm_ob
    mod.use_deform_preserve_volume = True
    me_ob.parent = arm_ob


def bone_parent(ob, arm_ob, bone):
    bpy.context.view_layer.update()
    mw = ob.matrix_world.copy()
    ob.parent = arm_ob
    ob.parent_type = 'BONE'
    ob.parent_bone = bone
    bpy.context.view_layer.update()
    ob.matrix_world = mw


def ik_setup(arm_ob, c):
    """Objetivos de IK (vacíos en el mundo) para pies y manos, polos de rodillas y codos."""
    tg = {}
    pb = arm_ob.pose.bones
    for s, X in (('L', 1), ('R', -1)):
        # pie
        foot = _target('IK pie.' + s, c, arm_ob, 'pie.' + s)
        pole_k = bpy.data.objects.new('Polo rodilla.' + s, None)
        c.objects.link(pole_k)
        pole_k.parent = arm_ob
        pole_k.parent_type = 'BONE'
        pole_k.parent_bone = 'cadera'
        bpy.context.view_layer.update()
        pole_k.matrix_world = arm_ob.matrix_world @ Matrix.Translation((X * 0.12, -0.9, 0.5))
        ik = pb['pierna.' + s].constraints.new('IK')
        ik.target = foot
        ik.pole_target = pole_k
        ik.chain_count = 2
        ik.use_tail = True
        cr = pb['pie.' + s].constraints.new('COPY_ROTATION')
        cr.target = foot
        # mano
        hand = _target('IK mano.' + s, c, arm_ob, 'mano.' + s, tail=False)
        pole_e = bpy.data.objects.new('Polo codo.' + s, None)
        c.objects.link(pole_e)
        pole_e.parent = arm_ob
        pole_e.parent_type = 'BONE'
        pole_e.parent_bone = 'pecho'
        bpy.context.view_layer.update()
        pole_e.matrix_world = arm_ob.matrix_world @ Matrix.Translation((X * 0.55, 0.7, 1.15))
        ik = pb['antebrazo.' + s].constraints.new('IK')
        ik.target = hand
        ik.pole_target = pole_e
        ik.chain_count = 2
        ik.use_tail = True
        crh = pb['mano.' + s].constraints.new('COPY_ROTATION')
        crh.target = hand
        crh.influence = 0.0
        tg['pie.' + s] = foot
        tg['mano.' + s] = hand
        tg['polo_rodilla.' + s] = pole_k
        tg['polo_codo.' + s] = pole_e
    calibrate_poles(arm_ob, tg)
    return tg


def _target(name, c, arm_ob, bone, tail=True):
    """Vacío con la orientación de reposo del hueso, situado en la punta (pie) o en la base (mano)."""
    e = bpy.data.objects.new(name, None)
    c.objects.link(e)
    e.empty_display_size = 0.08
    e.empty_display_type = 'ARROWS'
    b = arm_ob.data.bones[bone]
    m = arm_ob.matrix_world @ b.matrix_local
    # el pie: el objetivo de la IK es el tobillo (cola de la pierna = cabeza del pie)
    e.matrix_world = m
    e.rotation_mode = 'QUATERNION'
    return e


def calibrate_poles(arm_ob, tg):
    """Busca el ángulo de polo con el que la rodilla y el codo quedan en reposo como en el modelo."""
    pb = arm_ob.pose.bones
    for chain, mid in (('pierna', 'pierna'), ('antebrazo', 'antebrazo')):
        for s in ('L', 'R'):
            ik = [c for c in pb[mid + '.' + s].constraints if c.type == 'IK'][0]
            rest = (arm_ob.matrix_world @ arm_ob.data.bones[mid + '.' + s].head_local).copy()
            best = None
            for ang in range(-180, 180, 5):
                ik.pole_angle = math.radians(ang)
                bpy.context.view_layer.update()
                p = arm_ob.matrix_world @ pb[mid + '.' + s].head
                err = (p - rest).length
                if best is None or err < best[0]:
                    best = (err, ang)
            ik.pole_angle = math.radians(best[1])
            print('  polo %s.%s: %d grados (error %.3f m)' % (mid, s, best[1], best[0]))


# ------------------------------------------------------------------ montaje
def build(main, ctx):
    c = coll('Personaje', main)
    mats = materials()
    arm = armature(c)
    body = body_mesh(c)
    body.data.materials.append(mats['chaqueta'])
    body.data.materials.append(mats['pantalon'])
    for p in body.data.polygons:
        cc = p.center
        hem = 0.84 + 0.012 * math.sin(cc.x * 40) + (0.03 if cc.y > 0.05 else 0.0)
        arm_zone = abs(cc.x) > 0.21 and cc.z > 0.8
        p.material_index = 0 if (cc.z > hem or arm_zone) else 1
    skin_weights(body, arm)
    head = head_mesh(c)
    head.data.materials.append(mats['piel'])
    bone_parent(head, arm, 'cabeza')
    eyes = []
    for X in (1, -1):
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=16, radius=0.0118)
        e = bm_obj(bm, 'Ojo', c, mats['ojo'], smooth=True)
        e.location = (X * 0.031, -0.066, 1.667)
        eyes.append(e)
        bone_parent(e, arm, 'cabeza')
    gai = gaiter_mesh(c, mats['braga'])
    bone_parent(gai, arm, 'cabeza')
    hood = hood_mesh(c, mats['chaqueta'])
    bone_parent(hood, arm, 'cabeza')
    for s in ('L', 'R'):
        h = hand_mesh(c, s)
        h.data.materials.append(mats['guante'])
        bone_parent(h, arm, 'mano.' + s)
        bt, sole = boot_mesh(c, s, mats)
        bone_parent(bt, arm, 'pie.' + s)
        bone_parent(sole, arm, 'pie.' + s)
    for o in backpack(c, mats):
        bone_parent(o, arm, 'pecho')
    lamp_obs, lights = headlamp(c, mats)
    for o in lamp_obs + lights:
        bone_parent(o, arm, 'cabeza')
    tg = ik_setup(arm, c)
    R.update({'arm': arm, 'targets': tg, 'body': body})
    return R
