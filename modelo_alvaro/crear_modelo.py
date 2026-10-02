"""Modelo 3D de Alvaro a partir de sus fotos de referencia.

Construye cabeza (medida sobre las fotos de frente y perfil, con la foto
frontal proyectada como textura), pelo con particulas, orejas, brazos y
manos, camiseta blanca, vaqueros y zapatillas, mas un estudio de fotos.

Uso (Blender 4.2+ / 5.0):
  blender -b -P crear_modelo.py -- --tex RUTA/cara.png --modo fotos  --out RUTA/salida
  blender -b -P crear_modelo.py -- --tex RUTA/cara.png --modo turntable --out RUTA/salida --gpu
  blender -b -P crear_modelo.py -- --tex RUTA/cara.png --modo preview --out RUTA/salida
Tambien funciona con el modulo `bpy` de pip: python3 crear_modelo.py -- ...

La textura cara.png sale de preparar_textura_cara.py (no se sube al repo
porque es una foto personal).
"""
import argparse
import math
import os
import sys

import bpy  # noqa: E402  (bpy antes que bmesh con el modulo de pip)
import bmesh
import numpy as np
from mathutils import Vector

# ---------------------------------------------------------------- argumentos
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--tex", required=True)
ap.add_argument("--modo", default="preview", choices=["preview", "fotos", "turntable", "nada"])
ap.add_argument("--out", default="render")
ap.add_argument("--samples", type=int, default=0)
ap.add_argument("--pct", type=int, default=100)
ap.add_argument("--gpu", action="store_true")
ap.add_argument("--vistas", default="")
ap.add_argument("--frames", default="")
ap.add_argument("--blend", default="")
args = ap.parse_args(argv)
os.makedirs(args.out, exist_ok=True)

ALTURA_OJOS = 1.66     # m (altura total supuesta ~1,78 m)
CENTRO_F = -10.5       # cm, eje vertical de la cabeza (a la altura de las orejas)

# ------------------------------------------------------------------ escena
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"


