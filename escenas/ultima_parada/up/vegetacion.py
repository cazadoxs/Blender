"""Vegetación: plantas dispersadas con nodos de geometría (crecen donde llega la luz),
hiedra que trepa por la locomotora y cuelga de los hundimientos, raíces que bajan
de la bóveda, el árbol que atraviesa la cabina, polvo en suspensión y hojas cayendo."""
import bpy, bmesh, math
import numpy as np
from mathutils import Vector, Matrix, noise
from mathutils.bvhtree import BVHTree
from . import cfg, plantas as P
from . import materiales as M
from .util import coll, NB, rng, mesh_obj, bm_obj, join, hidden_coll


# ------------------------------------------------------------------ dispersión con nodos de geometría
def scatter(name, surface, lib, density, c, scale=(0.7, 1.3), seed=0, tilt=0.12, sway=0.04, align=False,
            attr='dens', zoff=0.0, dist_min=0.0):
    ob = bpy.data.objects.new(name, bpy.data.meshes.new(name))
    c.objects.link(ob)
    ng = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    ng.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    nb = NB(ng)
    gin = nb.n('NodeGroupInput')
    gout = nb.n('NodeGroupOutput')
    oi = nb.n('GeometryNodeObjectInfo', transform_space='RELATIVE')
    oi.inputs['Object'].default_value = surface
    dens = nb.n('GeometryNodeInputNamedAttribute', data_type='FLOAT')
    dens.inputs['Name'].default_value = attr
    dmul = nb.math('MULTIPLY', nb.out(dens, 'Attribute'), density)
    if dist_min > 0:
        dist = nb.n('GeometryNodeDistributePointsOnFaces', distribute_method='POISSON')
        nb.set(dist.inputs['Distance Min'], dist_min)
        nb.set(dist.inputs['Density Max'], density)
        nb.set(dist.inputs['Density Factor'], nb.out(dens, 'Attribute'))
    else:
        dist = nb.n('GeometryNodeDistributePointsOnFaces', distribute_method='RANDOM')
        nb.set(dist.inputs['Density'], dmul)
    nb.set(dist.inputs['Mesh'], nb.out(oi, 'Geometry'))
    nb.set(dist.inputs['Seed'], seed)
    ci = nb.n('GeometryNodeCollectionInfo', transform_space='ORIGINAL')
    ci.inputs['Collection'].default_value = lib
    ci.inputs['Separate Children'].default_value = True
    ci.inputs['Reset Children'].default_value = True
    n_items = max(1, len(lib.objects) + len(lib.children))
    ridx = nb.n('FunctionNodeRandomValue', data_type='INT')
    NB._sock(ridx.inputs, 'Min_002').default_value = 0
    NB._sock(ridx.inputs, 'Max_002').default_value = n_items - 1
    ridx.inputs['Seed'].default_value = seed + 1
    rrot = nb.n('FunctionNodeRandomValue', data_type='FLOAT_VECTOR')
    NB._sock(rrot.inputs, 'Min').default_value = (-tilt, -tilt, 0)
    NB._sock(rrot.inputs, 'Max').default_value = (tilt, tilt, 2 * math.pi)
    rrot.inputs['Seed'].default_value = seed + 2
    rsc = nb.n('FunctionNodeRandomValue', data_type='FLOAT')
    NB._sock(rsc.inputs, 'Min_001').default_value = scale[0]
    NB._sock(rsc.inputs, 'Max_001').default_value = scale[1]
    rsc.inputs['Seed'].default_value = seed + 3
    pos_pts = nb.n('GeometryNodeSetPosition')
    nb.set(pos_pts.inputs['Geometry'], nb.out(dist, 'Points'))
    nb.set(pos_pts.inputs['Offset'], (0, 0, zoff))
    iop = nb.n('GeometryNodeInstanceOnPoints')
    nb.set(iop.inputs['Points'], nb.out(pos_pts))
    nb.set(iop.inputs['Instance'], nb.out(ci))
    iop.inputs['Pick Instance'].default_value = True
    nb.set(iop.inputs['Instance Index'], nb.out(ridx, 0))
    if align:
        rot = nb.n('FunctionNodeRotateRotation', rotation_space='LOCAL')
        nb.set(rot.inputs['Rotation'], nb.out(dist, 'Rotation'))
        e2r = nb.n('FunctionNodeEulerToRotation', {'Euler': nb.out(rrot, 0)})
        nb.set(rot.inputs['Rotate By'], nb.out(e2r))
        nb.set(iop.inputs['Rotation'], nb.out(rot))
    else:
        e2r = nb.n('FunctionNodeEulerToRotation', {'Euler': nb.out(rrot, 0)})
        nb.set(iop.inputs['Rotation'], nb.out(e2r))
    nb.set(iop.inputs['Scale'], nb.out(rsc, 0))
    out_geo = nb.out(iop)
    if sway > 0:
        # balanceo suave con el aire (determinista: depende solo del tiempo)
        st = nb.n('GeometryNodeInputSceneTime')
        pos = nb.n('GeometryNodeInputPosition')
        nz = nb.n('ShaderNodeTexNoise', noise_dimensions='4D')
        nb.set(nz.inputs['Vector'], nb.vmath('SCALE', nb.out(pos), scale=0.35))
        nb.set(nz.inputs['W'], nb.math('MULTIPLY', nb.out(st, 'Seconds'), 0.45))
        nz.inputs['Scale'].default_value = 1.0
        nz.inputs['Detail'].default_value = 2.0
        off = nb.vmath('SUBTRACT', nb.out(nz, 'Color'), (0.5, 0.5, 0.5))
        eul = nb.vmath('MULTIPLY', off, (sway * 2, sway * 2, 0))
        e2 = nb.n('FunctionNodeEulerToRotation', {'Euler': eul})
        ri = nb.n('GeometryNodeRotateInstances')
        nb.set(ri.inputs['Instances'], out_geo)
        nb.set(ri.inputs['Rotation'], nb.out(e2))
        ri.inputs['Local Space'].default_value = True
        out_geo = nb.out(ri)
    nb.set(gout.inputs[0], out_geo)
    mod = ob.modifiers.new('dispersion', 'NODES')
    mod.node_group = ng
    return ob


