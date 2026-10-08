"""Túnel de ladrillo con la bóveda hundida, la vía, los charcos, los escombros,
el terreno de encima y el acantilado con la boca del túnel."""
import bpy, bmesh, math
import numpy as np
from mathutils import Vector, noise
from . import cfg
from .cfg import Y0, Y1, HALF_W, WALL_H, R_ARCH, THICK, CROWN
from .util import mesh_obj, grid_mesh, bm_obj, box, adaptive, apply_mods, put, coll, rng, bevel
from . import materiales as M


# ------------------------------------------------------------------ perfil
def profile(off=0.0, seg=0.22):
    """Perfil interior (off=0) o exterior (off=THICK) del túnel, de izquierda a derecha."""
    hw, wh, r = HALF_W + off, WALL_H, R_ARCH + off
    z0 = -0.35
    pts = []
    n_wall = max(2, int((wh - z0) / seg))
    for i in range(n_wall + 1):
        pts.append((-hw, z0 + (wh - z0) * i / n_wall))
    n_arc = int(math.pi * r / seg)
    for i in range(1, n_arc):
        a = math.pi - math.pi * i / n_arc
        pts.append((r * math.cos(a), wh + r * math.sin(a)))
    for i in range(n_wall + 1):
        pts.append((hw, wh - (wh - z0) * i / n_wall))
    return pts


def arclen(pts):
    d = [0.0]
    for a, b in zip(pts, pts[1:]):
        d.append(d[-1] + math.dist(a, b))
    return d


def tunnel_shell(c, mat):
    pin, pout = profile(0.0), profile(THICK)
    # mismo número de puntos en ambos perfiles (se remuestrea el exterior)
    la, lb = arclen(pin), arclen(pout)
    pout = [(np.interp(t / la[-1] * lb[-1], lb, [p[0] for p in profile(THICK)]),
             np.interp(t / la[-1] * lb[-1], lb, [p[1] for p in profile(THICK)])) for t in la]
    n = len(pin)
    ys = np.arange(Y0, Y1 + 1e-6, 0.25)
    verts, faces, uvs = [], [], []
    for y in ys:
        for p in pin:
            verts.append((p[0], y, p[1]))
    for y in ys:
        for p in pout:
            verts.append((p[0], y, p[1]))
    R = len(ys)
    off = R * n

    def vi(ring, k, outer=False):
        return (off if outer else 0) + ring * n + k

    for j in range(R - 1):
        for k in range(n - 1):
            # cara interior (normal hacia dentro del túnel)
            f = (vi(j, k), vi(j + 1, k), vi(j + 1, k + 1), vi(j, k + 1))
            faces.append(f)
            uvs.append([(la[k], ys[j]), (la[k], ys[j + 1]), (la[k + 1], ys[j + 1]), (la[k + 1], ys[j])])
            g = (vi(j, k, 1), vi(j, k + 1, 1), vi(j + 1, k + 1, 1), vi(j + 1, k, 1))
            faces.append(g)
            uvs.append([(la[k], ys[j]), (la[k + 1], ys[j]), (la[k + 1], ys[j + 1]), (la[k], ys[j + 1])])
        # cantos inferiores
        for k, rev in ((0, False), (n - 1, True)):
            f = (vi(j, k), vi(j, k, 1), vi(j + 1, k, 1), vi(j + 1, k))
            faces.append(f[::-1] if rev else f)
            uvs.append([(0, ys[j]), (1, ys[j]), (1, ys[j + 1]), (0, ys[j + 1])])
    # tapas de los extremos
    for j, rev in ((0, False), (R - 1, True)):
        for k in range(n - 1):
            f = (vi(j, k), vi(j, k + 1), vi(j, k + 1, 1), vi(j, k, 1))
            faces.append(f[::-1] if rev else f)
            uvs.append([(la[k], 0), (la[k + 1], 0), (la[k + 1], 1), (la[k], 1)])
    ob = mesh_obj('Tunel', verts, faces, c, uv=uvs, mat=mat)
    return ob