def link(obj, parent=None):
    scene.collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def mesh_obj(name, verts, faces, parent=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.update()
    return link(bpy.data.objects.new(name, me), parent)


def smooth(arr, s):
    k = np.exp(-0.5 * (np.arange(-3 * s, 3 * s + 1) / s) ** 2)
    k /= k.sum()
    pad = np.pad(arr, (3 * s, 3 * s), mode="edge")
    return np.convolve(pad, k, mode="valid")


def sstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


root = link(bpy.data.objects.new("Alvaro", None))

# ================================================================== CABEZA
# Medidas en cm. Origen: entre los ojos. x = izquierda de Alvaro, f = hacia
# delante, z = arriba. Columnas: z, frente (f), nuca (f), ancho total,
# exponente de la forma delantera (mas alto = cara mas plana).
TABLA = np.array([
    # z      Ff      Bb     W     nf
    [12.4,  -8.0,  -11.5,  3.0,  2.0],
    [12.0,  -4.5,  -15.5,  9.0,  2.2],
    [11.0,  -2.2,  -17.8, 11.8,  2.4],
    [9.5,   -0.8,  -19.0, 13.6,  2.6],
    [7.0,    0.3,  -19.8, 14.8,  2.7],
    [5.0,    0.8,  -20.0, 15.0,  2.7],
    [2.5,    0.8,  -19.8, 14.8,  2.7],
    [1.0,    0.3,  -19.4, 14.4,  2.7],
    [0.0,   -0.2,  -19.0, 14.0,  2.6],
    [-2.0,  -0.4,  -18.5, 13.8,  2.5],
    [-4.0,   0.0,  -17.8, 13.4,  2.4],
    [-5.5,   0.6,  -17.0, 12.9,  2.2],
    [-7.5,   0.9,  -16.2, 12.0,  2.0],
    [-9.0,   0.7,  -16.0, 11.2,  1.8],
    [-10.3,  0.4,  -16.0, 10.4,  1.6],
    [-11.2, -0.6,  -16.0, 10.6,  1.5],
    [-11.8, -2.4,  -16.0, 11.0,  1.6],
    [-12.5, -5.0,  -15.8, 10.8,  2.0],
    [-14.0, -5.2,  -15.6, 10.4,  2.0],
    [-17.0, -4.9,  -15.5, 10.6,  2.0],
    [-19.0, -5.3,  -15.2, 10.4,  2.0],
    [-21.0, -6.0,  -14.6, 9.6,   2.0],
])


def g2(x, z, x0, z0, sx, sz):
    return np.exp(-0.5 * (((x - x0) / sx) ** 2 + ((z - z0) / sz) ** 2))


def rasgos(x, z):
    """Desplazamiento hacia delante (cm) de los rasgos de la cara."""
    ax = np.abs(x)
    d = np.zeros_like(x)
    # nariz: puente desde el nasion hasta la punta y vuelta al subnasal
    zt = np.clip(z, -5.2, 0.8)
    prof = np.interp(zt, [-5.2, -4.8, -4.2, -3.7, -2.0, 0.0, 0.8],
                     [0.4, 1.3, 2.6, 3.1, 2.0, 0.75, 0.3])
    anch = np.interp(zt, [-5.2, -4.2, -3.0, 0.0, 0.8], [1.0, 1.25, 0.95, 0.65, 0.7])
    zona = sstep(-5.6, -4.9, z) * (1 - sstep(0.6, 1.4, z))
    d += prof * np.exp(-0.5 * (x / anch) ** 2) * zona
    # aletas nasales
    d += 0.75 * g2(ax, z, 1.55, -4.5, 0.55, 0.55)
    # cuencas de los ojos y globo ocular
    d += -1.0 * g2(ax, z, 3.2, 0.3, 1.6, 1.2)
    d += 0.45 * g2(ax, z, 3.2, 0.0, 0.9, 0.6)
    # arco de las cejas
    d += 0.35 * g2(ax, z, 3.0, 1.8, 2.2, 0.55)
    # pomulos
    d += 0.55 * g2(ax, z, 4.9, -2.0, 1.4, 1.3)
    # surco nasogeniano / mejilla bajo el pomulo
    d += -0.25 * g2(ax, z, 4.6, -5.5, 1.2, 1.5)
    # labios
    d += 0.55 * g2(x, z, 0, -7.0, 1.9, 0.45)
    d += 0.50 * g2(x, z, 0, -8.15, 1.7, 0.5)
    d += -0.30 * g2(x, z, 0, -7.6, 2.4, 0.13)
    d += -0.25 * g2(x, z, 0, -9.0, 1.5, 0.35)      # surco mentolabial
    # menton
    d += 0.45 * g2(x, z, 0, -10.3, 1.7, 0.8)
    return d


def linea_pelo(theta):
    """Altura (cm) del nacimiento del pelo segun el angulo desde la frente."""
    th = [0.0, 0.6, 1.0, 1.25, 1.32, 1.42, 1.48, 1.75, 1.85, 2.3, math.pi]
    hz = [6.4, 5.0, 3.6, 2.0, -1.0, -1.0, 1.8, 1.8, -3.0, -7.5, -8.3]
    return np.interp(theta, th, hz)


def construir_cabeza():
    zs = np.linspace(12.4, -21.0, 400)
    cols = []
    for c in range(1, 5):
        v = np.interp(-zs, -TABLA[:, 0], TABLA[:, c])
        cols.append(smooth(v, 8))
    Ff, Bb, W, NF = cols
    NSEG = 320
    t = np.linspace(0, 2 * np.pi, NSEG, endpoint=False)
    verts, xs_all, zs_all = [], [], []
    for i, z in enumerate(zs):
        ct, st = np.cos(t), np.sin(t)
        front = ct >= 0
        a = np.where(front, Ff[i] - CENTRO_F, CENTRO_F - Bb[i])
        n = np.where(front, NF[i], 2.0)
        x = (W[i] / 2) * np.sign(st) * np.abs(st) ** (2 / n)
        f = CENTRO_F + a * np.sign(ct) * np.abs(ct) ** (2 / n)
        f = f + rasgos(x, np.full_like(x, z)) * np.clip(ct, 0, 1) ** 0.5
        for xi, fi in zip(x, f):
            verts.append((xi, fi, z))
    verts.append((0.0, (Ff[0] + Bb[0]) / 2, 12.6))       # polo superior
    faces = []
    R = len(zs)
    for i in range(R - 1):
        for j in range(NSEG):
            a0 = i * NSEG + j
            a1 = i * NSEG + (j + 1) % NSEG
            faces.append((a0, a1, a1 + NSEG, a0 + NSEG))
    top = len(verts) - 1
    for j in range(NSEG):
        faces.append((top, (j + 1) % NSEG, j))
    V = np.array(verts)
    world = np.column_stack([V[:, 0] * 0.01, -(V[:, 1] + 10.0) * 0.01, ALTURA_OJOS + V[:, 2] * 0.01])
    head = mesh_obj("Cabeza", world, faces, root)
    me = head.data
    # normales coherentes hacia fuera
    bm = bmesh.new(); bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me); bm.free()
    for p in me.polygons:
        p.use_smooth = True

    # UV: proyeccion frontal de la foto (cara.png, 2000x3000)
    uv = me.uv_layers.new(name="Foto")
    for loop in me.loops:
        x, f, z = V[loop.vertex_index]
        px = 1020 + x * 98.4
        py = 1360 - z * 109.0
        uv.data[loop.index].uv = (px / 2000.0, 1 - py / 3000.0)

    # mascara de cara (donde manda la foto) segun orientacion y zona
    me.update()
    nrm = np.array([v.normal[:] for v in me.vertices])
    facing = -nrm[:, 1]
    x, z = V[:, 0], V[:, 2]
    theta = np.arctan2(np.abs(x), V[:, 1] - CENTRO_F)
    hl = linea_pelo(theta)
    m = sstep(0.35, 0.75, facing) * (1 - sstep(5.6, 6.6, np.abs(x)))
    m *= sstep(-13.0, -11.5, z)
    m *= 1 - sstep(hl - 0.6, hl + 0.4, z)
    m = np.clip(m, 0, 1)
    pelo = sstep(hl - 0.2, hl + 0.6, z)
    pelo[V[:, 2] > 12.0] = 1.0
    attr = me.color_attributes.new("mascaras", "FLOAT_COLOR", "POINT")
    for i in range(len(V)):
        attr.data[i].color = (m[i], pelo[i], 0.0, 1.0)

    # grupos de vertices para el pelo: densidad y longitud
    g_den = head.vertex_groups.new(name="pelo")
    g_len = head.vertex_groups.new(name="largo_pelo")
    # largo: arriba largo (flequillo), laterales degradados muy cortos
    largo = 0.12 + 0.88 * sstep(4.5, 9.5, z) * (1 - 0.35 * sstep(1.2, 2.8, theta))
    largo = largo * (0.35 + 0.65 * sstep(-0.5, 0.7, (V[:, 1] - CENTRO_F) / 10.0)) + 0.0
    for i in range(len(V)):
        if pelo[i] > 0.01:
            g_den.add([i], float(pelo[i]), "REPLACE")
            g_len.add([i], float(np.clip(largo[i], 0.05, 1.0)), "REPLACE")
    sub = head.modifiers.new("Subdiv", "SUBSURF")
    sub.levels = 1
    sub.render_levels = 2
    return head