def set_density(ob, fn):
    """Atributo 'dens' por vértice a partir de fn(x, y, z) (coordenadas de mundo)."""
    me = ob.data
    mw = ob.matrix_world
    vals = np.array([max(0.0, fn(*(mw @ v.co))) for v in me.vertices], dtype=np.float32)
    at = me.attributes.get('dens') or me.attributes.new('dens', 'FLOAT', 'POINT')
    at.data.foreach_set('value', vals)


def light_amount(x, y, z=0.0):
    """Cuánta luz recibe un punto del túnel (las plantas crecen donde hay luz)."""
    from . import tunel
    v = 0.0
    for _, pts, (hx, hy) in tunel.HOLES:
        d2 = (x - hx) ** 2 + (y - hy) ** 2
        v = max(v, math.exp(-d2 / (2 * 3.2 ** 2)))
    for tx, ty, tz in tunel.TARGETS:
        d2 = (x - tx) ** 2 + ((y - ty) * 0.6) ** 2
        v = max(v, 0.75 * math.exp(-d2 / (2 * 2.6 ** 2)))
    if y > cfg.Y1 - 30:
        v = max(v, min(1.0, (y - (cfg.Y1 - 30)) / 26.0) ** 1.5)
    if y > cfg.Y1 - 0.5:
        v = 1.0
    nz = noise.fractal(Vector((x * 0.35, y * 0.35, 3.3)), 0.6, 2.0, 3)
    v *= max(0.0, 0.8 + 0.9 * nz)
    # el charco del primer plano queda despejado
    hx, hy = tunel.HERO_PUDDLE
    if (x - hx) ** 2 + ((y - hy) / 1.4) ** 2 < 1.6 ** 2:
        return 0.0
    # junto a los muros crece más (menos pisado, más humedad)
    wall = max(0.0, (abs(x) - 2.3) / 2.0)
    return v * (0.7 + 0.6 * min(1.0, wall)) + 0.02


# ------------------------------------------------------------------ BVH y hiedra
def bvh_of(objs):
    verts, polys = [], []
    dg = bpy.context.evaluated_depsgraph_get()
    for o in objs:
        if o.type not in ('MESH', 'CURVE', 'FONT'):
            continue
        ev = o.evaluated_get(dg)
        try:
            me = ev.to_mesh()
        except RuntimeError:
            continue
        mw = o.matrix_world
        base = len(verts)
        verts.extend([mw @ v.co for v in me.vertices])
        polys.extend([[base + i for i in p.vertices] for p in me.polygons])
        ev.to_mesh_clear()
    return BVHTree.FromPolygons(verts, polys, all_triangles=False)


