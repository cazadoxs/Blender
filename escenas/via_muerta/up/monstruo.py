"""El monstruo: una locomotora vieja y oxidada, de caldera negra y roja, que camina sobre ocho
patas larguísimas de araña. En el frente, donde iría la puerta de la caja de humos, tiene una
cara de piel gris y tirante con una sonrisa enorme llena de dientes largos y unos ojos hundidos
en los que brilla el fuego de la caldera (también le asoma entre los dientes).

En reposo mira hacia +Y con el lomo hacia +Z. Las piezas son rígidas (como un artrópodo):
cuelgan de los huesos del esqueleto; las patas tienen cinemática inversa."""
import bpy, bmesh, math
import numpy as np
from mathutils import Vector, Matrix, Quaternion, Euler, noise
from . import cfg
from .util import coll, box, cyl, bm_obj, bevel, rng, join, NB, apply_mods, mesh_obj
from . import materiales as M
from .personaje import ring, loft, limb, resample, prof, unify

BOILER_R = 0.8
Y_BACK, Y_FRONT = -2.5, 1.65
FACE_Y = 2.12
# patas: (lado, y del enganche)
LEGS = []
for k, ya in enumerate((1.2, 0.4, -0.5, -1.35)):
    for s in (1, -1):
        LEGS.append(('%s%d' % ('L' if s > 0 else 'R', k + 1), s, ya))
GROUP_A = {'L1', 'R2', 'L3', 'R4'}
R = {}


# ------------------------------------------------------------------ materiales
def mat_chapa():
    return M.mat_metal_loco('Monstruo chapa', paint=(0.11, 0.012, 0.008))


def mat_piel():
    m, nb = M.new_material('Monstruo piel')
    if nb is None:
        return m
    tc = nb.n('ShaderNodeTexCoord')
    obj = nb.out(tc, 'Object')
    n1 = nb.out(nb.noise(obj, scale=3.0, detail=8, rough=0.62), 'Factor')
    n2 = nb.out(nb.noise(obj, scale=28.0, detail=6, rough=0.7), 'Factor')
    vo = nb.n('ShaderNodeTexVoronoi', {'Vector': obj, 'Scale': 7.0}, feature='DISTANCE_TO_EDGE')
    crack = nb.maprange(nb.out(vo, 'Distance'), 0.0, 0.025)
    veins_n = nb.out(nb.noise(obj, scale=5.0, detail=4, rough=0.5, dist=0.9), 'Factor')
    vein = nb.maprange(nb.math('ABSOLUTE', nb.math('SUBTRACT', veins_n, 0.5)), 0.0, 0.025)
    col = nb.mix(nb.maprange(n1, 0.3, 0.7), (0.30, 0.28, 0.26), (0.44, 0.41, 0.37))
    col = nb.mix(nb.math('MULTIPLY', nb.math('SUBTRACT', 1.0, vein), 0.55), col, (0.16, 0.06, 0.08))
    col = nb.mix(nb.math('MULTIPLY', nb.math('SUBTRACT', 1.0, crack), 0.8), col, (0.06, 0.015, 0.012))
    # hollín y óxido que chorrean desde la caja de humos
    z = nb.out(nb.separate(obj), 'Z')
    soot = nb.math('MULTIPLY', nb.maprange(nb.math('ADD', z, nb.math('MULTIPLY', n1, 0.4)), 0.35, 0.9), 0.85)
    col = nb.mix(soot, col, (0.03, 0.025, 0.022))
    # hollín en el borde de la cara (donde se junta con la caja de humos) y en las cuencas
    sp = nb.separate(obj)
    rr = nb.math('SQRT', nb.math('ADD', nb.math('POWER', nb.out(sp, 'X'), 2.0), nb.math('POWER', z, 2.0)))
    edge = nb.maprange(nb.math('ADD', rr, nb.math('MULTIPLY', nb.math('SUBTRACT', n1, 0.5), 0.3)), 0.62, 0.86)
    col = nb.mix(nb.math('MULTIPLY', edge, 0.9), col, (0.025, 0.018, 0.015))
    h = nb.math('ADD', nb.math('MULTIPLY', n2, 0.5), nb.math('MULTIPLY', crack, 0.5))
    b = nb.n('ShaderNodeBump', {'Height': h, 'Strength': 0.5, 'Distance': 0.01})
    p = M.principled(nb, col, nb.maprange(n2, 0.3, 0.7, 0.32, 0.55), nb.out(b), Subsurface_Weight=0.25,
                     Subsurface_Radius=(1.0, 0.3, 0.25), Subsurface_Scale=0.03, Coat_Weight=0.35, Coat_Roughness=0.2)
    M.output(nb, nb.out(p), None, m)
    return m