def construir_oreja(lado):
    """Oreja: elipsoide aplanado con concha hundida y borde (helix)."""
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=20, radius=1.0)
    ob = bpy.context.active_object
    ob.name = f"Oreja_{'I' if lado > 0 else 'D'}"
    me = ob.data
    for v in me.vertices:
        x, y, z = v.co
        # forma: alto 6.3, ancho 3.6, grosor 1.1 (cm); lobulo mas estrecho abajo
        w = 1.8 * (1 - 0.25 * max(0.0, -z))
        nx = x * 0.55
        y2 = y * w
        z2 = z * 3.15
        if x > 0:   # cara exterior: concha hundida
            r = math.sqrt((y * 1.0) ** 2 + ((z + 0.1) * 0.9) ** 2)
            nx -= 0.75 * math.exp(-(r / 0.55) ** 2)
        v.co = (nx * 0.01, y2 * 0.01, z2 * 0.01)
    for p in me.polygons:
        p.use_smooth = True
    ob.location = (lado * 0.071, -(CENTRO_F + 10.0) * 0.01, ALTURA_OJOS - 0.017)
    ob.scale = (lado * 1.08, 1.08, 1.08)
    ob.rotation_euler = (0.0, math.radians(-6 * lado), math.radians(-18 * lado))
    ob.parent = root
    ob.modifiers.new("Subdiv", "SUBSURF").levels = 1
    return ob


# ================================================================== CUERPO
def skin_obj(name, verts, edges, radios, raices, parent):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, edges, [])
    ob = link(bpy.data.objects.new(name, me), parent)
    mod = ob.modifiers.new("Skin", "SKIN")
    mod.branch_smoothing = 0.6
    sv = me.skin_vertices[0].data
    for i, r in enumerate(radios):
        sv[i].radius = r if isinstance(r, tuple) else (r, r)
        sv[i].use_root = i in raices
    sub = ob.modifiers.new("Subdiv", "SUBSURF")
    sub.levels = 2
    sub.render_levels = 2
    return ob