def ivy(bvh, start, steps, seed, up=0.6, gravity=0.0, step=0.07, leaf_every=1, leaf_size=(0.05, 0.09),
        branch_p=0.04, max_branches=6):
    """Hiedra que se arrastra por una superficie. Devuelve (tallos, hojas[(pos, normal, dir)])."""
    r = rng(seed)
    stems, leaves = [], []
    queue = [(Vector(start), None, steps)]
    nb = 0
    while queue:
        p, d, n = queue.pop()
        hit = bvh.find_nearest(p, 0.6)
        if hit[0] is None:
            continue
        p, nrm = hit[0], hit[1]
        if d is None:
            d = Vector((r.normal(), r.normal(), up - gravity)).normalized()
        pts = [p + nrm * 0.01]
        for i in range(n):
            wobble = Vector(r.normal(0, 0.55, 3))
            d = (d + wobble * 0.35 + Vector((0, 0, (up - gravity) * 0.35))).normalized()
            d = (d - nrm * d.dot(nrm))
            if d.length < 1e-3:
                break
            d.normalize()
            q = p + d * step
            hit = bvh.find_nearest(q, 0.25)
            if hit[0] is None:
                break
            p, nrm = hit[0], hit[1]
            pts.append(p + nrm * 0.012)
            if i % leaf_every == 0:
                for s in (-1, 1):
                    if r.random() < 0.75:
                        side = d.cross(nrm).normalized() * s
                        ld = (side + Vector((0, 0, -0.35)) + nrm * 0.4).normalized()
                        leaves.append((p + nrm * 0.02 + side * 0.02, (nrm + Vector(r.normal(0, 0.3, 3))).normalized(), ld,
                                       r.uniform(*leaf_size)))
            if nb < max_branches and r.random() < branch_p and i > 4:
                nb += 1
                bd = (d + d.cross(nrm) * r.choice([-1, 1]) * 1.2).normalized()
                queue.append((p.copy(), bd, int((n - i) * 0.7)))
        if len(pts) > 2:
            stems.append(pts)
    return stems, leaves


def stems_curve(name, stems, c, mat, radius=0.008):
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    cu.bevel_depth = radius
    cu.bevel_resolution = 1
    cu.resolution_u = 2
    for pts in stems:
        sp = cu.splines.new('POLY')
        sp.points.add(len(pts) - 1)
        for k, p in enumerate(pts):
            sp.points[k].co = (p.x, p.y, p.z, 1)
            sp.points[k].radius = 1.0 - 0.6 * k / len(pts)
    ob = bpy.data.objects.new(name, cu)
    c.objects.link(ob)
    cu.materials.append(mat)
    return ob


def leaves_mesh(name, leaves, c, mat, ivy_shape=True):
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new('UVMap')
    for p, nrm, d, L in leaves:
        P.leaf_quad(bm, p, d, nrm, L, L * (0.9 if ivy_shape else 0.5), uv, bend=0.15, segs=2)
    return bm_obj(bm, name, c, mat)


def hanging(starts, seed, length=(0.8, 4.0), leafy=True):
    """Lianas que cuelgan: de cada punto de inicio cae un tallo con hojas."""
    r = rng(seed)
    stems, leaves = [], []
    for s in starts:
        L = r.uniform(*length)
        n = max(6, int(L / 0.08))
        p = Vector(s)
        d = Vector((r.normal(0, 0.15), r.normal(0, 0.15), -1)).normalized()
        pts = [p.copy()]
        for i in range(n):
            d = (d + Vector(r.normal(0, 0.05, 3)) + Vector((0, 0, -0.08))).normalized()
            p = p + d * (L / n)
            pts.append(p.copy())
            if leafy and r.random() < 0.85:
                nrm = Vector((r.normal(), r.normal(), r.normal(0, 0.3))).normalized()
                ld = (Vector((r.normal(), r.normal(), -0.8))).normalized()
                leaves.append((p.copy(), nrm, ld, r.uniform(0.04, 0.08)))
        stems.append(pts)
    return stems, leaves


# ------------------------------------------------------------------ raíces y goteo
DROP_ROOT_TIP = None


def roots(c, mat, seed=4):
    """Raíces finas que atraviesan la bóveda y cuelgan (una de ellas gotea en el charco)."""
    global DROP_ROOT_TIP
    from . import tunel
    r = rng(seed)
    stems = []
    spots = []
    for k in range(70):
        y = r.uniform(cfg.Y0 + 5, cfg.Y1 - 8)
        x = r.uniform(-3.6, 3.6)
        spots.append((x, y))
    # raíz principal sobre el charco del primer plano
    px, py, pz = tunel.PUDDLE_DROP
    tip_z = pz + 2.15
    for (x, y) in spots + [(px + 0.05, py + 0.02)]:
        hero = (x, y) == (px + 0.05, py + 0.02)
        ztop = cfg.vault_z(x) + 0.05
        n_strands = 1 if hero else int(r.integers(1, 6))
        for s in range(n_strands):
            L = (ztop - tip_z) if hero else r.uniform(0.3, 2.8) * (1.5 if s == 0 else 0.7)
            n = max(8, int(L / 0.05))
            p = Vector((x + r.normal(0, 0.05), y + r.normal(0, 0.05), ztop))
            d = Vector((0, 0, -1))
            pts = []
            for i in range(n + 1):
                t = i / n
                pts.append((p.copy(), (0.016 if hero else r.uniform(0.004, 0.012)) * (1 - 0.8 * t)))
                d = (d + Vector(r.normal(0, 0.08, 3)) * (0.3 if hero else 1.0) + Vector((0, 0, -0.1))).normalized()
                if hero:
                    # que acabe justo encima del punto de la gota
                    goal = Vector((px, py, tip_z))
                    rem = (goal - p)
                    if rem.length > 1e-3:
                        d = (d * 0.4 + rem.normalized() * 0.6).normalized()
                p = p + d * (L / n)
            if hero:
                DROP_ROOT_TIP = (px, py, tip_z)
            stems.append(pts)
    cu = bpy.data.curves.new('Raices', 'CURVE')
    cu.dimensions = '3D'
    cu.bevel_depth = 1.0
    cu.bevel_resolution = 2
    cu.resolution_u = 2
    for pts in stems:
        sp = cu.splines.new('POLY')
        sp.points.add(len(pts) - 1)
        for k, (p, rad) in enumerate(pts):
            sp.points[k].co = (p.x, p.y, p.z, 1)
            sp.points[k].radius = rad
    ob = bpy.data.objects.new('Raices', cu)
    c.objects.link(ob)
    cu.materials.append(mat)
    return ob


