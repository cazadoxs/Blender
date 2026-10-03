"""Locomotora de vapor abandonada (tipo 030 de RENFE) con su ténder.
Mira hacia la boca del túnel (+Y). Todo se construye con primitivas y modificadores."""
import bpy, bmesh, math
import numpy as np
from mathutils import Vector, Matrix
from . import cfg
from .util import coll, box, cyl, bm_obj, bevel, rng, join, mesh_obj
from . import materiales as M

F = cfg.LOCO_FRONT
RT = cfg.RAIL_TOP
PARTS_TOP = []      # superficies donde crecerá vegetación (para vegetacion.py)


def Y(d):
    """Distancia desde los topes delanteros -> coordenada Y."""
    return F - d


def wheel(c, name, r, x, d, mats, spokes=14, crank_deg=0.0, crank=True):
    """Rueda de radios con bandaje, pestaña, cubo y contrapeso. Eje según X."""
    rust, paint = mats
    side = 1 if x > 0 else -1
    z = RT + r
    parts = []
    rot = (0, math.pi / 2, 0)
    w = 0.14
    tire = cyl(name + ' bandaje', c, r, w, (x, Y(d), z), rust, rot=rot, seg=64)
    # hueco interior del bandaje
    inner = cyl('tmp', c, r - 0.075, w * 2, (x, Y(d), z), None, rot=rot, seg=64)
    m = tire.modifiers.new('hueco', 'BOOLEAN')
    m.object = inner
    m.operation = 'DIFFERENCE'
    from .util import apply_mods
    apply_mods(tire)
    bpy.data.objects.remove(inner)
    parts.append(tire)
    fl = cyl(name + ' pestana', c, r + 0.03, 0.03, (x - side * (w / 2 - 0.015), Y(d), z), rust, rot=rot, seg=64)
    inner = cyl('tmp', c, r - 0.02, 0.2, (x - side * (w / 2 - 0.015), Y(d), z), None, rot=rot, seg=64)
    m = fl.modifiers.new('hueco', 'BOOLEAN')
    m.object = inner
    m.operation = 'DIFFERENCE'
    apply_mods(fl)
    bpy.data.objects.remove(inner)
    parts.append(fl)
    hub = cyl(name + ' cubo', c, r * 0.22, w * 1.1, (x, Y(d), z), rust, rot=rot, seg=32)
    parts.append(hub)
    cap = cyl(name + ' tapa', c, r * 0.12, w * 1.5, (x + side * 0.02, Y(d), z), rust, rot=rot, seg=24)
    parts.append(cap)
    for k in range(spokes):
        a = 2 * math.pi * k / spokes
        L = r - 0.075 - r * 0.2
        mid = r * 0.2 + L / 2
        b = box(name + ' radio', c, (0.05, 0.055, L + 0.04),
                (x, Y(d) + math.sin(a) * mid, z + math.cos(a) * mid), rust, rot=(-a, 0, 0))
        parts.append(b)
    # contrapeso (sector opuesto a la manivela)
    if crank:
        bm = bmesh.new()
        ca = math.radians(crank_deg) + math.pi
        seg = 16
        ring = []
        for i in range(seg + 1):
            a = ca - 0.75 + 1.5 * i / seg
            for rr in (r * 0.45, r - 0.07):
                ring.append((math.sin(a) * rr, math.cos(a) * rr))
        vs0 = [bm.verts.new((x - 0.035, Y(d) + p[0], z + p[1])) for p in ring]
        vs1 = [bm.verts.new((x + 0.035, Y(d) + p[0], z + p[1])) for p in ring]
        for i in range(seg):
            a0, a1, b0, b1 = 2 * i, 2 * i + 1, 2 * i + 2, 2 * i + 3
            bm.faces.new((vs0[a0], vs0[b0], vs0[b1], vs0[a1]))
            bm.faces.new((vs1[a0], vs1[a1], vs1[b1], vs1[b0]))
            bm.faces.new((vs0[a0], vs1[a0], vs1[b0], vs0[b0]))
            bm.faces.new((vs0[a1], vs0[b1], vs1[b1], vs1[a1]))
        bm.faces.new((vs0[0], vs0[1], vs1[1], vs1[0]))
        n = 2 * seg
        bm.faces.new((vs0[n], vs1[n], vs1[n + 1], vs0[n + 1]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        parts.append(bm_obj(bm, name + ' contrapeso', c, rust))
        # muñequilla de la manivela
        a = math.radians(crank_deg)
        pin = cyl(name + ' muñequilla', c, 0.065, 0.24, (x + side * 0.09, Y(d) + math.sin(a) * r * 0.42,
                                                         z + math.cos(a) * r * 0.42), rust, rot=rot, seg=20)
        parts.append(pin)
    ob = join(parts, name)
    bevel(ob, 0.006, 1, 35)
    return ob, (x + side * 0.16, Y(d) + math.sin(math.radians(crank_deg)) * r * 0.42,
                z + math.cos(math.radians(crank_deg)) * r * 0.42)


def rod(c, name, p0, p1, h, w, mat):
    p0, p1 = Vector(p0), Vector(p1)
    mid = (p0 + p1) / 2
    d = p1 - p0
    b = box(name, c, (w, d.length + h * 0.6, h), mid, mat)
    b.rotation_euler = (math.atan2(d.z, d.y), 0, 0)
    bevel(b, 0.008, 2)
    return b


def plate_text(c, text, loc, mat, size=0.16, rot=(math.pi / 2, 0, math.pi)):
    cu = bpy.data.curves.new('placa', 'FONT')
    cu.body = text
    cu.size = size
    cu.extrude = 0.01
    cu.align_x = 'CENTER'
    cu.align_y = 'CENTER'
    cu.bevel_depth = 0.003
    ob = bpy.data.objects.new('Numero placa', cu)
    c.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = rot
    ob.data.materials.append(mat)
    return ob


def build(main, ctx):
    c = coll('Locomotora', main)
    paint = M.mat_metal_loco()
    rust = M.mat_oxido('Oxido loco', 1.2, moss=0.25)
    soot = M.mat_negro_hollin()
    brass = M.mat_laton()
    glass = M.mat_vidrio_sucio()
    wood = ctx.get('tunel', {}).get('wood') or M.mat_generic('Madera traviesas', 'madera', 0.8, moss=0.5)
    red = M.mat_metal_loco('Topera roja', paint=(0.16, 0.025, 0.015))
    obs = []

    # --- bastidor
    for s in (-1, 1):
        obs.append(box('Larguero', c, (0.05, 10.0, 0.85), (s * 0.62, Y(5.6), 1.32), rust, bevel=0.01))
    bb = box('Topera', c, (2.7, 0.26, 0.5), (0, Y(0.38), 1.25), red, bevel=0.015)
    obs.append(bb)
    for s in (-1, 1):
        obs.append(cyl('Tope caja', c, 0.11, 0.38, (s * 0.87, Y(0.05), 1.22), rust, rot=(math.pi / 2, 0, 0), seg=24))
        obs.append(cyl('Tope vastago', c, 0.06, 0.3, (s * 0.87, Y(-0.25), 1.22), rust, rot=(math.pi / 2, 0, 0), seg=16))
        obs.append(cyl('Tope plato', c, 0.2, 0.05, (s * 0.87, Y(-0.4), 1.22), rust, rot=(math.pi / 2, 0, 0), seg=40))
    # gancho y cadena
    obs.append(box('Gancho', c, (0.08, 0.35, 0.12), (0, Y(0.05), 1.2), rust, bevel=0.01))

    # --- cilindros
    for s in (-1, 1):
        cy_ = cyl('Cilindro', c, 0.32, 1.05, (s * 1.08, Y(2.1), 1.35), paint, rot=(math.pi / 2, 0, 0), seg=40)
        bevel(cy_, 0.01, 2)
        obs.append(cy_)
        for dd in (1.55, 2.65):
            obs.append(cyl('Tapa cilindro', c, 0.345, 0.06, (s * 1.08, Y(dd), 1.35), rust, rot=(math.pi / 2, 0, 0), seg=40))
        # vástago y guías
        obs.append(cyl('Vastago', c, 0.035, 1.3, (s * 1.08, Y(3.25), 1.35), rust, rot=(math.pi / 2, 0, 0), seg=12))
        for dz in (0.11, -0.11):
            obs.append(box('Guia', c, (0.06, 1.4, 0.05), (s * 1.08, Y(3.4), 1.35 + dz), rust))
        obs.append(box('Cruceta', c, (0.16, 0.22, 0.2), (s * 1.08, Y(3.85), 1.35), rust, bevel=0.01))

    # --- ruedas motrices y de bogie
    crank = {(-1): 35.0, 1: 125.0}
    pins = {}
    for s in (-1, 1):
        x = s * 0.79
        pins[s] = []
        for k, d in enumerate((5.0, 6.75, 8.5)):
            w, pin = wheel(c, 'Rueda motriz', 0.74, x, d, (rust, paint), crank_deg=crank[s])
            obs.append(w)
            pins[s].append(pin)
        w, _ = wheel(c, 'Rueda bogie', 0.43, x, 2.2, (rust, paint), spokes=10, crank=False)
        obs.append(w)
        # bielas de acoplamiento (unen las tres muñequillas)
        p = pins[s]
        obs.append(rod(c, 'Biela acoplamiento', p[0], p[2], 0.11, 0.05, rust))
        # biela motriz: de la cruceta a la muñequilla central
        cross = (s * 1.0, Y(3.85), 1.35)
        pm = Vector(p[1]) + Vector((s * 0.06, 0, 0))
        obs.append(rod(c, 'Biela motriz', cross, pm, 0.13, 0.055, rust))
    # ejes
    for d in (2.2, 5.0, 6.75, 8.5):
        obs.append(cyl('Eje', c, 0.08, 1.75, (0, Y(d), RT + (0.43 if d < 3 else 0.74)), rust, rot=(0, math.pi / 2, 0), seg=16))

    # --- plataformas y caldera
    for s in (-1, 1):
        pl = box('Estribo', c, (0.55, 9.2, 0.04), (s * 1.2, Y(5.0), 1.86), paint, bevel=0.008)
        obs.append(pl)
        PARTS_TOP.append(pl)
        obs.append(box('Faldon', c, (0.03, 9.2, 0.14), (s * 1.47, Y(5.0), 1.8), paint))
        # areneros y tuberías a lo largo de la caldera
        obs.append(cyl('Tuberia', c, 0.03, 6.5, (s * 0.88, Y(5.4), 2.35), rust, rot=(math.pi / 2, 0, 0), seg=12))
        # cajas de grasa y escalones
        obs.append(box('Escalon', c, (0.35, 0.3, 0.03), (s * 1.3, Y(9.6), 0.95), rust))
        obs.append(box('Escalon soporte', c, (0.03, 0.3, 0.85), (s * 1.45, Y(9.6), 1.35), rust))
    zc = 2.65
    smk = cyl('Caja de humos', c, 0.88, 1.6, (0, Y(1.85), zc), soot, rot=(math.pi / 2, 0, 0), seg=64)
    bevel(smk, 0.01, 2)
    obs.append(smk)
    obs.append(cyl('Puerta caja humos', c, 0.8, 0.08, (0, Y(1.02), zc), soot, rot=(math.pi / 2, 0, 0), seg=64))
    obs.append(cyl('Cierre puerta', c, 0.07, 0.12, (0, Y(0.96), zc), rust, rot=(math.pi / 2, 0, 0), seg=16))
    # remaches, bisagras y manetas de la puerta de la caja de humos
    for k in range(36):
        a = 2 * math.pi * k / 36
        obs.append(cyl('Remache puerta', c, 0.017, 0.03, (0.72 * math.cos(a), Y(0.975), zc + 0.72 * math.sin(a)),
                       rust, rot=(math.pi / 2, 0, 0), seg=8))
    for dz in (0.42, -0.42):
        obs.append(box('Bisagra puerta', c, (0.95, 0.025, 0.08), (0.42, Y(0.965), zc + dz), rust, bevel=0.008))
        obs.append(cyl('Pernio', c, 0.04, 0.14, (0.86, Y(0.965), zc + dz), rust, seg=16))
    for ang in (0.35, 0.35 + math.pi / 2):
        obs.append(box('Maneta puerta', c, (0.42, 0.03, 0.035), (0, Y(0.9), zc), rust, rot=(0, ang, 0), bevel=0.008))
    for s in (-1, 1):
        obs.append(box('Bisagra', c, (0.5, 0.05, 0.05), (0.25, Y(0.98), zc + 0.4 * s), rust))
    boiler = cyl('Caldera', c, 0.82, 6.4, (0, Y(5.85), zc), paint, rot=(math.pi / 2, 0, 0), seg=72)
    obs.append(boiler)
    PARTS_TOP.append(boiler)
    # aros de latón: anillos finos (cilindros huecos simples)
    for d in (3.2, 4.9, 6.6, 8.3):
        obs.append(cyl('Aro', c, 0.835, 0.05, (0, Y(d), zc), brass, rot=(math.pi / 2, 0, 0), seg=72))
    # chimenea
    ch = cyl('Chimenea', c, 0.27, 0.95, (0, Y(1.85), zc + 0.88 + 0.42), soot, r2=0.24, seg=40)
    obs.append(ch)
    obs.append(cyl('Chimenea base', c, 0.4, 0.2, (0, Y(1.85), zc + 0.82), soot, r2=0.28, seg=40))
    lip = cyl('Chimenea borde', c, 0.31, 0.1, (0, Y(1.85), zc + 1.82), soot, seg=40)
    obs.append(lip)
    hole = cyl('tmp', c, 0.2, 1.0, (0, Y(1.85), zc + 1.8), None, seg=32)
    for o in (ch, lip):
        m = o.modifiers.new('hueco', 'BOOLEAN')
        m.object = hole
        m.operation = 'DIFFERENCE'
        from .util import apply_mods
        apply_mods(o)
    bpy.data.objects.remove(hole)
    # domos
    for d, rr, hh in ((4.1, 0.3, 0.45), (5.9, 0.36, 0.55)):
        dm = cyl('Domo', c, rr, hh, (0, Y(d), zc + 0.7 + hh / 2), paint, seg=48)
        obs.append(dm)
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=16, radius=rr)
        for v in bm.verts:
            if v.co.z < 0:
                v.co.z = 0
        cap = bm_obj(bm, 'Domo tapa', c, brass if d > 5 else paint, smooth=True)
        cap.location = (0, Y(d), zc + 0.7 + hh)
        cap.scale = (1, 1, 0.6)
        obs.append(cap)
        PARTS_TOP.append(cap)
    # silbato y válvulas
    obs.append(cyl('Silbato', c, 0.04, 0.35, (0.15, Y(8.7), zc + 1.0), brass, seg=16))
    obs.append(cyl('Valvula', c, 0.06, 0.3, (-0.15, Y(8.6), zc + 0.95), brass, seg=16))
    # farol y placa
    lamp = box('Farol', c, (0.34, 0.3, 0.4), (0, Y(0.95), zc + 1.02), soot, bevel=0.02)
    obs.append(lamp)
    obs.append(cyl('Farol aro', c, 0.13, 0.05, (0, Y(0.79), zc + 1.02), brass, rot=(math.pi / 2, 0, 0), seg=32))
    lens = cyl('Farol cristal', c, 0.115, 0.02, (0, Y(0.775), zc + 1.02), glass, rot=(math.pi / 2, 0, 0), seg=32)
    obs.append(lens)
    obs.append(cyl('Farol chimenea', c, 0.05, 0.15, (0, Y(0.95), zc + 1.28), soot, seg=16))
    for s in (-1, 1):
        obs.append(box('Farol lateral', c, (0.22, 0.2, 0.28), (s * 0.95, Y(0.3), 1.72), soot, bevel=0.015))
        obs.append(cyl('Farol lateral cristal', c, 0.075, 0.02, (s * 0.95, Y(0.19), 1.72), glass, rot=(math.pi / 2, 0, 0), seg=24))
    # placa de número: fondo pintado de rojo oscuro y cifras de latón en relieve
    pl = box('Placa numero', c, (0.98, 0.03, 0.27), (0, Y(0.94), zc - 0.5), red, bevel=0.012)
    obs.append(pl)
    obs.append(box('Marco placa', c, (1.02, 0.02, 0.31), (0, Y(0.955), zc - 0.5), brass, bevel=0.01))
    plate_text(c, '030-2471', (0, Y(0.918), zc - 0.5), brass, size=0.19)
    pl2 = cyl('Placa fabricante', c, 0.16, 0.025, (-0.7, Y(5.1), zc + 0.55), brass, rot=(0, math.pi / 2, 0), seg=40)
    pl2.rotation_euler = (0, math.radians(-90 + 20), 0)

    # --- hogar y cabina
    obs.append(box('Hogar', c, (1.5, 1.6, 1.3), (0, Y(9.0), 2.35), paint, bevel=0.03))
    cab_y = cfg.CAB_Y
    cab = []
    cab.append(box('Cabina frente', c, (2.75, 0.05, 2.1), (0, cab_y + 1.05, 2.9), paint))
    for s in (-1, 1):
        side = box('Cabina lateral', c, (0.05, 2.1, 2.1), (s * 1.37, cab_y, 2.9), paint)
        # ventana lateral
        win = box('tmp', c, (0.5, 0.75, 0.6), (s * 1.37, cab_y + 0.3, 3.35), None)
        m = side.modifiers.new('ventana', 'BOOLEAN')
        m.object = win
        m.operation = 'DIFFERENCE'
        from .util import apply_mods
        apply_mods(side)
        bpy.data.objects.remove(win)
        # hueco de acceso
        door = box('tmp', c, (0.5, 0.55, 1.3), (s * 1.37, cab_y - 0.75, 2.4), None)
        m = side.modifiers.new('puerta', 'BOOLEAN')
        m.object = door
        m.operation = 'DIFFERENCE'
        apply_mods(side)
        bpy.data.objects.remove(door)
        cab.append(side)
    fr = cab[0]
    for s in (-1, 1):
        win = cyl('tmp', c, 0.24, 0.5, (s * 0.85, cab_y + 1.05, 3.45), None, rot=(math.pi / 2, 0, 0), seg=32)
        m = fr.modifiers.new('ojo', 'BOOLEAN')
        m.object = win
        m.operation = 'DIFFERENCE'
        from .util import apply_mods
        apply_mods(fr)
        bpy.data.objects.remove(win)
        obs.append(cyl('Cristal roto', c, 0.24, 0.01, (s * 0.85, cab_y + 1.06, 3.45), glass, rot=(math.pi / 2, 0, 0), seg=32))
    obs.append(box('Suelo cabina', c, (2.7, 2.1, 0.06), (0, cab_y, 1.86), wood))
    # techo curvo, con un trozo arrancado por el árbol
    r = rng(3)
    tx = cfg.TREE_POS[0]
    for i in range(12):
        a0 = math.radians(-60 + 10 * i)
        a1 = math.radians(-60 + 10 * (i + 1))
        xm = 1.6 * math.sin((a0 + a1) / 2)
        if abs(xm - tx) < 0.75:
            continue
        zz = 3.95 + 1.6 * (math.cos((a0 + a1) / 2) - math.cos(math.radians(60)))
        sl = box('Techo cabina', c, (1.6 * (a1 - a0) + 0.01, 2.3, 0.025), (xm, cab_y, zz), paint,
                 rot=(r.uniform(-0.02, 0.02), (a0 + a1) / 2, 0))
        cab.append(sl)
        PARTS_TOP.append(sl)
    # chapa del techo doblada, caída sobre el estribo
    obs.append(box('Chapa caida', c, (0.9, 1.6, 0.02), (1.55, cab_y - 0.3, 2.3), paint, rot=(0.25, -1.2, 0.15)))
    obs.extend(cab)

    # --- ténder
    t0, t1 = 11.5, 17.3
    tl = t1 - t0
    obs.append(box('Tender caja', c, (2.7, tl, 1.75), (0, Y(t0 + tl / 2), 2.45), paint, bevel=0.03))
    obs.append(box('Tender bastidor', c, (2.2, tl + 0.3, 0.4), (0, Y(t0 + tl / 2), 1.3), rust, bevel=0.01))
    obs.append(box('Tender topera', c, (2.7, 0.24, 0.45), (0, Y(t1 + 0.1), 1.25), red, bevel=0.01))
    for s in (-1, 1):
        obs.append(cyl('Tope caja', c, 0.11, 0.38, (s * 0.87, Y(t1 + 0.35), 1.22), rust, rot=(math.pi / 2, 0, 0), seg=24))
        obs.append(cyl('Tope plato', c, 0.2, 0.05, (s * 0.87, Y(t1 + 0.6), 1.22), rust, rot=(math.pi / 2, 0, 0), seg=40))
        for d in (12.5, 14.4, 16.3):
            w, _ = wheel(c, 'Rueda tender', 0.5, s * 0.79, d, (rust, paint), spokes=10, crank=False)
            obs.append(w)
        obs.append(box('Caja grasa', c, (0.22, 5.4, 0.3), (s * 1.0, Y(14.4), 1.12), rust))
    # carbonera llena de tierra (donde crecen plantas)
    coal = box('Tender tierra', c, (2.5, tl - 0.3, 0.3), (0, Y(t0 + tl / 2), 3.25), ctx.get('tunel', {}).get('soil') or rust)
    PARTS_TOP.append(coal)
    obs.append(coal)
    obs.append(box('Depósito agua', c, (2.7, 1.6, 0.35), (0, Y(t1 - 0.8), 3.45), paint, bevel=0.02))
    obs.append(cyl('Boca agua', c, 0.25, 0.15, (0, Y(t1 - 0.8), 3.7), rust, seg=32))

    # --- todo cuelga de un vacío: ligera inclinación de una locomotora hundida en el balasto
    root = bpy.data.objects.new('Locomotora', None)
    c.objects.link(root)
    for o in c.objects:
        if o is root or o.parent:
            continue
        o.parent = root
    root.rotation_euler = (0, math.radians(-1.6), 0)
    root.location = (0, 0, -0.04)
    return {'root': root, 'top': PARTS_TOP, 'paint': paint, 'rust': rust}