def mat_dientes():
    m, nb = M.new_material('Monstruo dientes')
    if nb is None:
        return m
    tc = nb.n('ShaderNodeTexCoord')
    n = nb.out(nb.noise(nb.out(tc, 'Object'), scale=40, detail=5), 'Factor')
    col = nb.mix(nb.maprange(n, 0.3, 0.75), (0.55, 0.47, 0.32), (0.32, 0.25, 0.14))
    p = M.principled(nb, col, 0.32, None, Subsurface_Weight=0.3, Subsurface_Radius=(1.0, 0.8, 0.5), Subsurface_Scale=0.01,
                     Coat_Weight=0.5, Coat_Roughness=0.1)
    M.output(nb, nb.out(p), None, m)
    return m


def mat_patas():
    m, nb = M.new_material('Monstruo patas')
    if nb is None:
        return m
    tc = nb.n('ShaderNodeTexCoord')
    obj = nb.out(tc, 'Object')
    n1 = nb.out(nb.noise(obj, scale=4.0, detail=6, rough=0.6), 'Factor')
    n2 = nb.out(nb.noise(obj, scale=60.0, detail=4, rough=0.7), 'Factor')
    col = nb.mix(nb.maprange(n1, 0.45, 0.75), (0.008, 0.006, 0.006), (0.05, 0.008, 0.006))
    st = nb.out(nb.n('ShaderNodeMapping', {'Vector': obj, 'Scale': (60, 60, 3)}))
    hair = nb.out(nb.noise(st, scale=4.0, detail=2, rough=0.5), 'Factor')
    h = nb.math('ADD', nb.math('MULTIPLY', n2, 0.4), nb.math('MULTIPLY', hair, 0.6))
    b = nb.n('ShaderNodeBump', {'Height': h, 'Strength': 0.35, 'Distance': 0.008})
    p = M.principled(nb, col, nb.maprange(hair, 0.3, 0.7, 0.28, 0.6), nb.out(b), Coat_Weight=0.8, Coat_Roughness=0.12,
                     Specular_IOR_Level=0.6)
    M.output(nb, nb.out(p), None, m)
    return m


def mat_brasa(name='Monstruo brasa', color=(1.0, 0.32, 0.05), strength=30.0):
    """Emisión de brasa; la intensidad la lleva el alfa del color del objeto (animable)."""
    m, nb = M.new_material(name)
    if nb is None:
        return m
    tc = nb.n('ShaderNodeTexCoord')
    n = nb.out(nb.noise(nb.out(tc, 'Object'), scale=18, detail=6, rough=0.6), 'Factor')
    oi = nb.n('ShaderNodeObjectInfo')
    col = nb.out(nb.ramp(n, [(0.3, (0.5, 0.02, 0.0)), (0.6, color), (0.8, (1.0, 0.7, 0.3))]))
    em = nb.n('ShaderNodeEmission', {'Color': col, 'Strength': nb.math('MULTIPLY', nb.out(oi, 'Alpha'), strength)})
    M.output(nb, nb.out(em))
    return m


def mat_ojo():
    """Ojo: esfera que brilla como una brasa, con la pupila rasgada negra y brillo húmedo."""
    m, nb = M.new_material('Monstruo ojo')
    if nb is None:
        return m
    tc = nb.n('ShaderNodeTexCoord')
    sep = nb.separate(nb.out(tc, 'Object'))
    fy = nb.out(sep, 'Y')
    slit = nb.math('MULTIPLY', nb.math('LESS_THAN', nb.math('ABSOLUTE', nb.out(sep, 'X')), 0.012),
                   nb.math('GREATER_THAN', fy, 0.04))
    oi = nb.n('ShaderNodeObjectInfo')
    d = nb.math('SQRT', nb.math('ADD', nb.math('POWER', nb.out(sep, 'X'), 2.0), nb.math('POWER', nb.out(sep, 'Z'), 2.0)))
    col = nb.out(nb.ramp(nb.maprange(d, 0.0, 0.065), [(0.0, (1.0, 0.75, 0.25)), (0.5, (1.0, 0.25, 0.03)),
                                                          (1.0, (0.3, 0.01, 0.0))]))
    em = nb.n('ShaderNodeEmission', {'Color': col, 'Strength': nb.math('MULTIPLY', nb.math('MULTIPLY', nb.out(oi, 'Alpha'), 45.0),
                                                                        nb.math('SUBTRACT', 1.0, slit))})
    gl = M.principled(nb, (0.0, 0.0, 0.0), 0.02, None, Coat_Weight=1.0)
    add = nb.n('ShaderNodeAddShader', {0: nb.out(em), 1: nb.out(gl)})
    M.output(nb, nb.out(add))
    return m