def drop_and_ripples(c, water_mat):
    """La gota que cae de la raíz al charco (fotogramas definidos en camaras.DROPS) y sus ondas."""
    from . import camaras
    px, py, tip_z = DROP_ROOT_TIP
    from . import tunel
    water_z = tunel.PUDDLE_DROP[2]
    # gota: se forma (crece) en la punta, cae con gravedad y desaparece al tocar el agua
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=16, radius=0.012)
    for v in bm.verts:
        if v.co.z > 0:
            v.co.z *= 1.45     # forma de lágrima
    drop = bm_obj(bm, 'Gota', c, None, smooth=True)
    m, nb = M.new_material('Agua gota')
    if nb:
        g = nb.n('ShaderNodeBsdfGlass', {'Color': (0.95, 0.97, 1.0), 'Roughness': 0.0, 'IOR': 1.33})
        M.output(nb, nb.out(g))
    drop.data.materials.append(m)
    fps = cfg.FPS
    hidden = (0.0, 0.0, 0.0)
    drop.scale = hidden
    drop.keyframe_insert('scale', frame=1)
    for f0 in camaras.DROPS:
        grow = int(1.2 * fps)
        fall = math.sqrt(2 * (tip_z - water_z) / 9.81) * fps
        drop.location = (px, py, tip_z - 0.012)
        drop.scale = hidden
        drop.keyframe_insert('scale', frame=f0 - grow - 1)
        drop.keyframe_insert('location', frame=f0 - grow - 1)
        drop.scale = (1, 1, 1)
        drop.keyframe_insert('scale', frame=f0)
        drop.location = (px, py, tip_z - 0.02)
        drop.keyframe_insert('location', frame=f0)
        # caída: fotograma a fotograma (parábola)
        for k in range(1, int(fall) + 2):
            t = min(k / fps, math.sqrt(2 * (tip_z - water_z) / 9.81))
            drop.location = (px, py, tip_z - 0.02 - 0.5 * 9.81 * t * t)
            drop.scale = (0.85, 0.85, 1.25)
            drop.keyframe_insert('location', frame=f0 + k)
            drop.keyframe_insert('scale', frame=f0 + k)
        drop.scale = hidden
        drop.keyframe_insert('scale', frame=f0 + int(fall) + 2)
    if drop.animation_data and drop.animation_data.action:
        try:
            for fc in drop.animation_data.action.fcurves:
                for kp in fc.keyframe_points:
                    kp.interpolation = 'LINEAR'
        except AttributeError:
            pass
    # ondas: disco subdividido con desplazamiento animado por nodos de geometría
    bm = bmesh.new()
    bmesh.ops.create_circle(bm, cap_ends=True, segments=128, radius=0.42)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=0)
    ripple = bm_obj(bm, 'Ondas charco', c, water_mat)
    ripple.location = (px, py, water_z + 0.003)
    ripple.scale = (1.0, 0.42, 1)
    sub = ripple.modifiers.new('sub', 'SUBSURF')
    sub.subdivision_type = 'SIMPLE'
    sub.levels = sub.render_levels = 5
    ng = bpy.data.node_groups.new('Ondas', 'GeometryNodeTree')
    ng.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    nb = NB(ng)
    gin = nb.n('NodeGroupInput')
    gout = nb.n('NodeGroupOutput')
    st = nb.n('GeometryNodeInputSceneTime')
    pos = nb.n('GeometryNodeInputPosition')
    sep = nb.separate(nb.out(pos))
    rr = nb.math('SQRT', nb.math('ADD', nb.math('POWER', nb.out(sep, 'X'), 2.0),
                                  nb.math('POWER', nb.math('MULTIPLY', nb.out(sep, 'Y'), 0.42), 2.0)))
    total = 0.0
    for f0 in camaras.DROPS:
        fall = math.sqrt(2 * (tip_z - water_z) / 9.81) * fps
        t_hit = (f0 + fall) / fps
        tt = nb.math('SUBTRACT', nb.out(st, 'Seconds'), t_hit)
        active = nb.math('GREATER_THAN', tt, 0.0)
        front = nb.math('MULTIPLY', tt, 0.23)                       # velocidad de la onda (m/s)
        ph = nb.math('MULTIPLY', nb.math('SUBTRACT', rr, front), 95.0)
        env = nb.math('MULTIPLY', nb.math('EXPONENT', nb.math('MULTIPLY', nb.math('POWER', nb.math('SUBTRACT', rr, front), 2.0), -900.0)),
                      nb.math('EXPONENT', nb.math('MULTIPLY', tt, -1.4)))
        h = nb.math('MULTIPLY', nb.math('MULTIPLY', nb.math('COSINE', ph), env), nb.math('MULTIPLY', active, 0.0022))
        total = h if total == 0.0 else nb.math('ADD', total, h)
    sp_ = nb.n('GeometryNodeSetPosition')
    nb.set(sp_.inputs['Geometry'], nb.out(gin, 0))
    nb.set(sp_.inputs['Offset'], nb.combine(0.0, 0.0, total))
    nb.set(gout.inputs[0], nb.out(sp_))
    mod = ripple.modifiers.new('ondas', 'NODES')
    mod.node_group = ng
    return drop, ripple