# ------------------------------------------------------------------ hundimientos de la bóveda
def hole_center(target):
    """Punto de la bóveda por el que entra el rayo de sol que cae en 'target'."""
    p = Vector(target)
    d = cfg.SUN_DIR
    for _ in range(4000):
        p += d * 0.02
        if p.z >= cfg.vault_z(p.x):
            return p
    return p


def noisy_polygon(cx, cy, rx, ry, seed, n=48, rough=0.28):
    r = rng(seed)
    ph = r.uniform(0, 6.28, 4)
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        k = 1 + rough * (0.5 * math.sin(2 * a + ph[0]) + 0.3 * math.sin(3 * a + ph[1]) +
                         0.2 * math.sin(5 * a + ph[2]) + 0.15 * math.sin(9 * a + ph[3]))
        k += r.uniform(-0.06, 0.06)
        pts.append((cx + rx * k * math.cos(a), cy + ry * k * math.sin(a)))
    return pts


def prism(name, pts, z0, z1, c, slant_zc=None):
    """Prisma vertical, o inclinado según la dirección del sol si slant_zc (altura de referencia)."""
    bm = bmesh.new()

    def at(x, y, z):
        if slant_zc is None:
            return (x, y, z)
        k = (z - slant_zc) / cfg.SUN_DIR.z
        return (x + cfg.SUN_DIR.x * k, y + cfg.SUN_DIR.y * k, z)
    bot = [bm.verts.new(at(x, y, z0)) for x, y in pts]
    top = [bm.verts.new(at(x, y, z1)) for x, y in pts]
    bm.faces.new(bot[::-1])
    bm.faces.new(top)
    n = len(pts)
    for i in range(n):
        bm.faces.new((bot[i], bot[(i + 1) % n], top[(i + 1) % n], top[i]))
    bm.normal_update()
    return bm_obj(bm, name, c)


HERO_PUDDLE = (-3.0, 9.2)   # charco donde cae la gota del primer plano
HOLES = []   # (nombre, polígono, centro)
TARGETS = []  # puntos donde cae el sol que entra por cada hundimiento


def make_holes(cut_coll):
    specs = [
        ('Hundimiento 1', (HERO_PUDDLE[0] + 0.3, HERO_PUDDLE[1], 0.1), 1.5, 2.1, 11),
        ('Hundimiento 3', (1.4, -8.0, 0.25), 1.1, 1.6, 13),
        # por aquí se asoma el monstruo (tiene que caber: más ancho que los demás)
        ('Hundimiento 4', cfg.H4_TARGET, 2.3, 2.9, 14),
    ]
    cutters = []
    for name, tgt, rx, ry, seed in specs:
        h = hole_center(tgt)
        TARGETS.append(tgt)
        pts = noisy_polygon(h.x, h.y, rx, ry, seed)
        HOLES.append((name, pts, (h.x, h.y)))
    # el gran hundimiento: desde detrás de la cabina (árbol) hasta donde entra el sol que la ilumina
    h = hole_center((0.2, cfg.CAB_Y + 0.5, 3.2))
    TARGETS.append((0.2, cfg.CAB_Y + 0.5, 3.2))
    y_lo = cfg.TREE_POS[1] - 2.6
    y_hi = h.y + 2.0
    pts = noisy_polygon(0.15, (y_lo + y_hi) / 2, 2.7, (y_hi - y_lo) / 2, 12, n=64, rough=0.22)
    HOLES.append(('Hundimiento 2', pts, (0.15, (y_lo + y_hi) / 2)))
    for name, pts, (hx, hy) in HOLES:
        zc = cfg.vault_z(hx)
        cutters.append(prism('Corte ' + name, pts, WALL_H + 0.6, 40.0, cut_coll))
        cutters.append(prism('Corte sol ' + name, pts, zc - 0.6, 40.0, cut_coll, slant_zc=zc))
    return cutters