# ------------------------------------------------------------------ cuerpo
def body(c, mats):
    chapa, soot, rust = mats['chapa'], mats['hollin'], mats['oxido']
    obs = []
    bo = cyl('Monstruo caldera', c, BOILER_R, Y_FRONT - Y_BACK, (0, (Y_FRONT + Y_BACK) / 2, 0), chapa,
             rot=(math.pi / 2, 0, 0), seg=72)
    obs.append(bo)
    # abolladuras y chapas reventadas: un desplazamiento con ruido sobre la caldera
    for k, y in enumerate(np.linspace(Y_BACK + 0.3, Y_FRONT - 0.2, 6)):
        obs.append(cyl('Monstruo aro', c, BOILER_R + 0.025, 0.07, (0, y, 0), rust, rot=(math.pi / 2, 0, 0), seg=72))
        for j in range(28):
            a = 2 * math.pi * j / 28
            obs.append(cyl('Remache', c, 0.016, 0.03, (math.cos(a) * (BOILER_R + 0.05), y + 0.04, math.sin(a) * (BOILER_R + 0.05)),
                           rust, rot=(math.pi / 2, 0, 0), seg=6))
    # caja de humos (más ancha) que enmarca la cara
    sb = cyl('Monstruo caja humos', c, BOILER_R + 0.12, 0.5, (0, Y_FRONT + 0.25, 0.02), soot, rot=(math.pi / 2, 0, 0), seg=72)
    obs.append(sb)
    rim = cyl('Monstruo borde cara', c, BOILER_R + 0.17, 0.08, (0, Y_FRONT + 0.48, 0.02), rust, rot=(math.pi / 2, 0, 0), seg=72)
    obs.append(rim)
    # chimenea torcida y con el borde roto
    ch = cyl('Monstruo chimenea', c, 0.25, 1.05, (0, Y_FRONT - 0.15, BOILER_R + 0.45), soot, r2=0.21, seg=40)
    ch.rotation_euler = (math.radians(-12), math.radians(4), 0)
    obs.append(ch)
    obs.append(cyl('Monstruo chimenea borde', c, 0.3, 0.12, (0, Y_FRONT - 0.27, BOILER_R + 0.96), soot, seg=40))
    obs[-1].rotation_euler = (math.radians(-12), math.radians(4), 0)
    # domos
    obs.append(cyl('Monstruo domo', c, 0.32, 0.45, (0, 0.1, BOILER_R + 0.15), chapa, seg=48))
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=40, v_segments=14, radius=0.32)
    for v in bm.verts:
        v.co.z = max(0.0, v.co.z) * 0.7
    cap = bm_obj(bm, 'Monstruo domo tapa', c, rust, smooth=True)
    cap.location = (0, 0.1, BOILER_R + 0.37)
    obs.append(cap)
    # cabina trasera hundida, con las ventanas rotas que brillan por dentro
    cab = box('Monstruo cabina', c, (1.95, 1.4, 1.75), (0, Y_BACK + 0.55, 0.35), chapa, bevel=0.03)
    obs.append(cab)
    roof = box('Monstruo techo', c, (2.15, 1.65, 0.07), (0, Y_BACK + 0.5, 1.28), rust, rot=(0.06, 0.08, 0.02))
    obs.append(roof)
    glow_parts = []
    for s in (1, -1):
        w = box('Monstruo ventana', c, (0.03, 0.55, 0.5), (s * 0.985, Y_BACK + 0.6, 0.65), None)
        glow_parts.append(w)
    fw = box('Monstruo ventana trasera', c, (1.2, 0.03, 0.45), (0, Y_BACK - 0.16, 0.7), None)
    glow_parts.append(fw)
    # bastidor, ruedas muertas colgando y quitapiedras
    for s in (1, -1):
        obs.append(box('Monstruo larguero', c, (0.08, Y_FRONT - Y_BACK + 0.4, 0.5), (s * 0.55, (Y_FRONT + Y_BACK) / 2, -0.85), rust))
        for k, y in enumerate((1.0, -0.2, -1.4)):
            wh = cyl('Monstruo rueda', c, 0.52, 0.12, (s * 0.62, y, -1.05 - 0.05 * k), rust,
                     rot=(0.3 * s * (k - 1), math.pi / 2, 0), seg=40)
            hole = cyl('tmp', c, 0.4, 0.4, (s * 0.62, y, -1.05 - 0.05 * k), None, rot=(0.3 * s * (k - 1), math.pi / 2, 0), seg=40)
            m = wh.modifiers.new('hueco', 'BOOLEAN')
            m.object = hole
            m.operation = 'DIFFERENCE'
            apply_mods(wh)
            bpy.data.objects.remove(hole)
            obs.append(wh)
            for j in range(8):
                a = j * math.pi / 4
                obs.append(box('Monstruo radio', c, (0.04, 0.04, 0.8), (s * 0.62, y, -1.05 - 0.05 * k), rust,
                               rot=(a + 0.3 * s * (k - 1), 0, 0)))
    for j in range(7):
        x = -0.75 + j * 0.25
        obs.append(box('Monstruo quitapiedras', c, (0.05, 0.6, 0.06), (x, Y_FRONT + 0.25, -1.05), rust,
                       rot=(math.radians(-35), 0, 0)))
    # tuberías y cadenas que cuelgan
    from .tunel import sweep
    prof_ = [(0.035 * math.cos(2 * math.pi * k / 10), 0.035 * math.sin(2 * math.pi * k / 10)) for k in range(10)]
    r = rng(91)
    for k in range(6):
        s = 1 if k % 2 else -1
        y0 = r.uniform(Y_BACK + 0.3, Y_FRONT - 0.4)
        pts = [(s * 0.7, y0, 0.45), (s * 0.85, y0 + 0.4, 0.1), (s * 0.82, y0 + 0.7, -0.35), (s * 0.6, y0 + 1.0, -0.7)]
        obs.append(sweep('Monstruo tubo', prof_, pts, c, rust))
    # desgarros de la chapa donde nacen las patas (masa negra y blanda)
    flesh = mats['patas']
    for name, s, ya in LEGS:
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=12, radius=0.3)
        for v in bm.verts:
            v.co += Vector((noise.noise(v.co * 6) * 0.05, noise.noise(v.co * 6 + Vector((3, 1, 2))) * 0.05, 0))
        o = bm_obj(bm, 'Monstruo raiz pata', c, flesh, smooth=True)
        o.location = (s * 0.75, ya, -0.1)
        o.scale = (0.9, 1.3, 1.0)
        obs.append(o)
    hull = join(obs, 'Monstruo cuerpo')
    bevel(hull, 0.006, 1)
    glow = join(glow_parts, 'Monstruo ventanas')
    glow.data.materials.append(mats['brasa'])
    return hull, glow