# ------------------------------------------------------------------ polvo y hojas que caen
def dust(c, n=9000, seed=8):
    r = rng(seed)
    verts = []
    for i in range(n):
        y = r.uniform(cfg.Y0 + 10, cfg.Y1 + 3)
        verts.append((r.uniform(-4.2, 4.2), y, r.uniform(0.2, cfg.vault_z(0) - 0.4)))
    ob = mesh_obj('Polvo', verts, [], c)
    ng = bpy.data.node_groups.new('Polvo', 'GeometryNodeTree')
    ng.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    nb = NB(ng)
    gin = nb.n('NodeGroupInput')
    gout = nb.n('NodeGroupOutput')
    st = nb.n('GeometryNodeInputSceneTime')
    pos = nb.n('GeometryNodeInputPosition')
    nz = nb.n('ShaderNodeTexNoise', noise_dimensions='4D')
    nb.set(nz.inputs['Vector'], nb.vmath('SCALE', nb.out(pos), scale=0.6))
    nb.set(nz.inputs['W'], nb.math('MULTIPLY', nb.out(st, 'Seconds'), 0.06))
    nz.inputs['Scale'].default_value = 1.2
    nz.inputs['Detail'].default_value = 1.0
    off = nb.vmath('SCALE', nb.vmath('SUBTRACT', nb.out(nz, 'Color'), (0.5, 0.5, 0.5)), scale=1.6)
    drift = nb.vmath('SCALE', (0.0, -0.08, -0.025), scale=nb.out(st, 'Seconds'))   # corriente de aire hacia dentro
    sp_ = nb.n('GeometryNodeSetPosition')
    nb.set(sp_.inputs['Geometry'], nb.out(gin, 0))
    nb.set(sp_.inputs['Offset'], nb.vmath('ADD', off, drift))
    ico = nb.n('GeometryNodeMeshIcoSphere', {'Radius': 1.0, 'Subdivisions': 1})
    rsc = nb.n('FunctionNodeRandomValue', data_type='FLOAT')
    NB._sock(rsc.inputs, 'Min_001').default_value = 0.0012
    NB._sock(rsc.inputs, 'Max_001').default_value = 0.0045
    iop = nb.n('GeometryNodeInstanceOnPoints')
    nb.set(iop.inputs['Points'], nb.out(sp_))
    nb.set(iop.inputs['Instance'], nb.out(ico, 'Mesh'))
    nb.set(iop.inputs['Scale'], nb.out(rsc, 0))
    sm = nb.n('GeometryNodeSetMaterial')
    nb.set(sm.inputs['Geometry'], nb.out(iop))
    sm.inputs['Material'].default_value = M.mat_polvo()
    nb.set(gout.inputs[0], nb.out(sm))
    ob.modifiers.new('polvo', 'NODES').node_group = ng
    return ob