def point_in_poly(x, y, pts):
    inside = False
    n = len(pts)
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def delete_faces(ob, test):
    """Borra las caras de una superficie abierta cuyo centro cumpla test(centro)."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    kill = [f for f in bm.faces if test(f.calc_center_median())]
    bmesh.ops.delete(bm, geom=kill, context='FACES')
    bm.to_mesh(ob.data)
    bm.free()


def boolean_cut(ob, cutters, edge_mat=None):
    """edge_mat: material de las caras del corte (la rotura de la bóveda), que no tienen UV útiles."""
    for k, ct in enumerate(cutters):
        if edge_mat is not None:
            ct.data.materials.clear()
            ct.data.materials.append(edge_mat)
        m = ob.modifiers.new('hueco%d' % k, 'BOOLEAN')
        m.operation = 'DIFFERENCE'
        m.solver = 'EXACT'
        m.object = ct
        if edge_mat is not None:
            m.material_mode = 'TRANSFER'
    apply_mods(ob)


# ------------------------------------------------------------------ terreno de encima
def top_z(x, y):
    base = CROWN + THICK + 0.45
    ax = abs(x)
    rise = 0.0 if ax < 8 else ((ax - 8) ** 1.3) * 0.12
    back = max(0.0, (-y - 135)) * 0.22     # el monte sube al fondo del túnel
    n = noise.fractal(Vector((x * 0.08, y * 0.08, 0.3)), 0.6, 2.0, 4) * 0.6
    n2 = noise.fractal(Vector((x * 0.012, y * 0.012, 1.7)), 0.5, 2.0, 3) * 6.0 * min(1.0, ax / 30)
    return base + rise + back + n + n2


def massif(c, mat):
    """El monte que atraviesa el túnel (alrededor del parche fino de encima del túnel)."""
    xs = np.concatenate([-np.geomspace(1100, 30, 70), np.linspace(-30, 30, 13)[1:-1], np.geomspace(30, 1100, 70)])
    ys = np.concatenate([-np.geomspace(700, -(Y0 - 10), 40), np.linspace(Y0 - 10, Y1, 70)[1:]])
    verts, faces, uvs = [], [], []
    W = len(xs)
    for y in ys:
        for x in xs:
            verts.append((x, y, top_z(x, y)))
    for j in range(len(ys) - 1):
        for i in range(W - 1):
            cx = (xs[i] + xs[i + 1]) / 2
            cy = (ys[j] + ys[j + 1]) / 2
            if abs(cx) < 30 and cy > Y0 - 10:
                continue
            a = j * W + i
            f = (a, a + 1, a + 1 + W, a + W)
            faces.append(f)
            uvs.append([(verts[k][0] / 6, verts[k][1] / 6) for k in f])
    ob = mesh_obj('Monte', verts, faces, c, uv=uvs, mat=mat)
    adaptive(ob, 1.5)
    return ob


def terrain_top(c, mat, cutters):
    def f(u, v):
        x = -31 + 62 * u
        y = Y0 - 10 + (cfg.Y1 + 1.5 - (Y0 - 10)) * v
        return (x, y, top_z(x, y))
    ob = grid_mesh('Terreno sobre el tunel', 120, int((Y1 + 11.5 - Y0) / 0.5), f, c, uvscale=4.0, mat=mat)
    def in_hole(p):
        for _, pts, (hx, hy) in HOLES:
            if point_in_poly(p.x, p.y, pts):
                return True
            k = (p.z - cfg.vault_z(hx)) / cfg.SUN_DIR.z
            if point_in_poly(p.x - cfg.SUN_DIR.x * k, p.y - cfg.SUN_DIR.y * k, pts):
                return True
        from . import pozo
        return pozo.in_collar(p.x, p.y)
    delete_faces(ob, in_hole)
    adaptive(ob)
    return ob


# ------------------------------------------------------------------ acantilado y boca
def cliff_y(x, z):
    """Posición Y de la pared del acantilado (la boca está en y=100)."""
    lean = (-z) * 0.07 if z < 0 else -z * 0.12
    near = min(1.0, max(0.0, (abs(x) - 7.5) / 10.0)) if z < 13 else 1.0
    amp = 0.25 + 5.5 * near
    n = noise.fractal(Vector((x * 0.035, z * 0.035, 4.2)), 0.55, 2.0, 6)
    n2 = noise.fractal(Vector((x * 0.008, z * 0.01, 8.1)), 0.5, 2.0, 3)
    # estratos: repisas horizontales de roca
    zz = z + noise.noise(Vector((x * 0.01, 0.5, 3.0))) * 6.0
    strata = (zz / 7.0) % 1.0
    ledge = (strata ** 3) * 3.5 * near
    return Y1 + lean + n * amp + n2 * 16 * near + ledge


def cliff(c, mat):
    xs = np.sign(np.linspace(-1, 1, 321)) * np.abs(np.linspace(-1, 1, 321)) ** 1.7 * 450
    zs = np.linspace(cfg.VALLEY_Z - 8, 1, 1)
    verts, faces, uvs = [], [], []
    rows = []
    NZ = 140
    for i, x in enumerate(xs):
        ztop = top_z(x, Y1)
        col = []
        for j in range(NZ + 1):
            t = j / NZ
            z = (cfg.VALLEY_Z - 8) + (ztop + 0.6 - (cfg.VALLEY_Z - 8)) * t
            y = cliff_y(x, z) if t < 0.995 else Y1 - 1.0
            col.append(len(verts))
            verts.append((x, y, z))
        rows.append(col)
    for i in range(len(xs) - 1):
        for j in range(NZ):
            f = (rows[i][j], rows[i + 1][j], rows[i + 1][j + 1], rows[i][j + 1])
            faces.append(f)
            uvs.append([(verts[k][0] / 4, verts[k][2] / 4) for k in f])
    ob = mesh_obj('Acantilado', verts, faces, c, uv=uvs, mat=mat)
    # boca del túnel
    delete_faces(ob, lambda p: p.z > -0.3 and abs(p.x) < HALF_W + 0.9 and p.z < cfg.vault_z(p.x) + 0.9)
    adaptive(ob)
    return ob


def prism_profile(name, prof, y0, y1, c, scale=1.0):
    pts = [(x * scale, z) for x, z in prof]
    bm = bmesh.new()
    a = [bm.verts.new((x, y0, z)) for x, z in pts]
    b = [bm.verts.new((x, y1, z)) for x, z in pts]
    bm.faces.new(a)
    bm.faces.new(b[::-1])
    n = len(pts)
    for i in range(n):
        bm.faces.new((a[i], b[i], b[(i + 1) % n], a[(i + 1) % n]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm_obj(bm, name, c)


def portal(c, mat):
    """Arco de sillería de la boca: dovelas, impostas y muros de acompañamiento."""
    r = rng(5)
    obs = []
    n = 23
    r_in, r_out = R_ARCH, R_ARCH + 1.15
    for i in range(n):
        a0 = math.pi * i / n
        a1 = math.pi * (i + 1) / n
        bm = bmesh.new()
        q = []
        for (a, rr) in ((a0, r_in), (a1, r_in), (a1, r_out), (a0, r_out)):
            q.append((rr * math.cos(a), WALL_H + rr * math.sin(a)))
        dy = r.uniform(-0.06, 0.06)
        v0 = [bm.verts.new((x, Y1 - 1.6, z)) for x, z in q]
        v1 = [bm.verts.new((x, Y1 + 0.35 + dy, z)) for x, z in q]
        bm.faces.new(v0[::-1])
        bm.faces.new(v1)
        for k in range(4):
            bm.faces.new((v0[k], v0[(k + 1) % 4], v1[(k + 1) % 4], v1[k]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        ob = bm_obj(bm, 'Dovela', c, mat)
        ob.rotation_euler = (r.uniform(-0.01, 0.01), r.uniform(-0.012, 0.012), 0)
        bevel(ob, 0.03, 2)
        obs.append(ob)
    # jambas de sillares
    for side in (-1, 1):
        z = -0.3
        while z < WALL_H:
            h = r.uniform(0.45, 0.6)
            w = r.uniform(0.9, 1.25)
            b = box('Sillar jamba', c, (w, 2.0 + r.uniform(-0.05, 0.1), h - 0.015),
                    (side * (HALF_W + w / 2), Y1 - 0.65, z + h / 2), mat)
            bevel(b, 0.03, 2)
            obs.append(b)
            z += h
    # imposta y cornisa
    for side in (-1, 1):
        b = box('Imposta', c, (1.6, 2.2, 0.25), (side * (HALF_W + 0.6), Y1 - 0.6, WALL_H + 0.05), mat)
        bevel(b, 0.03, 2)
        obs.append(b)
    b = box('Cornisa', c, (14.5, 1.0, 0.45), (0, Y1 + 0.2, CROWN + 1.7), mat)
    bevel(b, 0.04, 2)
    obs.append(b)
    return obs


# ------------------------------------------------------------------ vía
def sweep(name, prof, path, c, mat, closed=True, uv_scale=1.0):
    """Barre un perfil 2D (x, z) a lo largo de una polilínea 3D (con marcos estables)."""
    path = [Vector(p) for p in path]
    verts, faces, uvs = [], [], []
    n = len(prof)
    L = [0.0]
    for a, b in zip(path, path[1:]):
        L.append(L[-1] + (b - a).length)
    up0 = Vector((0, 0, 1))
    for i, p in enumerate(path):
        t = (path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]).normalized()
        side = t.cross(up0)
        if side.length < 1e-4:
            side = Vector((1, 0, 0))
        side.normalize()
        up = side.cross(t).normalized()
        # perfil en (lado, arriba)
        for x, z in prof:
            verts.append(tuple(p - side * x + up * z))
    m = len(path)
    for i in range(m - 1):
        for k in range(n if closed else n - 1):
            k2 = (k + 1) % n
            f = (i * n + k, i * n + k2, (i + 1) * n + k2, (i + 1) * n + k)
            faces.append(f)
            uvs.append([(k / n, L[i] / uv_scale), (k2 / n, L[i] / uv_scale), (k2 / n, L[i + 1] / uv_scale), (k / n, L[i + 1] / uv_scale)])
    return mesh_obj(name, verts, faces, c, uv=uvs, mat=mat)


RAIL_PROFILE = [(-0.075, 0.0), (0.075, 0.0), (0.075, 0.012), (0.012, 0.03), (0.009, 0.105), (0.036, 0.115),
                (0.036, 0.15), (-0.036, 0.15), (-0.036, 0.115), (-0.009, 0.105), (-0.012, 0.03), (-0.075, 0.012)]


def rail_path(x, y_start, y_end, gap=None):
    pts = []
    y = y_start
    while y <= y_end:
        z = cfg.SLEEPER_TOP
        # pequeños asientos y ondulaciones de una vía abandonada
        z += noise.noise(Vector((x * 0.3, y * 0.07, 2.0))) * 0.012
        xx = x + noise.noise(Vector((x, y * 0.03, 5.0))) * 0.012
        pts.append((xx, y, z))
        y += 0.5
    if gap:
        # el carril queda colgando sobre el hueco del viaducto, doblado
        base = Vector(pts[-1])
        k = 0.0
        for i in range(1, 30):
            s = i * 0.5
            ang = min(1.35, 0.0035 * s * s + 0.02 * s)
            k += 0.5
            base = base + Vector((0.004 * s * (1 if x > 0 else -1), math.cos(ang) * 0.5, -math.sin(ang) * 0.5))
            pts.append(tuple(base))
    return pts


def track(c, y_start, y_end, mats, seed=1, gap=False, missing=0.06):
    rail_m, wood_m, ballast_m = mats
    r = rng(seed)
    obs = []
    for x in (-cfg.RAIL_X, cfg.RAIL_X):
        obs.append(sweep('Carril', RAIL_PROFILE, rail_path(x, y_start, y_end, gap), c, rail_m))
    # traviesas
    y = y_start + 0.3
    sl = []
    while y < y_end - 0.2:
        if r.random() > missing:
            w = 2.6 + r.uniform(-0.05, 0.05)
            b = box('Traviesa', c, (w, 0.24, 0.15), (r.uniform(-0.04, 0.04), y + r.uniform(-0.03, 0.03),
                                                       cfg.SLEEPER_TOP - 0.075 - r.uniform(0, 0.025)), wood_m,
                    rot=(r.uniform(-0.02, 0.02), r.uniform(-0.03, 0.03), r.uniform(-0.035, 0.035)))
            sl.append(b)
        y += 0.65
    # se unen todas las traviesas en un objeto (mucho más ligero)
    from .util import join
    trav = join(sl, 'Traviesas')
    bevel(trav, 0.012, 1)
    obs.append(trav)
    # balasto: prisma trapecial con desplazamiento
    prof = [(-2.2, 0.0), (-1.55, cfg.BALLAST_TOP), (1.55, cfg.BALLAST_TOP), (2.2, 0.0)]
    pts = []
    for i in range(int((y_end - y_start) / 0.5) + 1):
        pts.append((0, y_start + i * 0.5, 0.0))
    bal = sweep('Balasto', prof, pts, c, ballast_m, closed=False)
    # subdividir a lo ancho para que el desplazamiento tenga dónde trabajar
    adaptive(bal)
    obs.append(bal)
    return obs


# ------------------------------------------------------------------ suelo, charcos y escombros
def floor(c, mat):
    def f(u, v):
        x = -HALF_W - 0.4 + (2 * HALF_W + 0.8) * u
        y = Y0 + (Y1 + 6 - Y0) * v
        z = 0.02 + noise.fractal(Vector((x * 0.4, y * 0.4, 7.0)), 0.6, 2.0, 3) * 0.05
        return (x, y, z)
    ob = grid_mesh('Suelo tunel', 40, int((Y1 + 6 - Y0) / 0.26), f, c, uvscale=2.0, mat=mat)
    adaptive(ob)
    return ob


PUDDLE_DROP = None   # (x, y, z) del charco del primer plano


def puddles(c, mat, sleeper_ys):
    global PUDDLE_DROP
    r = rng(21)
    obs = []
    # charcos al pie de los muros y a los lados del balasto
    for i in range(26):
        x = r.choice([-1, 1]) * r.uniform(2.4, 4.0)
        y = r.uniform(Y0 + 4, Y1 - 3)
        pts = noisy_polygon(x, y, r.uniform(0.4, 1.1), r.uniform(0.8, 2.6), 100 + i, n=40, rough=0.35)
        bm = bmesh.new()
        vs = [bm.verts.new((px, py, 0.045)) for px, py in pts]
        bm.faces.new(vs)
        obs.append(bm_obj(bm, 'Charco', c, mat))
    # charco del plano de la gota: en el suelo de tierra, junto al muro izquierdo
    hx, hy = HERO_PUDDLE
    pts = noisy_polygon(hx, hy, 0.75, 1.3, 77, n=48, rough=0.18)
    bm = bmesh.new()
    vs = [bm.verts.new((px, py, 0.085)) for px, py in pts]
    bm.faces.new(vs)
    ob = bm_obj(bm, 'Charco gota', c, mat)
    PUDDLE_DROP = (hx, hy, 0.085)
    obs.append(ob)
    return obs


def rubble(c, mats, center, radius, height, n, seed, z0=0.0):
    """Montón de escombros: un túmulo de tierra y bloques de ladrillo caídos."""
    brick_m, soil_m = mats
    r = rng(seed)
    cx, cy = center

    def f(u, v):
        x = cx - radius * 1.3 + 2.6 * radius * u
        y = cy - radius * 1.3 + 2.6 * radius * v
        d = math.hypot((x - cx) / radius, (y - cy) / (radius * 1.25))
        h = height * max(0.0, 1 - d * d) ** 1.4
        h += noise.fractal(Vector((x * 0.7, y * 0.7, seed)), 0.6, 2.0, 4) * 0.12 * (h > 0.02)
        return (x, y, z0 + h - 0.05)
    mound = grid_mesh('Escombros tierra', 48, 48, f, c, uvscale=2.0, mat=soil_m)
    adaptive(mound)
    blocks = []
    for i in range(n):
        a = r.uniform(0, 2 * math.pi)
        d = radius * math.sqrt(r.uniform(0, 1)) * 1.1
        x, y = cx + d * math.cos(a), cy + d * math.sin(a) * 1.2
        dd = math.hypot((x - cx) / radius, (y - cy) / (radius * 1.25))
        h = z0 + height * max(0.0, 1 - dd * dd) ** 1.4
        s = r.uniform(0.25, 0.9)
        dims = (s * r.uniform(0.8, 1.6), s * r.uniform(0.6, 1.2), s * r.uniform(0.25, 0.55))
        b = box('Bloque', c, dims, (x, y, h + dims[2] * 0.2), brick_m,
                rot=tuple(r.uniform(-0.6, 0.6, 3)))
        blocks.append(b)
    from .util import join
    if blocks:
        j = join(blocks, 'Bloques caidos')
        bevel(j, 0.025, 2)
    return mound


def build(main_c):
    c = coll('Tunel', main_c)
    cut_c = coll('Cortes', main_c)
    brick = M.mat_ladrillo_tunel()
    soil = M.mat_generic('Tierra y hojas', 'tierra', 0.5, moss=0.45, wet=0.5, disp_scale=0.04)
    rock = M.mat_generic('Roca acantilado', 'roca', 0.12, moss=0.5, disp_scale=0.35, bump=1.5, tint=(0.8, 0.8, 0.82), sat=0.35,
                         weather=1.0, weather_z=(30.0, -72.0))
    stone = M.mat_generic('Sillar', 'sillar', 0.33, moss=0.55, disp_scale=0.0, weather=0.8, weather_z=(cfg.CROWN + 3, -2.0), real=1.2)
    top_m = M.mat_generic('Tierra monte', 'tierra', 0.35, moss=0.7, disp_scale=0.05, backface=(0.025, 0.017, 0.01))
    shell = tunnel_shell(c, brick)
    cutters = make_holes(cut_c)
    broken = M.mat_generic('Rotura boveda', 'ladrillo', 0.33, moss=0.6, disp_scale=0.03, bump=1.5,
                           weather=0.8, weather_z=(CROWN + 2, 0.0), real=1.0)
    boolean_cut(shell, cutters, broken)
    from . import pozo
    pozo.cut_shell(shell)
    adaptive(shell)
    terrain_top(c, top_m, cutters)
    massif(c, M.mat_paisaje('Monte', 0.1, disp_scale=0.15))
    for ct in cutters:
        bpy.data.objects.remove(ct)
    bpy.data.collections.remove(cut_c)
    cl = cliff(c, rock)
    portal(c, stone)
    floor(c, soil)
    # vía del túnel
    rail_m = M.mat_rail()
    wood_m = M.mat_generic('Madera traviesas', 'madera', 0.8, moss=0.55, bump=1.2)
    bal_m = M.mat_generic('Balasto', 'balasto', 0.7, box=False, uv_scale=None, moss=0.3, disp_scale=0.06)
    trk = track(c, Y0 + 3, Y1 + 0.4, (rail_m, wood_m, bal_m), seed=2)
    sleepers = []
    y = Y0 + 3 + 0.3
    while y < Y1:
        sleepers.append(y)
        y += 0.65
    puddles(c, M.mat_agua(), sleepers)
    # escombros bajo los hundimientos y en el fondo
    for name, pts, (hx, hy) in HOLES:
        big = name.endswith('2')
        if big:
            # el derrumbe grande cae a los lados de la locomotora
            rubble(c, (brick, soil), (-3.3, 39.0), 1.6, 1.1, 40, 31)
            rubble(c, (brick, soil), (3.1, hy - 2.0), 1.5, 1.3, 40, 32)
            # (en "Vía muerta" la locomotora sale: este montón va pegado al muro, fuera de la vía)
            rubble(c, (brick, soil), (-3.5, hy + 5.0), 1.3, 0.9, 30, 33)
        elif name.endswith('4'):
            # el del monstruo: escombros a un lado, la vía queda libre para caminar
            rubble(c, (brick, soil), (hx - 1.6, hy + 0.8), 1.5, 0.6, 30, 34)
        else:
            rubble(c, (brick, soil), (hx * 0.6 + (2.6 if hx < 0 else -2.6) * 0, hy), 1.7, 0.75, 35, int(hy))
    rubble(c, (brick, soil), (0.0, Y0 + 2.5), 5.0, 6.0, 120, 40)
    return {'brick': brick, 'soil': soil, 'stone': stone, 'rail': rail_m, 'wood': wood_m, 'ballast': bal_m,
            'rock': rock, 'top': top_m}