# ------------------------------------------------------------------ cara
EYE = [(0.3, 0.2), (-0.3, 0.2)]
EYE_R = (0.13, 0.085)
MOUTH_W = 0.7


def eye_d(u, v):
    """Distancia normalizada al borde de la cuenca más cercana (<1 dentro del agujero).
    Las cuencas están inclinadas hacia dentro y abajo (mirada malvada)."""
    best = 9.0
    for cu, cv in EYE:
        du, dv = u - cu, v - cv
        a = math.radians(-14) * (1 if cu > 0 else -1)
        x = du * math.cos(a) + dv * math.sin(a)
        y = -du * math.sin(a) + dv * math.cos(a)
        best = min(best, math.sqrt((x / EYE_R[0]) ** 2 + (y / EYE_R[1]) ** 2))
    return best


def face_height(u, v):
    """Relieve de la cara: piel estirada sobre el frente, frente arrugada, cuencas hundidas que acaban
    en agujeros, pómulos marcados y nariz de calavera."""
    e = 1 - (abs(u) / 0.9) ** 2.3 - (abs(v) / 0.93) ** 2.3
    if e <= 0:
        return None
    h = 0.36 * e ** 0.5
    g = lambda cu, cv, r, a: a * math.exp(-((u - cu) ** 2 + (v - cv) ** 2) / (2 * r * r))
    h += g(0, 0.45, 0.25, 0.04) + g(0.3, 0.36, 0.1, 0.06) + g(-0.3, 0.36, 0.1, 0.06)      # frente y cejas
    h += 0.008 * math.sin(v * 70) * math.exp(-((v - 0.55) / 0.12) ** 2)                    # arrugas de la frente
    ed = eye_d(u, v)
    h -= 0.14 * math.exp(-max(0.0, ed - 1.0) ** 2 / 0.35)                                   # cuencas
    h += g(0.46, -0.02, 0.12, 0.07) + g(-0.46, -0.02, 0.12, 0.07)                           # pómulos
    h += g(0, 0.03, 0.06, 0.03) + g(0.035, -0.06, 0.028, -0.07) + g(-0.035, -0.06, 0.028, -0.07)   # nariz
    h += g(0.2, -0.17, 0.1, 0.035) + g(-0.2, -0.17, 0.1, 0.035)                             # carrillos tensos
    h += 0.014 * noise.noise(Vector((u * 9, v * 9, 1.3))) + 0.005 * noise.noise(Vector((u * 40, v * 40, 2.1)))
    # asimetría: un lado algo caído y una grieta honda que baja por la mejilla izquierda
    h -= 0.03 * max(0.0, -u) * max(0.0, 0.3 - v)
    h -= 0.03 * math.exp(-((u - 0.52 - 0.15 * (v - 0.1)) / 0.012) ** 2) * (1.0 if -0.2 < v < 0.45 else 0.0)
    return h