def aplicar(ob):
    bpy.context.view_layer.objects.active = ob
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    ob.select_set(True)
    for m in list(ob.modifiers):
        bpy.ops.object.modifier_apply(modifier=m.name)


def borrar_caras(ob, cond):
    bm = bmesh.new(); bm.from_mesh(ob.data)
    bm.normal_update()
    quitar = [f for f in bm.faces if cond(f.calc_center_median(), f.normal)]
    bmesh.ops.delete(bm, geom=quitar, context="FACES")
    bm.to_mesh(ob.data); bm.free()


def construir_brazos():
    V, E, R, roots = [], [], [], []

    def add(p, r, prev=None):
        V.append(p); R.append(r)
        i = len(V) - 1
        if prev is not None:
            E.append((prev, i))
        return i

    for s in (1, -1):
        sh = add((s * 0.170, 0.004, 1.452), 0.054)
        roots.append(sh)
        a = add((s * 0.199, 0.008, 1.29), 0.050, sh)
        el = add((s * 0.218, 0.022, 1.125), 0.040, a)
        fa = add((s * 0.229, 0.006, 1.00), (0.043, 0.040), el)
        wr = add((s * 0.240, -0.018, 0.872), (0.031, 0.024), fa)
        # palma: dos filas hasta los nudillos
        ys = [-0.050, -0.028, -0.006, 0.014]
        mids = [add((s * 0.246, y * 0.8 - 0.004, 0.828), 0.015, wr) for y in ys[::2]]
        knu = []
        for k, y in enumerate(ys):
            knu.append(add((s * 0.249, y, 0.786), 0.0105, mids[min(k // 2, 1)]))
        largos = [(0.040, 0.024, 0.019), (0.044, 0.027, 0.020), (0.041, 0.025, 0.019), (0.032, 0.020, 0.017)]
        for k, kn in enumerate(knu):
            prev = kn
            p = Vector(V[kn])
            ang = 0.25
            for seg, L in enumerate(largos[k]):
                ang += 0.35
                p = p + Vector((-s * 0.004, -math.sin(ang) * L, -math.cos(ang) * L))
                prev = add(tuple(p), 0.0092 - seg * 0.0012, prev)
        # pulgar
        t0 = add((s * 0.236, -0.040, 0.848), 0.0125, wr)
        t1 = add((s * 0.232, -0.062, 0.818), 0.0105, t0)
        t2 = add((s * 0.229, -0.072, 0.792), 0.0092, t1)
        add((s * 0.227, -0.076, 0.772), 0.0082, t2)
    ob = skin_obj("Brazos", V, E, R, roots, root)
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def construir_camiseta():
    V = [(0, 0.006, 0.855), (0, 0.0, 1.02), (0, -0.006, 1.25), (0, 0.0, 1.41), (0, 0.008, 1.505)]
    R = [(0.178, 0.122), (0.162, 0.115), (0.178, 0.128), (0.150, 0.118), (0.055, 0.082)]
    E = [(0, 1), (1, 2), (2, 3), (3, 4)]
    for s in (1, -1):
        V.append((s * 0.168, 0.004, 1.455)); R.append(0.056); E.append((3, len(V) - 1))
        V.append((s * 0.214, 0.009, 1.31)); R.append(0.059); E.append((len(V) - 2, len(V) - 1))
    ob = skin_obj("Camiseta", V, E, R, [0], root)
    aplicar(ob)
    mangas = []
    for s in (1, -1):
        a, b = Vector((s * 0.168, 0.004, 1.455)), Vector((s * 0.214, 0.009, 1.31))
        mangas.append((b, (b - a).normalized()))

    def cond(c, n):
        if c.z < 0.872 and n.z < -0.5:
            return True
        if c.z > 1.49 and n.z > 0.5 and math.hypot(c.x, c.y) < 0.074:
            return True
        for b, d in mangas:
            if (c - b).dot(d) > -0.02 and n.dot(d) > 0.3 and (c - b).length < 0.075:
                return True
        return False
    borrar_caras(ob, cond)
    tex = bpy.data.textures.new("arrugas", "CLOUDS")
    tex.noise_scale = 0.09
    dm = ob.modifiers.new("Arrugas", "DISPLACE")
    dm.texture = tex; dm.strength = 0.007; dm.mid_level = 0.5
    sol = ob.modifiers.new("Grosor", "SOLIDIFY")
    sol.thickness = 0.003
    sol.offset = 1
    sm = ob.modifiers.new("Suave", "SUBSURF"); sm.levels = 1; sm.render_levels = 1
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob, None


def construir_vaqueros():
    V = [(0, 0.005, 0.975), (0, 0.01, 0.865)]
    R = [(0.163, 0.11), (0.168, 0.114)]
    E = [(0, 1)]
    for s in (1, -1):
        pts = [((s * 0.088, 0.012, 0.815), 0.086), ((s * 0.095, 0.002, 0.66), 0.076),
               ((s * 0.100, -0.004, 0.49), 0.059), ((s * 0.101, 0.008, 0.31), 0.057),
               ((s * 0.103, 0.002, 0.075), 0.054)]
        prev = 1
        for p, r in pts:
            V.append(p); R.append(r); E.append((prev, len(V) - 1)); prev = len(V) - 1
    ob = skin_obj("Vaqueros", V, E, R, [0], root)
    aplicar(ob)
    borrar_caras(ob, lambda c, n: c.z < 0.09 and n.z < -0.4)
    tex = bpy.data.textures.new("arrugas_vaq", "CLOUDS")
    tex.noise_scale = 0.06
    dm = ob.modifiers.new("Arrugas", "DISPLACE")
    dm.texture = tex; dm.strength = 0.006
    sol = ob.modifiers.new("Grosor", "SOLIDIFY"); sol.thickness = 0.003; sol.offset = 1
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def construir_zapatos():
    objs = []
    for s in (1, -1):
        x = s * 0.104
        V = [(x, 0.060, 0.060), (x, -0.03, 0.058), (x, -0.12, 0.044), (x, -0.185, 0.036)]
        R = [(0.044, 0.048), (0.048, 0.046), (0.050, 0.034), (0.043, 0.027)]
        E = [(0, 1), (1, 2), (2, 3)]
        up = skin_obj(f"Zapato_{s}", V, E, R, [0], root)
        aplicar(up)
        for v in up.data.vertices:
            if v.co.z < 0.024:
                v.co.z = 0.024
        for p in up.data.polygons:
            p.use_smooth = True
        objs.append(up)
        # suela
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x, -0.064, 0.011))
        so = bpy.context.active_object
        so.name = f"Suela_{s}"
        so.scale = (0.082, 0.262, 0.022)
        so.parent = root
        bv = so.modifiers.new("Bisel", "BEVEL"); bv.width = 0.008; bv.segments = 4
        so.modifiers.new("Subdiv", "SUBSURF").levels = 1
        for p in so.data.polygons:
            p.use_smooth = True
        objs.append(so)
    return objs


# ============================================================== MATERIALES
def nodos(mat):
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    return nt, out


def principled(nt, **kw):
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    for k, v in kw.items():
        b.inputs[k].default_value = v
    return b


def mat_piel_cara(tex_path):
    mat = bpy.data.materials.new("Piel_cara")
    nt, out = nodos(mat)
    b = principled(nt, **{"Roughness": 0.6, "Subsurface Weight": 0.08,
                          "Subsurface Scale": 0.003, "Specular IOR Level": 0.3})
    b.inputs["Subsurface Radius"].default_value = (1.0, 0.35, 0.2)
    img = nt.nodes.new("ShaderNodeTexImage")
    img.image = bpy.data.images.load(tex_path)
    img.extension = "EXTEND"
    uv = nt.nodes.new("ShaderNodeUVMap"); uv.uv_map = "Foto"
    nt.links.new(uv.outputs["UV"], img.inputs["Vector"])
    # tono de piel base (del moreno de la foto) con variacion
    base = nt.nodes.new("ShaderNodeRGB"); base.outputs[0].default_value = (0.30, 0.15, 0.088, 1)
    # leve calidez para compensar la luz fria de la foto
    hsv = nt.nodes.new("ShaderNodeHueSaturation")
    hsv.inputs["Saturation"].default_value = 0.82
    hsv.inputs["Value"].default_value = 1.0
    nt.links.new(img.outputs["Color"], hsv.inputs["Color"])
    attr = nt.nodes.new("ShaderNodeAttribute"); attr.attribute_name = "mascaras"
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(attr.outputs["Color"], sep.inputs["Color"])
    mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"
    nt.links.new(sep.outputs["Red"], mix.inputs[0])
    nt.links.new(base.outputs[0], mix.inputs[6])
    nt.links.new(hsv.outputs["Color"], mix.inputs[7])
    # cuero cabelludo oscuro bajo el pelo
    scalp = nt.nodes.new("ShaderNodeMix"); scalp.data_type = "RGBA"
    scalp.inputs[7].default_value = (0.025, 0.02, 0.017, 1)
    nt.links.new(sep.outputs["Green"], scalp.inputs[0])
    nt.links.new(mix.outputs[2], scalp.inputs[6])
    nt.links.new(scalp.outputs[2], b.inputs["Base Color"])
    # microrelieve de poros
    nz = nt.nodes.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 900
    bump = nt.nodes.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = 0.08
    bump.inputs["Distance"].default_value = 0.0005
    nt.links.new(nz.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    nt.links.new(b.outputs[0], out.inputs["Surface"])
    return mat


def mat_piel_cuerpo():
    mat = bpy.data.materials.new("Piel_cuerpo")
    nt, out = nodos(mat)
    b = principled(nt, **{"Roughness": 0.58, "Subsurface Weight": 0.1,
                          "Subsurface Scale": 0.003, "Specular IOR Level": 0.3})
    b.inputs["Subsurface Radius"].default_value = (1.0, 0.35, 0.2)
    nz = nt.nodes.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 60
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.30, 0.16, 0.095, 1)
    ramp.color_ramp.elements[1].color = (0.37, 0.205, 0.125, 1)
    nt.links.new(nz.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    nz2 = nt.nodes.new("ShaderNodeTexNoise"); nz2.inputs["Scale"].default_value = 700
    bump = nt.nodes.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = 0.06
    nt.links.new(nz2.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    nt.links.new(b.outputs[0], out.inputs["Surface"])
    return mat


def mat_tela(nombre, color, rough, escala, sheen=0.4, fuerza=0.15, sarga=False):
    mat = bpy.data.materials.new(nombre)
    nt, out = nodos(mat)
    b = principled(nt, **{"Roughness": rough, "Sheen Weight": sheen, "Specular IOR Level": 0.3})
    tc = nt.nodes.new("ShaderNodeTexCoord")
    if sarga:
        wave = nt.nodes.new("ShaderNodeTexWave")
        wave.wave_type = "BANDS"; wave.bands_direction = "DIAGONAL"
        wave.inputs["Scale"].default_value = escala
        wave.inputs["Distortion"].default_value = 2.0
        nt.links.new(tc.outputs["Object"], wave.inputs["Vector"])
        hfac = wave.outputs["Fac"]
        nz = nt.nodes.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 8
        nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = tuple(c * 0.6 for c in color) + (1,)
        ramp.color_ramp.elements[1].color = tuple(min(1, c * 1.5) for c in color) + (1,)
        nt.links.new(nz.outputs["Fac"], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    else:
        nz = nt.nodes.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = escala
        nz.inputs["Detail"].default_value = 4
        nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
        hfac = nz.outputs["Fac"]
        b.inputs["Base Color"].default_value = tuple(color) + (1,)
    bump = nt.nodes.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = fuerza
    nt.links.new(hfac, bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    nt.links.new(b.outputs[0], out.inputs["Surface"])
    return mat


def mat_simple(nombre, color, rough, coat=0.0):
    mat = bpy.data.materials.new(nombre)
    nt, out = nodos(mat)
    b = principled(nt, **{"Base Color": tuple(color) + (1,), "Roughness": rough, "Coat Weight": coat})
    nt.links.new(b.outputs[0], out.inputs["Surface"])
    return mat


def mat_pelo():
    mat = bpy.data.materials.new("Pelo")
    nt, out = nodos(mat)
    h = nt.nodes.new("ShaderNodeBsdfHairPrincipled")
    h.parametrization = "MELANIN"
    h.inputs["Melanin"].default_value = 0.97
    h.inputs["Melanin Redness"].default_value = 0.12
    h.inputs["Roughness"].default_value = 0.4
    h.inputs["Radial Roughness"].default_value = 0.4
    h.inputs["Random Roughness"].default_value = 0.2
    nt.links.new(h.outputs[0], out.inputs["Surface"])
    return mat


def poner(ob, mat):
    ob.data.materials.clear()
    ob.data.materials.append(mat)


def pelo_curvas(head, mat, n=140000, npts=6, seed=7):
    """Pelo como curvas generadas a mano: raices repartidas por el cuero
    cabelludo, largo segun el grupo 'largo_pelo' y peinado hacia delante y
    arriba en la parte superior y hacia abajo y atras en los laterales (degradado)."""
    rng = np.random.default_rng(seed)
    me = head.data
    V = np.array([v.co[:] for v in me.vertices])
    den = np.zeros(len(V)); lar = np.zeros(len(V))
    gd, gl = head.vertex_groups["pelo"].index, head.vertex_groups["largo_pelo"].index
    for v in me.vertices:
        for g in v.groups:
            if g.group == gd:
                den[v.index] = g.weight
            elif g.group == gl:
                lar[v.index] = g.weight
    me.calc_loop_triangles()
    tris = np.array([t.vertices[:] for t in me.loop_triangles])
    A, B, C = V[tris[:, 0]], V[tris[:, 1]], V[tris[:, 2]]
    cr = np.cross(B - A, C - A)
    area = 0.5 * np.linalg.norm(cr, axis=1)
    w = area * den[tris].mean(1)
    idx = rng.choice(len(tris), n, p=w / w.sum())
    s_ = np.sqrt(rng.random(n)); r2 = rng.random(n)
    bc = np.column_stack([1 - s_, s_ * (1 - r2), s_ * r2])
    P = (A[idx] * bc[:, :1] + B[idx] * bc[:, 1:2] + C[idx] * bc[:, 2:])
    N = cr[idx] / np.linalg.norm(cr[idx], axis=1)[:, None]
    centro = np.array([0.0, -(CENTRO_F + 10.0) * 0.01, ALTURA_OJOS + 0.03])
    flip = np.einsum("ij,ij->i", N, P - centro) < 0
    N[flip] *= -1
    L = 0.030 * np.clip((lar[tris[idx]] * bc).sum(1), 0.06, 1.0) * rng.uniform(0.8, 1.15, n)
    zl = (P[:, 2] - ALTURA_OJOS) * 100
    top = sstep(4.0, 11.5, zl)[:, None]
    comb = top * np.array([0.0, -1.0, 0.7]) + (1 - top) * np.array([0.0, 0.45, -1.0])
    T = comb - np.einsum("ij,ij->i", comb, N)[:, None] * N
    T /= np.maximum(np.linalg.norm(T, axis=1), 1e-6)[:, None]
    lift = 0.18 + 0.17 * top
    D = N * lift + T * (1 - lift) + rng.normal(0, 0.22, (n, 3))
    D /= np.linalg.norm(D, axis=1)[:, None]
    pts = np.zeros((n, npts, 3))
    for k in range(npts):
        t = k / (npts - 1)
        pts[:, k] = (P + D * (L * t)[:, None] + T * (L * 0.35 * t * t)[:, None]
                     - N * (L * 0.25 * t * t)[:, None] * (1 - top))
    pts[:, 0] -= N * 0.0015          # raiz ligeramente dentro del cuero cabelludo
    cv = bpy.data.hair_curves.new("Pelo")
    cv.add_curves([npts] * n)
    cv.position_data.foreach_set("vector", pts.astype(np.float32).ravel())
    rad = cv.attributes.get("radius") or cv.attributes.new("radius", "FLOAT", "POINT")
    rr = np.tile(np.linspace(0.00005, 0.000015, npts), n).astype(np.float32)
    rad.data.foreach_set("value", rr)
    cv.materials.append(mat)
    return link(bpy.data.objects.new("Pelo", cv), root)


# ================================================================ ESTUDIO
def estudio():
    world = bpy.data.worlds.new("Estudio")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.32, 0.33, 0.35, 1)
    bg.inputs["Strength"].default_value = 0.22
    # ciclorama: suelo curvado hacia una pared
    verts, faces = [], []
    ys = [-8.0, 0.0] + [3.0 + 1.2 * math.sin(i / 29 * math.pi / 2) for i in range(30)] + [4.2]
    zs = [0.0, 0.0] + [1.2 - 1.2 * math.cos(i / 29 * math.pi / 2) for i in range(30)] + [6.0]
    for j, (y, z) in enumerate(zip(ys, zs)):
        verts += [(-8.0, y, z), (8.0, y, z)]
        if j:
            k = 2 * j
            faces.append((k - 2, k - 1, k + 1, k))
    cyc = mesh_obj("Ciclorama", verts, faces)
    for p in cyc.data.polygons:
        p.use_smooth = True
    m = mat_simple("Fondo", (0.30, 0.31, 0.33), 0.8)
    poner(cyc, m)

    def area(nombre, loc, energia, tam, color=(1, 1, 1)):
        ld = bpy.data.lights.new(nombre, "AREA")
        ld.energy = energia; ld.size = tam; ld.color = color
        ob = link(bpy.data.objects.new(nombre, ld))
        ob.location = loc
        d = Vector((0, 0, 1.25)) - Vector(loc)
        ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        return ob
    area("Principal", (-2.2, -2.6, 2.6), 520, 1.8, (1.0, 0.96, 0.9))
    area("Relleno", (2.6, -2.2, 1.6), 140, 2.5, (0.9, 0.95, 1.0))
    area("Contra", (1.2, 2.6, 2.8), 220, 1.2)
    area("Contra2", (-1.5, 2.4, 2.2), 110, 1.0)


def camara(nombre, foco, dist, objetivo, altura):
    cd = bpy.data.cameras.new(nombre)
    cd.lens = foco
    cd.sensor_width = 36
    ob = link(bpy.data.objects.new(nombre, cd))
    ob.location = (0, -dist, altura)
    d = Vector(objetivo) - ob.location
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return ob


# ================================================================ MONTAJE
tex_path = os.path.abspath(args.tex)
head = construir_cabeza()
orejas = [construir_oreja(1), construir_oreja(-1)]
brazos = construir_brazos()
camiseta, cuello = construir_camiseta()
vaqueros = construir_vaqueros()
zapatos = construir_zapatos()

m_cara = mat_piel_cara(tex_path)
m_cuerpo = mat_piel_cuerpo()
poner(head, m_cara)
for o in orejas:
    poner(o, m_cuerpo)
poner(brazos, m_cuerpo)
m_cami = mat_tela("Camiseta_blanca", (0.80, 0.80, 0.78), 0.85, 900, sheen=0.6, fuerza=0.1)
poner(camiseta, m_cami)
poner(vaqueros, mat_tela("Vaquero", (0.018, 0.028, 0.065), 0.75, 300, sheen=0.1, fuerza=0.12, sarga=True))
m_cuero = mat_simple("Cuero_negro", (0.015, 0.015, 0.017), 0.35, coat=0.3)
m_suela = mat_simple("Suela", (0.05, 0.045, 0.04), 0.7)
for z in zapatos:
    poner(z, m_suela if z.name.startswith("Suela") else m_cuero)
pelo_curvas(head, mat_pelo())

estudio()
cam_cuerpo = camara("Cam_cuerpo", 50, 5.2, (0, 0, 0.92), 1.0)
cam_cara = camara("Cam_cara", 85, 1.55, (0, 0, ALTURA_OJOS - 0.02), ALTURA_OJOS + 0.02)

# ------------------------------------------------------------------ render
scene.render.engine = "CYCLES"
cy = scene.cycles
if args.gpu:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for tipo in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            prefs.compute_device_type = tipo
            prefs.get_devices()
            if any(d.type == tipo for d in prefs.devices):
                for d in prefs.devices:
                    d.use = True
                cy.device = "GPU"
                print("GPU:", tipo)
                break
        except TypeError:
            continue
cy.use_denoising = True
cy.max_bounces = 8
scene.render.resolution_x = 1920
scene.render.resolution_y = 1080
scene.render.resolution_percentage = args.pct
scene.render.image_settings.file_format = "PNG"
try:
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = -0.6
except TypeError:
    pass

VISTAS = {
    "frente": (cam_cuerpo, 0), "tres_cuartos": (cam_cuerpo, -35), "perfil": (cam_cuerpo, -90),
    "espalda": (cam_cuerpo, 180), "cara": (cam_cara, 0), "cara_3q": (cam_cara, -35),
    "cara_perfil": (cam_cara, -90),
}

if args.blend:
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.blend))

if args.modo in ("preview", "fotos"):
    cy.samples = args.samples or (24 if args.modo == "preview" else 160)
    vistas = args.vistas.split(",") if args.vistas else list(VISTAS)
    for nombre in vistas:
        cam, ang = VISTAS[nombre]
        scene.camera = cam
        root.rotation_euler = (0, 0, math.radians(ang))
        scene.render.filepath = os.path.join(os.path.abspath(args.out), f"{nombre}.png")
        bpy.ops.render.render(write_still=True)
        print("render", nombre)
elif args.modo == "turntable":
    cy.samples = args.samples or 64
    scene.camera = cam_cuerpo
    scene.frame_start, scene.frame_end = 1, 144
    scene.render.fps = 24
    bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
    root.rotation_euler = (0, 0, 0)
    root.keyframe_insert("rotation_euler", index=2, frame=1)
    root.rotation_euler = (0, 0, math.radians(360))
    root.keyframe_insert("rotation_euler", index=2, frame=145)
    if args.frames:
        a, b = args.frames.split("-")
        scene.frame_start, scene.frame_end = int(a), int(b)
    scene.render.filepath = os.path.join(os.path.abspath(args.out), "turntable_")
    bpy.ops.render.render(animation=True)