def falling_leaves(c, center, leaf_obj, n=90, height=11.0, seed=9):
    """Hojas que caen despacio por el gran hundimiento, girando (bucle sin saltos visibles)."""
    r = rng(seed)
    verts = [(center[0] + r.uniform(-2.3, 2.3), center[1] + r.uniform(-7, 7), r.uniform(0, 1)) for _ in range(n)]
    ob = mesh_obj('Hojas cayendo', verts, [], c)
    ng = bpy.data.node_groups.new('Hojas cayendo', 'GeometryNodeTree')
    ng.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    nb = NB(ng)
    gin = nb.n('NodeGroupInput')
    gout = nb.n('NodeGroupOutput')
    st = nb.n('GeometryNodeInputSceneTime')
    pos = nb.n('GeometryNodeInputPosition')
    sep = nb.separate(nb.out(pos))
    phase = nb.out(sep, 'Z')
    sec = nb.out(st, 'Seconds')
    speed = 0.55
    # z = top - fract(phase + t*speed/height) * height
    fr = nb.math('FRACT', nb.math('ADD', phase, nb.math('MULTIPLY', sec, speed / height)))
    z = nb.math('SUBTRACT', 13.0, nb.math('MULTIPLY', fr, height + 0.3))
    sway_x = nb.math('MULTIPLY', nb.math('SINE', nb.math('ADD', nb.math('MULTIPLY', sec, 1.3), nb.math('MULTIPLY', phase, 40))), 0.35)
    sway_y = nb.math('MULTIPLY', nb.math('COSINE', nb.math('ADD', nb.math('MULTIPLY', sec, 0.9), nb.math('MULTIPLY', phase, 23))), 0.25)
    newp = nb.combine(nb.math('ADD', nb.out(sep, 'X'), sway_x), nb.math('ADD', nb.out(sep, 'Y'), sway_y), z)
    sp_ = nb.n('GeometryNodeSetPosition')
    nb.set(sp_.inputs['Geometry'], nb.out(gin, 0))
    nb.set(sp_.inputs['Position'], newp)
    oi = nb.n('GeometryNodeObjectInfo')
    oi.inputs['Object'].default_value = leaf_obj
    oi.inputs['As Instance'].default_value = True
    rot = nb.combine(nb.math('MULTIPLY', sec, 2.1), nb.math('MULTIPLY', nb.math('ADD', sec, nb.math('MULTIPLY', phase, 10)), 1.4),
                     nb.math('MULTIPLY', phase, 30))
    e2r = nb.n('FunctionNodeEulerToRotation', {'Euler': rot})
    iop = nb.n('GeometryNodeInstanceOnPoints')
    nb.set(iop.inputs['Points'], nb.out(sp_))
    nb.set(iop.inputs['Instance'], nb.out(oi, 'Geometry'))
    nb.set(iop.inputs['Rotation'], nb.out(e2r))
    # solo por encima del suelo
    nb.set(iop.inputs['Selection'], nb.math('GREATER_THAN', z, 0.3))
    nb.set(gout.inputs[0], nb.out(iop))
    ob.modifiers.new('hojas', 'NODES').node_group = ng
    return ob


# ------------------------------------------------------------------ árbol de la cabina
def hero_tree(c, bark, leaf):
    from . import tunel
    tx, ty = cfg.TREE_POS
    base = Vector((tx, ty, 1.88))
    skel, tips = P.tree_skeleton(77, base, 12.5, 0.27, lean=(0.03, 0.12), crown_start=0.62, branches=8, depth=3,
                                 up_bias=0.9)
    # que ninguna rama se meta en la bóveda: se recortan las que quedan por debajo de la clave y fuera del hueco
    hole = [h for h in tunel.HOLES if h[0].endswith('2')][0][1]
    clean = []
    for pts in skel:
        keep = []
        for p, rad in pts:
            inside_tunnel = abs(p.x) < cfg.HALF_W + cfg.THICK and p.z < cfg.CROWN + cfg.THICK + 0.3
            if inside_tunnel and p.z > cfg.vault_z(p.x) - 0.3 and not tunel.point_in_poly(p.x, p.y, hole):
                break
            keep.append((p, rad))
        if len(keep) > 2:
            clean.append(keep)
    tips = [(p, d) for p, d in tips if p.z > cfg.CROWN + 1.5]
    trunk = P.branches_to_curve('Arbol cabina', clean, c, bark)
    lv = P.leaves_at('Arbol cabina hojas', tips, c, leaf, per_tip=(70, 110), spread=0.75, size=(0.07, 0.12), seed=5)
    # raíces que bajan por los costados de la locomotora hasta el suelo
    r = rng(12)
    rts = []
    for k in range(9):
        a = 2 * math.pi * k / 9 + r.uniform(-0.2, 0.2)
        p = base.copy()
        pts = [(p.copy(), 0.13)]
        d = Vector((math.cos(a), math.sin(a), -0.05))
        # por el suelo de la cabina hasta el borde
        while abs(p.x) < 1.42 and abs(p.y - cfg.CAB_Y) < 1.0:
            p = p + d * 0.12 + Vector((0, 0, -0.001))
            p.z = max(p.z, 1.9)
            pts.append((p.copy(), 0.11 * max(0.3, 1 - len(pts) * 0.04)))
        # y luego cayendo hasta el balasto
        while p.z > 0.25:
            d = (d * 0.3 + Vector((0, 0, -1))).normalized()
            p = p + d * 0.12 + Vector((r.normal(0, 0.02), r.normal(0, 0.02), 0))
            pts.append((p.copy(), max(0.02, pts[-1][1] * 0.985)))
        # un poco por el suelo
        for i in range(8):
            p = p + Vector((math.cos(a), math.sin(a), 0)) * 0.12
            p.z = 0.25
            pts.append((p.copy(), max(0.012, pts[-1][1] * 0.93)))
        rts.append(pts)
    P.branches_to_curve('Raices arbol', rts, c, bark)
    return trunk, lv