def mouth_curve(u):
    """Línea media de la boca: una sonrisa enorme con las comisuras muy levantadas."""
    return -0.34 + 0.34 * (u / MOUTH_W) ** 2


def mouth_gap(u):
    return 0.12 * max(0.0, 1 - (u / MOUTH_W) ** 2) ** 0.55 + 0.004


def in_mouth(u, v):
    if abs(u) > MOUTH_W:
        return False
    mc = mouth_curve(u)
    g = mouth_gap(u)
    return mc - g < v < mc + g * 0.75


def face(c, mats):
    """Malla de la cara (parte de arriba, con los agujeros de los ojos) y de la mandíbula."""
    N = 170
    us = np.linspace(-0.92, 0.92, N)
    vs = np.linspace(-0.95, 0.95, N)
    parts = {}
    for part in ('cara', 'mandibula'):
        verts, faces = [], []
        idx = {}
        for j, v in enumerate(vs):
            for i, u in enumerate(us):
                h = face_height(u, v)
                if h is None:
                    continue
                idx[(i, j)] = len(verts)
                verts.append((u, FACE_Y + h, v))
        for (i, j), k in idx.items():
            if (i + 1, j) in idx and (i, j + 1) in idx and (i + 1, j + 1) in idx:
                uc, vc = (us[i] + us[i + 1]) / 2, (vs[j] + vs[j + 1]) / 2
                if in_mouth(uc, vc) or eye_d(uc, vc) < 1.0:
                    continue
                if abs(uc) <= MOUTH_W:
                    below = vc < mouth_curve(uc)
                else:
                    below = vc < mouth_curve(MOUTH_W) - 0.9 * (abs(uc) - MOUTH_W)
                if (part == 'mandibula') != below:
                    continue
                faces.append((k, idx[(i + 1, j)], idx[(i + 1, j + 1)], idx[(i, j + 1)]))
        me = mesh_obj('Monstruo ' + part, verts, faces, c, mat=mats['piel'], smooth=True)
        bm = bmesh.new()
        bm.from_mesh(me.data)
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
        bm.to_mesh(me.data)
        bm.free()
        sol = me.modifiers.new('grosor', 'SOLIDIFY')
        sol.thickness = 0.05
        sol.offset = -1
        sub = me.modifiers.new('suave', 'SUBSURF')
        sub.levels = 1
        sub.render_levels = 2
        parts[part] = me
    from .tunel import sweep
    lip_prof = [(0.03 * math.cos(2 * math.pi * k / 12), 0.026 * math.sin(2 * math.pi * k / 12)) for k in range(12)]
    lips = {}
    for part, sign in (('cara', 0.75), ('mandibula', -1.0)):
        pts = []
        for u in np.linspace(-MOUTH_W, MOUTH_W, 90):
            v = mouth_curve(u) + sign * mouth_gap(u)
            h = face_height(u, v) or 0.0
            pts.append((u, FACE_Y + h + 0.008, v))
        lips[part] = sweep('Monstruo labio', lip_prof, pts, c, mats['piel'], closed=True)
    # párpados: un cordón grueso alrededor de cada cuenca
    lids = []
    for cu, cv in EYE:
        pts = []
        a0 = math.radians(-14) * (1 if cu > 0 else -1)
        for k in range(49):
            t = 2 * math.pi * k / 48
            x, y = EYE_R[0] * 1.02 * math.cos(t), EYE_R[1] * 1.05 * math.sin(t)
            u = cu + x * math.cos(a0) - y * math.sin(a0)
            v = cv + x * math.sin(a0) + y * math.cos(a0)
            h = face_height(u, v) or 0.0
            pts.append((u, FACE_Y + h + 0.004, v))
        lids.append(sweep('Monstruo parpado', lip_prof, pts, c, mats['piel'], closed=True))
    # dientes: agujas largas, amarillentas y torcidas, que se cruzan
    teeth = {'cara': [], 'mandibula': []}
    r = rng(66)
    for part, sign, n in (('cara', 0.75, 30), ('mandibula', -1.0, 26)):
        for k in range(n):
            u = -MOUTH_W * 0.96 + 2 * MOUTH_W * 0.96 * (k + r.uniform(-0.3, 0.3)) / (n - 1)
            v = mouth_curve(u) + sign * mouth_gap(u)
            h = face_height(u, v) or 0.0
            L = r.uniform(0.15, 0.34) * (1 - 0.6 * (u / MOUTH_W) ** 2) * (0.85 if part == 'mandibula' else 1.0)
            if r.random() < 0.15:
                L *= 0.4          # alguno roto
            base = Vector((u, FACE_Y + h - 0.012, v + (0.012 if part == 'cara' else -0.012)))
            d = Vector((r.uniform(-0.2, 0.2), r.uniform(-0.15, 0.25), -1.0 if part == 'cara' else 1.0)).normalized()
            bend = Vector((r.uniform(-0.03, 0.03), -0.02, 0.0))
            pts = [base, base + d * L * 0.5 + bend * 0.5, base + d * L + bend]
            bm = bmesh.new()
            limb(bm, pts, [r.uniform(0.016, 0.024), 0.01, 0.001], Vector((1, 0, 0)), n=10)
            teeth[part].append(bm_obj(bm, 'Diente', c, mats['dientes'], smooth=True))
    up_teeth = join(teeth['cara'], 'Monstruo dientes arriba')
    lo_teeth = join(teeth['mandibula'], 'Monstruo dientes abajo')
    # boca y cuencas por dentro: huecos oscuros, con brasas al fondo
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=1.0)
    inner = bm_obj(bm, 'Monstruo garganta', c, mats['garganta'], smooth=True)
    inner.location = (0, FACE_Y - 0.12, -0.28)
    inner.scale = (0.68, 0.32, 0.3)
    sockets = []
    eyes = []
    for cu, cv in EYE:
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=1.0)
        so = bm_obj(bm, 'Monstruo cuenca', c, mats['cuenca'], smooth=True)
        so.location = (cu, FACE_Y + 0.08, cv)
        so.scale = (0.15, 0.14, 0.11)
        sockets.append(so)
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=20, radius=0.034)
        e = bm_obj(bm, 'Monstruo ojo', c, mats['ojo'], smooth=True)
        e.location = (cu * 0.97, FACE_Y + 0.07, cv - 0.015)
        e.color = (1, 1, 1, 0.6)
        eyes.append(e)
    upper = join([parts['cara'], lips['cara'], up_teeth] + lids + sockets, 'Monstruo cara')
    lower = join([parts['mandibula'], lips['mandibula'], lo_teeth], 'Monstruo mandibula')
    return upper, lower, inner, eyes


# ------------------------------------------------------------------ patas
FOOT = {1: (3.55, 3.4), 2: (3.95, 1.35), 3: (3.95, -1.45), 4: (3.6, -3.6)}   # (x, y) de cada punta en reposo


def leg_rest(name, s, ya):
    """Puntos de reposo de una pata (enganche, fin de coxa, rodilla, punta): las delanteras van
    hacia delante y las traseras hacia atrás, como una araña."""
    k = int(name[1])
    fx, fy = FOOT[k]
    A = Vector((s * 0.8, ya, -0.12))
    C = A + Vector((s * 0.45, (fy - ya) * 0.08, 0.16))
    F = Vector((s * fx, fy, -2.25))
    K = C.lerp(F, 0.42) + Vector((s * 0.15, 0, 2.7))
    return A, C, K, F


def leg_mesh(c, mats, name, s, ya):
    A, C, K, F = leg_rest(name, s, ya)
    meshes = {}
    up = Vector((0, 0, 1))
    bm = bmesh.new()
    limb(bm, [A, (A + C) / 2, C], [0.21, 0.19, 0.16], Vector((0, 1, 0)), n=18)
    meshes['coxa'] = bm_obj(bm, 'Pata %s coxa' % name, c, mats['patas'], smooth=True)
    # fémur: grueso, arqueado, con nudos en las articulaciones
    N = 28
    pts = [C.lerp(K, u) + up * 0.22 * math.sin(math.pi * u) for u in np.linspace(0, 1, N)]
    rad = [prof(u, [(0.0, 0.16), (0.07, 0.13), (0.45, 0.115), (0.88, 0.1), (0.96, 0.13), (1.0, 0.12)]) for u in np.linspace(0, 1, N)]
    bm = bmesh.new()
    limb(bm, pts, rad, Vector((0, 1, 0)), n=16)
    spikes(bm, pts, rad, 34, seed=abs(hash(name)) % 1000)
    meshes['femur'] = bm_obj(bm, 'Pata %s femur' % name, c, mats['patas'], smooth=True)
    # tibia y tarso con la uña: larga, con un codo suave hacia fuera
    tar = F + (K - F).normalized() * 0.8
    pts = [K.lerp(tar, u) + Vector((s, 0, 0)) * 0.18 * math.sin(math.pi * u) for u in np.linspace(0, 1, 32)]
    pts += [tar.lerp(F, u) + Vector((s, 0, 0)) * 0.05 * math.sin(math.pi * u) for u in np.linspace(0, 1, 12)[1:]]
    n = len(pts)
    rad = [prof(k / (n - 1), [(0.0, 0.12), (0.05, 0.095), (0.55, 0.075), (0.72, 0.062), (0.74, 0.075), (0.8, 0.06),
                              (0.95, 0.03), (1.0, 0.004)]) for k in range(n)]
    bm = bmesh.new()
    limb(bm, pts, rad, Vector((0, 1, 0)), n=14)
    spikes(bm, pts[:32], rad[:32], 36, seed=(abs(hash(name)) + 7) % 1000)
    meshes['tibia'] = bm_obj(bm, 'Pata %s tibia' % name, c, mats['patas'], smooth=True)
    return meshes, (A, C, K, F)