# ------------------------------------------------------------------ montaje
def build(main, ctx):
    from . import tunel
    c = coll('Vegetacion', main)
    leaf_ivy = M.mat_hoja('Hoja hiedra', base=(0.025, 0.06, 0.012), var=(0.015, 0.03, 0.01), autumn=0.06)
    leaf_tree = M.mat_hoja('Hoja arbol', base=(0.04, 0.085, 0.02), autumn=0.15)
    bark = M.mat_generic('Corteza', 'corteza', 1.2, box=True, moss=0.4)
    root_m = M.mat_generic('Raiz', 'corteza', 3.0, box=True, tint=(0.75, 0.6, 0.5))

    libs = {
        'helecho': P.library('helecho', P.fern),
        'hierba': P.library('hierba', P.grass),
        'arbusto': P.library('arbusto', P.shrub),
        'maleza': P.library('maleza', P.grass),
        'rocas': P.library('rocas', P.rock),
    }

    def obj(name):
        return bpy.data.objects.get(name)

    # densidad según la luz en el suelo del túnel, el balasto, los escombros y el terreno de encima
    floor_like = [o for o in bpy.data.objects if o.type == 'MESH' and (
        o.name.startswith('Suelo tunel') or o.name.startswith('Balasto') or o.name.startswith('Escombros'))]
    for o in floor_like:
        k = 0.45 if o.name.startswith('Balasto') else 1.0
        set_density(o, lambda x, y, z, k=k: light_amount(x, y, z) * k)
    top = obj('Terreno sobre el tunel')
    if top:
        set_density(top, lambda x, y, z: 0.5 + 0.5 * max(0, noise.fractal(Vector((x * 0.1, y * 0.1, 9)), 0.6, 2, 3) + 0.4))
    cl = obj('Acantilado')
    if cl:
        # en el acantilado solo en repisas (normales hacia arriba) — se aproxima con ruido y altura
        me = cl.data
        vals = []
        for v in me.vertices:
            p = cl.matrix_world @ v.co
            n = v.normal
            vals.append(max(0.0, (n.z - 0.25) * 2.0) * (1.0 if p.z > -60 else 0.3))
        at = me.attributes.new('dens', 'FLOAT', 'POINT')
        at.data.foreach_set('value', np.array(vals, dtype=np.float32))

    seed = 10
    for o in floor_like:
        big = o.name.startswith('Suelo') or o.name.startswith('Escombros')
        scatter('Hierba ' + o.name, o, libs['hierba'], 12.0 if big else 5.0, c, scale=(0.5, 1.1), seed=seed); seed += 7
        scatter('Helechos ' + o.name, o, libs['helecho'], 1.1 if big else 0.25, c, scale=(0.5, 1.2), seed=seed); seed += 7
        scatter('Maleza ' + o.name, o, libs['maleza'], 1.4, c, scale=(0.6, 1.1), seed=seed); seed += 7
        if big:
            scatter('Arbustos ' + o.name, o, libs['arbusto'], 0.08, c, scale=(0.4, 0.9), seed=seed); seed += 7
            scatter('Piedras ' + o.name, o, libs['rocas'], 0.25, c, scale=(0.08, 0.3), seed=seed, sway=0, tilt=0.5); seed += 7
    if top:
        scatter('Hierba monte', top, libs['hierba'], 4.0, c, scale=(0.7, 1.3), seed=101)
        scatter('Arbustos monte', top, libs['arbusto'], 0.35, c, scale=(0.6, 1.4), seed=102)
        scatter('Helechos monte', top, libs['helecho'], 0.7, c, scale=(0.8, 1.4), seed=103)
        scatter('Maleza monte', top, libs['maleza'], 1.5, c, scale=(0.7, 1.2), seed=104)
    if cl:
        scatter('Hierba acantilado', cl, libs['hierba'], 0.25, c, scale=(0.8, 1.5), seed=111, align=True, tilt=0.3)
        scatter('Arbustos acantilado', cl, libs['arbusto'], 0.02, c, scale=(0.8, 1.8), seed=112, align=True, tilt=0.3)

    # vegetación sobre la locomotora: musgo/hierba en las superficies de arriba y helechos en el ténder
    loco = ctx.get('loco')
    if loco:
        for i, o in enumerate(loco['top']):
            me = o.data
            at = me.attributes.get('dens') or me.attributes.new('dens', 'FLOAT', 'POINT')
            at.data.foreach_set('value', np.ones(len(me.vertices), dtype=np.float32))
            soil = o.name.startswith('Tender tierra')
            scatter('Hierba loco %d' % i, o, libs['hierba'], 14.0 if soil else 3.0, c, scale=(0.3, 0.7), seed=200 + i)
            if soil:
                scatter('Helechos tender', o, libs['helecho'], 2.0, c, scale=(0.6, 1.1), seed=300)
                scatter('Arbustos tender', o, libs['arbusto'], 0.4, c, scale=(0.4, 0.8), seed=301)

        # hiedra trepando por la locomotora
        loco_objs = [o for o in bpy.data.collections['Locomotora'].all_objects if o.type in ('MESH', 'CURVE')]
        bvh = bvh_of(loco_objs)
        r = rng(41)
        stems, leaves = [], []
        for k in range(26):
            side = r.choice([-1, 1])
            y = r.uniform(cfg.LOCO_FRONT - 17, cfg.LOCO_FRONT - 0.5)
            s, l = ivy(bvh, (side * 1.5, y, r.uniform(0.6, 1.4)), int(r.integers(30, 90)), 1000 + k, up=0.75,
                       step=0.06, branch_p=0.06)
            stems += s
            leaves += l
        # cascada de hiedra sobre la caldera desde el árbol
        for k in range(10):
            s, l = ivy(bvh, (r.uniform(-0.4, 0.4), cfg.CAB_Y + 1.6 + r.uniform(0, 4), 3.5), int(r.integers(40, 80)),
                       2000 + k, up=-0.2, gravity=0.7, step=0.06, branch_p=0.05)
            stems += s
            leaves += l
        stems_curve('Hiedra loco tallos', stems, c, bark, 0.006)
        leaves_mesh('Hiedra loco hojas', leaves, c, leaf_ivy)
        print('  hiedra en la locomotora: %d tallos, %d hojas' % (len(stems), len(leaves)))

    # hiedra y lianas en la bóveda: cuelgan de los bordes de los hundimientos y de la boca
    tun = [o for o in bpy.data.objects if o.name in ('Tunel',)]
    bvh_t = bvh_of(tun + [o for o in bpy.data.objects if o.name.startswith('Dovela') or o.name.startswith('Acantilado')])
    r = rng(51)
    stems, leaves, hstarts = [], [], []
    for name, pts, (hx, hy) in tunel.HOLES:
        for k in range(0, len(pts), 2):
            x, y = pts[k]
            z = cfg.vault_z(x) + 0.05
            inward = Vector((hx - x, hy - y, 0)).normalized() * -0.12
            p = Vector((x, y, z)) + inward
            if r.random() < 0.55:
                hstarts.append(p + Vector((0, 0, -0.1)))
            s, l = ivy(bvh_t, p, int(r.integers(25, 70)), 3000 + k + int(hy * 10), up=-0.3, gravity=0.8, step=0.07,
                       branch_p=0.05)
            stems += s
            leaves += l
    # boca del túnel: cortina de lianas y hiedra bajando por la piedra
    for k in range(40):
        a = math.pi * r.uniform(0.08, 0.92)
        rr = cfg.R_ARCH + r.uniform(0.05, 1.0)
        p = Vector((rr * math.cos(a), cfg.Y1 - r.uniform(0.0, 1.2), cfg.WALL_H + rr * math.sin(a)))
        if r.random() < 0.6:
            hstarts.append(p + Vector((0, 0, -0.05)))
        s, l = ivy(bvh_t, p + Vector((0, 0.6, 0.5)), int(r.integers(30, 80)), 4000 + k, up=-0.2, gravity=0.8, step=0.07)
        stems += s
        leaves += l
    hs, hl = hanging(hstarts, 61, length=(0.6, 4.2))
    stems_curve('Hiedra boveda tallos', stems + hs, c, bark, 0.006)
    leaves_mesh('Hiedra boveda hojas', leaves + hl, c, leaf_ivy)
    print('  hiedra y lianas en la bóveda: %d tallos, %d hojas' % (len(stems) + len(hs), len(leaves) + len(hl)))

    roots(c, root_m)
    hero_tree(c, bark, leaf_tree)
    from . import tunel as T
    water = bpy.data.materials.get('Agua charco') or M.mat_agua()
    drop_and_ripples(c, water)
    dust(c)
    # una hoja suelta como modelo para las que caen
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new('UVMap')
    P.leaf_quad(bm, Vector((0, -0.04, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)), 0.09, 0.05, uv, bend=0.1, segs=2)
    hc = hidden_coll('LIB hoja suelta')
    leaf_obj = bm_obj(bm, 'Hoja suelta', hc, leaf_tree)
    big = [h for h in tunel.HOLES if h[0].endswith('2')][0]
    falling_leaves(c, big[2], leaf_obj)
    return {}