def spikes(bm, pts, rad, n, seed=0):
    """Púas y pelos rígidos por la pata."""
    r = rng(seed)
    for k in range(n):
        i = int(r.integers(2, len(pts) - 2))
        p = Vector(pts[i])
        t = (Vector(pts[i + 1]) - Vector(pts[i - 1])).normalized()
        side = t.cross(Vector(r.normal(0, 1, 3))).normalized()
        base = p + side * rad[i] * 0.9
        tip = base + (side * 0.8 + t * 0.6).normalized() * r.uniform(0.04, 0.12)
        limb(bm, [base, tip], [rad[i] * 0.18, 0.002], t, n=5)


# ------------------------------------------------------------------ esqueleto
def armature(c, legs):
    ad = bpy.data.armatures.new('Monstruo')
    ob = bpy.data.objects.new('Monstruo', ad)
    c.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    with bpy.context.temp_override(active_object=ob, object=ob, selected_objects=[ob]):
        bpy.ops.object.mode_set(mode='EDIT')
        eb = ad.edit_bones.new('cuerpo')
        eb.head, eb.tail = (0, 0, 0), (0, 1, 0)
        hb = ad.edit_bones.new('cabeza')
        hb.head, hb.tail = (0, Y_FRONT - 0.1, 0.02), (0, FACE_Y + 0.4, 0.02)
        hb.parent = eb
        jb = ad.edit_bones.new('mandibula')
        jb.head, jb.tail = (0, FACE_Y - 0.25, -0.2), (0, FACE_Y + 0.3, -0.45)
        jb.parent = hb
        for name, s, ya in LEGS:
            A, C, K, F = legs[name]
            b1 = ad.edit_bones.new('coxa.' + name)
            b1.head, b1.tail = A, C
            b1.parent = eb
            b2 = ad.edit_bones.new('femur.' + name)
            b2.head, b2.tail = C, K
            b2.parent = b1
            b2.use_connect = True
            b3 = ad.edit_bones.new('tibia.' + name)
            b3.head, b3.tail = K, F
            b3.parent = b2
            b3.use_connect = True
        bpy.ops.object.mode_set(mode='OBJECT')
    return ob


def bone_parent(ob, arm, bone):
    bpy.context.view_layer.update()
    mw = ob.matrix_world.copy()
    ob.parent = arm
    ob.parent_type = 'BONE'
    ob.parent_bone = bone
    bpy.context.view_layer.update()
    ob.matrix_world = mw


def build(main, ctx):
    c = coll('Monstruo', main)
    mats = {
        'chapa': mat_chapa(),
        'hollin': bpy.data.materials.get('Hollin') or M.mat_negro_hollin(),
        'oxido': bpy.data.materials.get('Oxido loco') or M.mat_oxido('Oxido loco', 1.2),
        'piel': mat_piel(),
        'dientes': mat_dientes(),
        'patas': mat_patas(),
        'brasa': mat_brasa(),
        'garganta': mat_brasa('Monstruo garganta', (0.9, 0.12, 0.02), 6.0),
        'cuenca': mat_brasa('Monstruo cuenca', (0.5, 0.05, 0.01), 1.5),
        'ojo': mat_ojo(),
    }
    hull, glow = body(c, mats)
    upper, lower, inner, eyes = face(c, mats)
    legs, legm = {}, {}
    for name, s, ya in LEGS:
        m, pts = leg_mesh(c, mats, name, s, ya)
        legs[name] = pts
        legm[name] = m
    arm = armature(c, legs)
    for o in (hull, glow):
        bone_parent(o, arm, 'cuerpo')
    for o in [upper, inner] + eyes:
        bone_parent(o, arm, 'cabeza')
    bone_parent(lower, arm, 'mandibula')
    for name, m in legm.items():
        for part, o in m.items():
            bone_parent(o, arm, part + '.' + name)
    glow.color = (1, 1, 1, 0.5)
    inner.color = (1, 1, 1, 0.3)
    # luces: brillo de los ojos y de la garganta (se animan)
    lights = {}
    for key, loc, col, en in (('ojo.L', (0.28, FACE_Y + 0.12, 0.17), (1.0, 0.25, 0.04), 0.0),
                              ('ojo.R', (-0.28, FACE_Y + 0.12, 0.17), (1.0, 0.25, 0.04), 0.0),
                              ('boca', (0, FACE_Y - 0.05, -0.3), (1.0, 0.3, 0.05), 0.0)):
        ld = bpy.data.lights.new('Monstruo luz ' + key, 'POINT')
        ld.color = col
        ld.energy = en
        ld.shadow_soft_size = 0.04
        lo = bpy.data.objects.new('Monstruo luz ' + key, ld)
        c.objects.link(lo)
        lo.location = loc
        bone_parent(lo, arm, 'cabeza')
        lights[key] = lo
    # objetivos de IK de las patas (en el mundo) y polos (con el cuerpo)
    targets, poles = {}, {}
    pb = arm.pose.bones
    for name, s, ya in LEGS:
        A, C, K, F = legs[name]
        t = bpy.data.objects.new('IK pata ' + name, None)
        c.objects.link(t)
        t.empty_display_size = 0.2
        t.location = F
        p = bpy.data.objects.new('Polo pata ' + name, None)
        c.objects.link(p)
        p.parent = arm
        p.parent_type = 'BONE'
        p.parent_bone = 'cuerpo'
        bpy.context.view_layer.update()
        p.matrix_world = arm.matrix_world @ Matrix.Translation(K + Vector((s * 1.2, 0, 3.0)))
        ik = pb['tibia.' + name].constraints.new('IK')
        ik.target = t
        ik.pole_target = p
        ik.chain_count = 2
        targets[name], poles[name] = t, p
    # ángulo de polo calibrado como en el personaje
    for name, s, ya in LEGS:
        ik = pb['tibia.' + name].constraints[0]
        rest = arm.data.bones['tibia.' + name].head_local.copy()
        best = None
        for ang in range(-180, 180, 5):
            ik.pole_angle = math.radians(ang)
            bpy.context.view_layer.update()
            err = (pb['tibia.' + name].head - rest).length
            if best is None or err < best[0]:
                best = (err, ang)
        ik.pole_angle = math.radians(best[1])
    R.update({'arm': arm, 'targets': targets, 'poles': poles, 'legs': legs, 'lights': lights, 'eyes': eyes,
              'glow': glow, 'inner': inner, 'mats': mats})
    return R
