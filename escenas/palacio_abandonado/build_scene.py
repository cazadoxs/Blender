"""
Palacio abandonado: construye la escena completa por script y guarda el .blend.

Recorrido: la cámara camina por un sendero, cruza la puerta abierta de una
muralla en ruinas y entra en un patio invadido por la vegetación que lleva a un
palacio-castillo abandonado (mezcla de fortaleza medieval y mansión de la Edad
Moderna).

Uso (Blender 5.x, también vale el módulo `bpy` de PyPI):
    python3 build_scene.py            # o: blender -b -P build_scene.py
Genera palacio_abandonado.blend y timing.json (tiempos para el sonido).
Todo es procedural: no necesita texturas ni HDRI externos.
"""
import bpy, bmesh, math, random, json, os
from mathutils import Vector, Matrix, Euler, noise

HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 24
DURATION = 22.0
FRAMES = int(FPS * DURATION)
TAU = math.tau

rng = random.Random(1234)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
ROOT = scene.collection


# ---------------------------------------------------------------------------
# Utilidades de nodos
# ---------------------------------------------------------------------------
def setin(nt, sock, x):
    if isinstance(x, bpy.types.NodeSocket):
        nt.links.new(x, sock)
    else:
        if isinstance(x, (tuple, list)) and len(x) == 3 and sock.type == 'RGBA':
            x = (*x, 1.0)
        sock.default_value = x


def node(nt, t, **kw):
    n = nt.nodes.new(t)
    for k, v in kw.items():
        setattr(n, k, v)
    return n


def M(nt, op, a, b=0.0, c=None, clamp=False):
    n = nt.nodes.new('ShaderNodeMath')
    n.operation = op
    n.use_clamp = clamp
    args = (a, b) if c is None else (a, b, c)
    for i, x in enumerate(args):
        setin(nt, n.inputs[i], x)
    return n.outputs[0]


def MIXC(nt, fac, a, b, blend='MIX'):
    n = nt.nodes.new('ShaderNodeMix')
    n.data_type = 'RGBA'
    n.blend_type = blend
    n.clamp_result = True
    setin(nt, n.inputs[0], fac)
    setin(nt, n.inputs[6], a)
    setin(nt, n.inputs[7], b)
    return n.outputs[2]


def NOISE(nt, vec=None, scale=1.0, detail=4.0, rough=0.5, dist=0.0, dims='3D', w=0.0):
    n = nt.nodes.new('ShaderNodeTexNoise')
    n.noise_dimensions = dims
    n.inputs['Scale'].default_value = scale
    n.inputs['Detail'].default_value = detail
    n.inputs['Roughness'].default_value = rough
    n.inputs['Distortion'].default_value = dist
    if dims in ('4D', '1D'):
        n.inputs['W'].default_value = w
    if vec is not None:
        nt.links.new(vec, n.inputs['Vector'])
    return n


def RAMP(nt, fac, stops, interp='LINEAR'):
    n = nt.nodes.new('ShaderNodeValToRGB')
    cr = n.color_ramp
    cr.interpolation = interp
    cr.elements.remove(cr.elements[1])
    p0, c0 = stops[0]
    cr.elements[0].position = p0
    cr.elements[0].color = (*c0, 1.0) if len(c0) == 3 else c0
    for p, c in stops[1:]:
        e = cr.elements.new(p)
        e.color = (*c, 1.0) if len(c) == 3 else c
    setin(nt, n.inputs[0], fac)
    return n.outputs[0]


def MAPR(nt, v, a, b, c=0.0, d=1.0, interp='LINEAR'):
    n = nt.nodes.new('ShaderNodeMapRange')
    n.interpolation_type = interp
    n.clamp = True
    setin(nt, n.inputs[0], v)
    n.inputs[1].default_value = a
    n.inputs[2].default_value = b
    n.inputs[3].default_value = c
    n.inputs[4].default_value = d
    return n.outputs[0]


def new_mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    return m, nt, out


def world_pos(nt):
    g = nt.nodes.new('ShaderNodeNewGeometry')
    return g


def bump(nt, height, strength=0.5, distance=0.05, normal=None):
    b = nt.nodes.new('ShaderNodeBump')
    b.inputs['Strength'].default_value = strength
    b.inputs['Distance'].default_value = distance
    setin(nt, b.inputs['Height'], height)
    if normal is not None:
        nt.links.new(normal, b.inputs['Normal'])
    return b.outputs[0]


# ---------------------------------------------------------------------------
# Materiales
# ---------------------------------------------------------------------------
def mat_stone(name, light, dark, brick_w=0.9, row_h=0.42, moss=0.6, streaks=0.6,
              mortar=0.03, seed=0.0, mortar_col=(0.06, 0.055, 0.045), rough=0.9):
    """Sillería envejecida: bloques, juntas, mugre, chorreones y musgo."""
    m, nt, out = new_mat(name)
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled')
    geo = world_pos(nt)
    sep = node(nt, 'ShaderNodeSeparateXYZ')
    nt.links.new(geo.outputs['Position'], sep.inputs[0])
    h = M(nt, 'ADD', sep.outputs[0], sep.outputs[1])
    comb = node(nt, 'ShaderNodeCombineXYZ')
    nt.links.new(h, comb.inputs[0])
    nt.links.new(sep.outputs[2], comb.inputs[1])
    comb.inputs[2].default_value = seed
    # Distorsión ligera para que las hiladas no sean perfectas
    wob = NOISE(nt, geo.outputs['Position'], scale=0.35, detail=2)
    wv = node(nt, 'ShaderNodeVectorMath', operation='MULTIPLY_ADD')
    nt.links.new(wob.outputs[1], wv.inputs[0])
    wv.inputs[1].default_value = (0.28, 0.14, 0.0)
    nt.links.new(comb.outputs[0], wv.inputs[2])
    brick = node(nt, 'ShaderNodeTexBrick', offset=0.5, offset_frequency=2)
    nt.links.new(wv.outputs[0], brick.inputs['Vector'])
    setin(nt, brick.inputs['Color1'], (1, 1, 1))
    setin(nt, brick.inputs['Color2'], (0, 0, 0))
    brick.inputs['Scale'].default_value = 1.0
    brick.inputs['Mortar Size'].default_value = mortar
    brick.inputs['Mortar Smooth'].default_value = 0.4
    brick.inputs['Brick Width'].default_value = brick_w
    brick.inputs['Row Height'].default_value = row_h
    per_brick = RAMP(nt, brick.outputs['Color'], [(0.0, dark), (0.55, tuple((a + b) / 2 for a, b in zip(dark, light))),
                                                  (1.0, light)])
    tint = NOISE(nt, geo.outputs['Position'], scale=0.6, detail=2)
    per_brick = MIXC(nt, 0.35, per_brick, RAMP(nt, tint.outputs[0], [(0.35, (0.85, 0.9, 1.0)), (0.65, (1.1, 1.0, 0.85))]),
                     'MULTIPLY')
    # Textura dentro de cada piedra
    n1 = NOISE(nt, geo.outputs['Position'], scale=4.0, detail=8, rough=0.6)
    grain = RAMP(nt, n1.outputs[0], [(0.3, (0.55, 0.55, 0.55)), (0.7, (1, 1, 1))])
    col = MIXC(nt, 0.8, per_brick, grain, 'MULTIPLY')
    # Mugre a gran escala
    n2 = NOISE(nt, geo.outputs['Position'], scale=0.18, detail=5, rough=0.6)
    grime = RAMP(nt, n2.outputs[0], [(0.35, (0.45, 0.43, 0.40)), (0.65, (1, 1, 1))])
    col = MIXC(nt, 0.9, col, grime, 'MULTIPLY')
    # Chorreones verticales
    mp = node(nt, 'ShaderNodeMapping')
    nt.links.new(geo.outputs['Position'], mp.inputs['Vector'])
    mp.inputs['Scale'].default_value = (3.0, 3.0, 0.12)
    n3 = NOISE(nt, mp.outputs[0], scale=1.2, detail=3)
    streak = RAMP(nt, n3.outputs[0], [(0.45, (0.35, 0.33, 0.30)), (0.62, (1, 1, 1))])
    col = MIXC(nt, streaks, col, streak, 'MULTIPLY')
    # Juntas
    col = MIXC(nt, brick.outputs['Factor'], col, mortar_col)
    # Musgo: arriba (normales hacia +Z) y humedad cerca del suelo
    sn = node(nt, 'ShaderNodeSeparateXYZ')
    nt.links.new(geo.outputs['Normal'], sn.inputs[0])
    top = MAPR(nt, sn.outputs[2], 0.35, 0.85)
    base = MAPR(nt, sep.outputs[2], 2.2, 0.0)
    nm = NOISE(nt, geo.outputs['Position'], scale=0.9, detail=6, rough=0.65)
    nmask = MAPR(nt, nm.outputs[0], 0.42, 0.62)
    mask = M(nt, 'MULTIPLY', M(nt, 'ADD', top, M(nt, 'MULTIPLY', base, 0.8), clamp=True), nmask)
    mask = M(nt, 'MULTIPLY', mask, moss, clamp=True)
    nmc = NOISE(nt, geo.outputs['Position'], scale=6.0, detail=4)
    mosscol = RAMP(nt, nmc.outputs[0], [(0.3, (0.035, 0.05, 0.012)), (0.7, (0.10, 0.12, 0.03))])
    col = MIXC(nt, mask, col, mosscol)
    nt.links.new(col, bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = rough
    # Relieve: juntas hundidas + superficie irregular
    hgt = M(nt, 'ADD', M(nt, 'MULTIPLY', brick.outputs['Factor'], -1.0),
            M(nt, 'MULTIPLY', n1.outputs[0], 0.6))
    hgt = M(nt, 'ADD', hgt, M(nt, 'MULTIPLY', nm.outputs[0], 0.4))
    hgt = M(nt, 'ADD', hgt, M(nt, 'MULTIPLY', brick.outputs['Color'], 0.35))
    nt.links.new(bump(nt, hgt, 0.55, 0.04), bsdf.inputs['Normal'])
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return m


def mat_rock(name, light=(0.32, 0.30, 0.27), dark=(0.12, 0.11, 0.10), moss=0.7):
    m, nt, out = new_mat(name)
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled')
    geo = world_pos(nt)
    n1 = NOISE(nt, geo.outputs['Position'], scale=2.5, detail=10, rough=0.62)
    col = RAMP(nt, n1.outputs[0], [(0.25, dark), (0.75, light)])
    sn = node(nt, 'ShaderNodeSeparateXYZ')
    nt.links.new(geo.outputs['Normal'], sn.inputs[0])
    top = MAPR(nt, sn.outputs[2], 0.2, 0.9)
    nm = NOISE(nt, geo.outputs['Position'], scale=1.5, detail=6)
    mask = M(nt, 'MULTIPLY', M(nt, 'MULTIPLY', top, MAPR(nt, nm.outputs[0], 0.4, 0.6)), moss)
    col = MIXC(nt, mask, col, (0.06, 0.08, 0.02))
    nt.links.new(col, bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = 0.92
    nt.links.new(bump(nt, n1.outputs[0], 0.7, 0.05), bsdf.inputs['Normal'])
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return m


def mat_slate(name):
    m, nt, out = new_mat(name)
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled')
    geo = world_pos(nt)
    sep = node(nt, 'ShaderNodeSeparateXYZ')
    nt.links.new(geo.outputs['Position'], sep.inputs[0])
    comb = node(nt, 'ShaderNodeCombineXYZ')
    nt.links.new(M(nt, 'ADD', sep.outputs[0], sep.outputs[1]), comb.inputs[0])
    nt.links.new(sep.outputs[2], comb.inputs[1])
    brick = node(nt, 'ShaderNodeTexBrick', offset=0.5, offset_frequency=2)
    nt.links.new(comb.outputs[0], brick.inputs['Vector'])
    setin(nt, brick.inputs['Color1'], (1, 1, 1))
    setin(nt, brick.inputs['Color2'], (0, 0, 0))
    brick.inputs['Mortar Size'].default_value = 0.012
    brick.inputs['Brick Width'].default_value = 0.32
    brick.inputs['Row Height'].default_value = 0.17
    tile = RAMP(nt, brick.outputs['Color'], [(0.0, (0.035, 0.04, 0.05)), (1.0, (0.11, 0.115, 0.13))])
    n1 = NOISE(nt, geo.outputs['Position'], scale=0.5, detail=6)
    lichen = MAPR(nt, n1.outputs[0], 0.55, 0.7)
    col = MIXC(nt, M(nt, 'MULTIPLY', lichen, 0.55), tile, (0.22, 0.17, 0.06))
    n2 = NOISE(nt, geo.outputs['Position'], scale=0.25, detail=4)
    col = MIXC(nt, M(nt, 'MULTIPLY', MAPR(nt, n2.outputs[0], 0.5, 0.65), 0.6), col, (0.04, 0.06, 0.015))
    col = MIXC(nt, brick.outputs['Factor'], col, (0.01, 0.01, 0.01))
    nt.links.new(col, bsdf.inputs['Base Color'])
    nt.links.new(MAPR(nt, lichen, 0, 1, 0.45, 0.85), bsdf.inputs['Roughness'])
    nt.links.new(bump(nt, M(nt, 'MULTIPLY', brick.outputs['Factor'], -1.0), 0.6, 0.03), bsdf.inputs['Normal'])
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return m


def mat_wood(name, light=(0.30, 0.24, 0.17), dark=(0.08, 0.06, 0.045)):
    m, nt, out = new_mat(name)
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled')
    tc = node(nt, 'ShaderNodeTexCoord')
    mp = node(nt, 'ShaderNodeMapping')
    nt.links.new(tc.outputs['Object'], mp.inputs['Vector'])
    mp.inputs['Scale'].default_value = (14.0, 14.0, 0.6)
    n1 = NOISE(nt, mp.outputs[0], scale=2.0, detail=10, rough=0.7, dist=0.4)
    col = RAMP(nt, n1.outputs[0], [(0.3, dark), (0.7, light)])
    obi = node(nt, 'ShaderNodeObjectInfo')
    col = MIXC(nt, M(nt, 'MULTIPLY', obi.outputs['Random'], 0.5), col, (0.05, 0.045, 0.04), 'MULTIPLY')
    nt.links.new(col, bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = 0.88
    nt.links.new(bump(nt, n1.outputs[0], 0.6, 0.02), bsdf.inputs['Normal'])
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return m


def mat_iron(name):
    m, nt, out = new_mat(name)
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled')
    geo = world_pos(nt)
    n1 = NOISE(nt, geo.outputs['Position'], scale=6.0, detail=8, rough=0.6)
    rust = MAPR(nt, n1.outputs[0], 0.4, 0.6)
    col = MIXC(nt, rust, (0.05, 0.05, 0.05), (0.22, 0.08, 0.03))
    nt.links.new(col, bsdf.inputs['Base Color'])
    nt.links.new(MAPR(nt, rust, 0, 1, 0.75, 0.2), bsdf.inputs['Metallic'])
    nt.links.new(MAPR(nt, rust, 0, 1, 0.45, 0.85), bsdf.inputs['Roughness'])
    nt.links.new(bump(nt, n1.outputs[0], 0.4, 0.01), bsdf.inputs['Normal'])
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return m


def mat_void(name):
    """Interior oscuro tras ventanas y puertas."""
    m, nt, out = new_mat(name)
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled')
    setin(nt, bsdf.inputs['Base Color'], (0.012, 0.011, 0.010))
    bsdf.inputs['Roughness'].default_value = 0.95
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return m


def mat_glass(name):
    m, nt, out = new_mat(name)
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled')
    setin(nt, bsdf.inputs['Base Color'], (0.35, 0.38, 0.33))
    bsdf.inputs['Roughness'].default_value = 0.12
    bsdf.inputs['Metallic'].default_value = 0.0
    bsdf.inputs['Specular IOR Level'].default_value = 0.8
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return m


def mat_ground(name):
    m, nt, out = new_mat(name)
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled')
    geo = world_pos(nt)
    n1 = NOISE(nt, geo.outputs['Position'], scale=0.35, detail=6, rough=0.6)
    n2 = NOISE(nt, geo.outputs['Position'], scale=7.0, detail=8, rough=0.7)
    base = RAMP(nt, n1.outputs[0], [(0.3, (0.09, 0.075, 0.05)), (0.5, (0.16, 0.13, 0.07)),
                                    (0.7, (0.10, 0.11, 0.035))])
    det = RAMP(nt, n2.outputs[0], [(0.3, (0.6, 0.6, 0.6)), (0.7, (1.1, 1.05, 1.0))])
    col = MIXC(nt, 1.0, base, det, 'MULTIPLY')
    nt.links.new(col, bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = 0.95
    nt.links.new(bump(nt, n2.outputs[0], 0.8, 0.03), bsdf.inputs['Normal'])
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return m


def mat_cobble(name):
    m, nt, out = new_mat(name)
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled')
    geo = world_pos(nt)
    v_edge = node(nt, 'ShaderNodeTexVoronoi', feature='DISTANCE_TO_EDGE')
    nt.links.new(geo.outputs['Position'], v_edge.inputs['Vector'])
    v_edge.inputs['Scale'].default_value = 2.6
    v_col = node(nt, 'ShaderNodeTexVoronoi', feature='F1')
    nt.links.new(geo.outputs['Position'], v_col.inputs['Vector'])
    v_col.inputs['Scale'].default_value = 2.6
    stone = RAMP(nt, v_col.outputs['Color'], [(0.0, (0.10, 0.095, 0.085)), (1.0, (0.30, 0.28, 0.24))])
    gap = MAPR(nt, v_edge.outputs['Distance'], 0.02, 0.09)
    n1 = NOISE(nt, geo.outputs['Position'], scale=0.6, detail=5)
    missing = MAPR(nt, n1.outputs[0], 0.5, 0.6)  # zonas sin adoquines
    dirt = RAMP(nt, NOISE(nt, geo.outputs['Position'], scale=5, detail=6).outputs[0],
                [(0.3, (0.07, 0.06, 0.04)), (0.7, (0.14, 0.12, 0.07))])
    col = MIXC(nt, gap, dirt, stone)
    col = MIXC(nt, missing, col, dirt)
    mossmask = M(nt, 'MULTIPLY', M(nt, 'SUBTRACT', 1.0, gap), 0.7)
    col = MIXC(nt, mossmask, col, (0.04, 0.055, 0.015))
    nt.links.new(col, bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = 0.85
    h = M(nt, 'MULTIPLY', gap, M(nt, 'SUBTRACT', 1.0, missing))
    nt.links.new(bump(nt, h, 0.9, 0.06), bsdf.inputs['Normal'])
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return m


def mat_foliage(name, c_a, c_b, translucency=0.35, rough=0.55, island_random=True):
    m, nt, out = new_mat(name)
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled')
    obi = node(nt, 'ShaderNodeObjectInfo')
    rnd = obi.outputs['Random']
    if island_random:
        geo = world_pos(nt)
        rnd = M(nt, 'FRACT', M(nt, 'ADD', M(nt, 'MULTIPLY', geo.outputs['Random Per Island'], 0.6),
                                 M(nt, 'MULTIPLY', obi.outputs['Random'], 0.7)))
    col = RAMP(nt, rnd, [(0.0, c_a), (1.0, c_b)])
    nt.links.new(col, bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = rough
    tr = node(nt, 'ShaderNodeBsdfTranslucent')
    nt.links.new(MIXC(nt, 1.0, col, (1.2, 1.3, 0.6), 'MULTIPLY'), tr.inputs['Color'])
    mix = node(nt, 'ShaderNodeMixShader')
    mix.inputs[0].default_value = translucency
    nt.links.new(bsdf.outputs[0], mix.inputs[1])
    nt.links.new(tr.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs[0])
    return m


def mat_water(name):
    m, nt, out = new_mat(name)
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled')
    geo = world_pos(nt)
    n1 = NOISE(nt, geo.outputs['Position'], scale=1.2, detail=4)
    algae = MAPR(nt, n1.outputs[0], 0.55, 0.65)
    col = MIXC(nt, algae, (0.01, 0.015, 0.01), (0.07, 0.09, 0.02))
    nt.links.new(col, bsdf.inputs['Base Color'])
    nt.links.new(MAPR(nt, algae, 0, 1, 0.04, 0.8), bsdf.inputs['Roughness'])
    nt.links.new(bump(nt, NOISE(nt, geo.outputs['Position'], scale=8, detail=2).outputs[0], 0.08, 0.01),
                 bsdf.inputs['Normal'])
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return m


def mat_simple(name, col, rough=0.9):
    m, nt, out = new_mat(name)
    bsdf = node(nt, 'ShaderNodeBsdfPrincipled')
    setin(nt, bsdf.inputs['Base Color'], col)
    bsdf.inputs['Roughness'].default_value = rough
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    return m


MAT = {
    'wall': mat_stone('Muralla', (0.33, 0.29, 0.23), (0.12, 0.105, 0.085), brick_w=0.75, row_h=0.36,
                      moss=0.85, seed=3.0),
    'gate': mat_stone('Torre_puerta', (0.35, 0.31, 0.25), (0.13, 0.115, 0.09), brick_w=0.95, row_h=0.45,
                      moss=0.7, seed=7.0),
    'palace': mat_stone('Palacio_sillar', (0.50, 0.44, 0.34), (0.24, 0.20, 0.15), brick_w=1.25, row_h=0.5,
                        moss=0.3, streaks=0.85, mortar=0.015, seed=11.0),
    'trim': mat_stone('Molduras', (0.52, 0.46, 0.37), (0.33, 0.29, 0.22), brick_w=1.6, row_h=0.9,
                      moss=0.3, streaks=0.9, mortar=0.006, seed=5.0),
    'rock': mat_rock('Escombro'),
    'slate': mat_slate('Pizarra'),
    'wood': mat_wood('Madera_vieja'),
    'iron': mat_iron('Hierro_oxidado'),
    'void': mat_void('Interior_oscuro'),
    'glass': mat_glass('Cristal_sucio'),
    'ground': mat_ground('Tierra'),
    'cobble': mat_cobble('Empedrado'),
    'grass': mat_foliage('Hierba', (0.30, 0.25, 0.10), (0.06, 0.12, 0.025), 0.3, 0.6),
    'leaf': mat_foliage('Hojas', (0.05, 0.09, 0.02), (0.22, 0.16, 0.04), 0.35, 0.5),
    'ivy': mat_foliage('Hiedra', (0.02, 0.05, 0.012), (0.07, 0.10, 0.03), 0.25, 0.4),
    'farleaf': mat_simple('Bosque_lejano', (0.03, 0.05, 0.02), 0.8),
    'bark': mat_rock('Corteza', (0.17, 0.15, 0.13), (0.05, 0.045, 0.04), moss=0.9),
    'water': mat_water('Agua_estancada'),
    'flower_w': mat_simple('Flor_blanca', (0.8, 0.78, 0.7), 0.6),
    'flower_y': mat_simple('Flor_amarilla', (0.75, 0.55, 0.08), 0.6),
    'flower_p': mat_simple('Flor_morada', (0.35, 0.12, 0.45), 0.6),
    'bird': mat_simple('Cuervo', (0.01, 0.01, 0.012), 0.6),
}


# ---------------------------------------------------------------------------
# Utilidades de malla
# ---------------------------------------------------------------------------
def link(ob, coll=None):
    (coll or ROOT).objects.link(ob)
    return ob


def obj_from_bm(name, bm, mats, smooth=False, coll=None):
    me = bpy.data.meshes.new(name)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    for mt in (mats if isinstance(mats, (list, tuple)) else [mats]):
        me.materials.append(mt)
    if smooth:
        me.shade_smooth()
    return link(bpy.data.objects.new(name, me), coll)


def add_box(bm, c, s, rot=(0, 0, 0)):
    mtx = Matrix.Translation(c) @ Euler(rot).to_matrix().to_4x4() @ Matrix.Diagonal((*s, 1.0))
    return bmesh.ops.create_cube(bm, size=1.0, matrix=mtx)['verts']


def add_cyl(bm, c, r, h, seg=24, r2=None, rot=(0, 0, 0), caps=True):
    mtx = Matrix.Translation(c) @ Euler(rot).to_matrix().to_4x4()
    return bmesh.ops.create_cone(bm, cap_ends=caps, cap_tris=False, segments=seg, radius1=r,
                                 radius2=r if r2 is None else r2, depth=h, matrix=mtx)['verts']


def arch_prism(bm, cx, cy, z_bottom, z_spring, half_w, length, axis='Y', seg=24):
    """Prisma cerrado (rectángulo + medio punto) para abrir arcos con un solo booleano."""
    prof = [(-half_w, z_bottom), (half_w, z_bottom)]
    for i in range(seg + 1):
        a = math.pi * i / seg
        prof.append((half_w * math.cos(a), z_spring + half_w * math.sin(a)))
    rings = []
    for d in (-length / 2, length / 2):
        ring = []
        for (u, z) in prof:
            if axis == 'Y':
                ring.append(bm.verts.new((cx + u, cy + d, z)))
            else:
                ring.append(bm.verts.new((cx + d, cy + u, z)))
        rings.append(ring)
    n = len(prof)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((rings[0][i], rings[0][j], rings[1][j], rings[1][i]))
    bm.faces.new(rings[0])
    bm.faces.new(list(reversed(rings[1])))


def apply_modifiers(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev)
    old = ob.data
    ob.modifiers.clear()
    ob.data = me
    bpy.data.meshes.remove(old)


def boolean_cut(ob, cutter_bm, cutter_mat=None, name='cutter'):
    """Resta la geometría de cutter_bm a ob (solver exacto) y aplica."""
    cut = obj_from_bm(name, cutter_bm, [cutter_mat] if cutter_mat else [])
    cut.hide_render = True
    mod = ob.modifiers.new('cut', 'BOOLEAN')
    mod.operation = 'DIFFERENCE'
    mod.solver = 'EXACT'
    mod.object = cut
    mod.material_mode = 'TRANSFER'
    apply_modifiers(ob)
    bpy.data.objects.remove(cut)


def ground_h(x, y):
    """Altura del terreno cercano."""
    v = noise.noise(Vector((x * 0.05, y * 0.05, 0.3))) * 0.35
    v += noise.noise(Vector((x * 0.25, y * 0.25, 1.7))) * 0.06
    # Aplanar el sendero y la base de los edificios
    d = abs(x)
    flat = min(1.0, max(0.0, (d - 2.0) / 4.0))
    v *= 0.25 + 0.75 * flat
    r = math.hypot(x, y - 25)
    if r > 60:
        v += (r - 60) * 0.06 * (0.6 + 0.4 * noise.noise(Vector((x * 0.02, y * 0.02, 5.0))))
    return v


def wall_line(bm, p0, p1, thick, height_fn, nseg, z0=-1.0):
    """Lienzo de muralla entre dos puntos con coronación irregular (brechas)."""
    p0, p1 = Vector(p0), Vector(p1)
    d = (p1 - p0)
    L = d.length
    d.normalize()
    n = Vector((-d.y, d.x)) * (thick / 2)
    rings = []
    for i in range(nseg + 1):
        t = i / nseg
        p = p0 + d * (L * t)
        h = height_fn(t * L)
        a = bm.verts.new((p.x + n.x, p.y + n.y, z0))
        b = bm.verts.new((p.x - n.x, p.y - n.y, z0))
        c = bm.verts.new((p.x - n.x, p.y - n.y, h))
        e = bm.verts.new((p.x + n.x, p.y + n.y, h))
        rings.append((a, b, c, e))
    for i in range(nseg):
        A, B = rings[i], rings[i + 1]
        bm.faces.new((A[0], B[0], B[3], A[3]))
        bm.faces.new((A[1], A[2], B[2], B[1]))
        bm.faces.new((A[3], B[3], B[2], A[2]))
        bm.faces.new((A[0], A[1], B[1], B[0]))
    bm.faces.new(rings[0])
    bm.faces.new(tuple(reversed(rings[-1])))


def ruined_height(H, L, breaches, seed):
    def f(s):
        h = H + noise.noise(Vector((s * 0.4, seed, 0.0))) * 0.25
        for (c, w, dep) in breaches:
            h -= dep * math.exp(-((s - c) / w) ** 2) * (0.85 + 0.3 * noise.noise(Vector((s * 1.3, seed, 2.0))))
        return h
    return f


def merlons_along(bm, p0, p1, thick, height_fn, spacing=2.1, mw=1.15, mh=1.25, seed=0):
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    L = d.length
    d.normalize()
    ang = math.atan2(d.y, d.x)
    s = spacing * 0.5
    r = random.Random(seed)
    H0 = height_fn(0.0) if False else None
    while s < L - 0.5:
        h = height_fn(s)
        top = max(height_fn(s - 0.6), height_fn(s + 0.6))
        expected = top
        if r.random() > 0.22 and h > expected - 0.35 and h > 2.5:
            hh = mh * r.uniform(0.6, 1.05)
            tilt = (r.uniform(-0.04, 0.04), r.uniform(-0.04, 0.04), ang + r.uniform(-0.03, 0.03))
            p = p0 + d * s
            add_box(bm, (p.x, p.y, h + hh / 2 - 0.05), (mw * r.uniform(0.85, 1.0), thick * 0.95, hh), tilt)
        s += spacing


# ---------------------------------------------------------------------------
# Terreno
# ---------------------------------------------------------------------------
def build_ground():
    bm = bmesh.new()
    nx, ny = 200, 220
    x0, x1, y0, y1 = -80.0, 80.0, -60.0, 116.0
    verts = []
    for j in range(ny + 1):
        y = y0 + (y1 - y0) * j / ny
        row = []
        for i in range(nx + 1):
            x = x0 + (x1 - x0) * i / nx
            row.append(bm.verts.new((x, y, ground_h(x, y))))
        verts.append(row)
    for j in range(ny):
        for i in range(nx):
            bm.faces.new((verts[j][i], verts[j][i + 1], verts[j + 1][i + 1], verts[j + 1][i]))
    g = obj_from_bm('Suelo_cercano', bm, MAT['ground'], smooth=True)
    # Terreno lejano con colinas
    bm = bmesh.new()
    n = 120
    R = 900.0
    vv = []
    for j in range(n + 1):
        row = []
        for i in range(n + 1):
            x = -R + 2 * R * i / n
            y = -R + 2 * R * j / n + 200
            r = math.hypot(x, y - 25)
            h = -0.4
            if r > 70:
                h += (r - 70) * 0.05 * (0.5 + 0.5 * (noise.noise(Vector((x * 0.006, y * 0.006, 9.0))) + 1))
                h += noise.noise(Vector((x * 0.02, y * 0.02, 3.0))) * 4.0 * min(1, (r - 70) / 100)
            row.append(bm.verts.new((x, y, h)))
        vv.append(row)
    for j in range(n):
        for i in range(n):
            bm.faces.new((vv[j][i], vv[j][i + 1], vv[j + 1][i + 1], vv[j + 1][i]))
    obj_from_bm('Suelo_lejano', bm, MAT['ground'], smooth=True)
    # Sendero empedrado (x ~ 0)
    bm = bmesh.new()
    ys = [-40 + i * 0.5 for i in range(int((53.6 + 40) / 0.5) + 1)]
    xs = [-1.9, -1.0, 0.0, 1.0, 1.9]
    vv = []
    for y in ys:
        row = []
        for x in xs:
            w = 0.05 * noise.noise(Vector((x, y * 0.3, 4.0)))
            row.append(bm.verts.new((x * (1 + w), y, ground_h(x, y) + 0.035)))
        vv.append(row)
    for j in range(len(ys) - 1):
        for i in range(len(xs) - 1):
            bm.faces.new((vv[j][i], vv[j][i + 1], vv[j + 1][i + 1], vv[j + 1][i]))
    obj_from_bm('Sendero', bm, MAT['cobble'], smooth=True)
    return g


# ---------------------------------------------------------------------------
# Muralla y torre de la puerta
# ---------------------------------------------------------------------------
GATE_HALF_W = 2.5      # media anchura del paso
GATE_SPRING = 4.6      # arranque del arco
GATE_Y0, GATE_Y1 = -3.6, 3.6


def build_walls():
    bm = bmesh.new()
    merl = bmesh.new()
    T = 3.2
    H = 9.5
    segs = [
        # (p0, p1, brechas [(centro, ancho, profundidad)])
        ((-45, 0), (-7.2, 0), [(9, 3.5, 4.2), (27, 2.0, 1.5)]),
        ((7.2, 0), (45, 0), [(13, 4.5, 6.0), (31, 1.6, 2.0)]),
        ((-45, 0), (-45, 74), [(22, 5.0, 5.0), (48, 2.5, 2.0)]),
        ((45, 0), (45, 74), [(35, 6.0, 7.0), (60, 2.0, 1.5)]),
    ]
    for k, (p0, p1, br) in enumerate(segs):
        L = (Vector(p1) - Vector(p0)).length
        hf = ruined_height(H, L, br, seed=k * 3.1)
        wall_line(bm, p0, p1, T, hf, int(L * 2))
        merlons_along(merl, p0, p1, T * 0.42, hf, seed=k)
    # Las almenas se apoyan en el lado exterior del adarve
    w = obj_from_bm('Muralla', bm, MAT['wall'])
    m = obj_from_bm('Muralla_almenas', merl, MAT['wall'])
    # Torres de esquina en ruinas
    bm = bmesh.new()
    for (x, y) in ((-45, 0), (45, 0)):
        r = 4.2
        seg = 28
        hgt = 14.0
        ring_b, ring_t = [], []
        for i in range(seg):
            a = TAU * i / seg
            px, py = x + r * math.cos(a), y + r * math.sin(a)
            top = hgt - 3.5 * max(0, math.sin(a * 2 + x)) - 1.2 * noise.noise(Vector((a * 3, x, 1)))
            ring_b.append(bm.verts.new((px, py, -1)))
            ring_t.append(bm.verts.new((px, py, top)))
        for i in range(seg):
            j = (i + 1) % seg
            bm.faces.new((ring_b[i], ring_b[j], ring_t[j], ring_t[i]))
        bm.faces.new(ring_t)
        bm.faces.new(list(reversed(ring_b)))
    obj_from_bm('Torres_esquina', bm, MAT['wall'])

    # Torre de la puerta
    bm = bmesh.new()
    add_box(bm, (0, 0, 6.0), (14.4, 7.2, 14.0))
    gh = obj_from_bm('Torre_puerta', bm, MAT['gate'])
    cut = bmesh.new()
    arch_prism(cut, 0, 0, -1.5, GATE_SPRING, GATE_HALF_W, 12, seg=40)
    boolean_cut(gh, cut, MAT['gate'])
    # Saeteras
    cut = bmesh.new()
    for x in (-5.0, 5.0):
        for z in (6.5, 10.0):
            add_box(cut, (x, -3.6, z), (0.22, 1.2, 1.4))
            add_box(cut, (x, 3.6, z), (0.22, 1.2, 1.4))
    boolean_cut(gh, cut, MAT['void'])

    deco = bmesh.new()
    # Dovelas del arco (delante y detrás)
    nv = 17
    for yy in (GATE_Y0 - 0.12, GATE_Y1 + 0.12):
        for i in range(nv):
            a0 = math.pi * i / nv
            a1 = math.pi * (i + 1) / nv
            am = (a0 + a1) / 2
            r_in, r_out = GATE_HALF_W + 0.02, GATE_HALF_W + 0.85 + (0.25 if i == nv // 2 else 0)
            rm = (r_in + r_out) / 2
            wdt = (a1 - a0) * rm * 0.96
            add_box(deco, (rm * math.cos(am), yy, GATE_SPRING + rm * math.sin(am)),
                    (r_out - r_in, 0.32, wdt), (0, -(am - math.pi / 2) + math.pi / 2, 0) if False else
                    (0, math.pi / 2 - am, 0))
        # jambas
        for sx in (-1, 1):
            for k in range(5):
                hh = GATE_SPRING / 5
                add_box(deco, (sx * (GATE_HALF_W + 0.42), yy, -0.3 + hh * k + hh / 2 + 0.3),
                        (0.84 if k % 2 == 0 else 0.6, 0.32, hh * 0.97))
    # Matacanes: ménsulas + parapeto volado
    for yy, sgn in ((GATE_Y0, -1), (GATE_Y1, 1)):
        for i in range(15):
            x = -6.65 + i * 0.95
            add_box(deco, (x, yy + sgn * 0.25, 11.6), (0.42, 0.5, 0.9))
    add_box(deco, (0, 0, 12.75), (15.2, 8.2, 1.3))
    obj_from_bm('Puerta_molduras', deco, MAT['gate'])
    merl = bmesh.new()
    hf = lambda s: 13.4
    for (p0, p1) in (((-7.4, -4.0), (7.4, -4.0)), ((-7.4, 4.0), (7.4, 4.0)),
                     ((-7.5, -4.0), (-7.5, 4.0)), ((7.5, -4.0), (7.5, 4.0))):
        merlons_along(merl, (p0[0], p0[1] + (0.3 if p0[1] < 0 else -0.3) if p0[1] == p1[1] else p0[1]),
                      (p1[0], p1[1] + (0.3 if p1[1] < 0 else -0.3) if p0[1] == p1[1] else p1[1]),
                      0.6, hf, spacing=1.9, mw=1.0, mh=1.3, seed=hash(p0) % 100)
    obj_from_bm('Puerta_almenas', merl, MAT['gate'])

    # Rastrillo (subido, asoma bajo la clave)
    bm = bmesh.new()
    py = -2.3
    for i in range(9):
        x = -2.4 + i * 0.6
        top_arch = GATE_SPRING + math.sqrt(max(0.0, GATE_HALF_W ** 2 - x ** 2))
        bottom = GATE_SPRING + 1.85
        if top_arch - bottom > 0.15:
            add_box(bm, (x, py, (bottom + top_arch + 0.4) / 2), (0.09, 0.09, top_arch - bottom + 0.4))
            add_cyl(bm, (x, py, bottom - 0.12), 0.06, 0.25, seg=6, r2=0.0)
    add_box(bm, (0, py, GATE_SPRING + 1.95), (4.0, 0.08, 0.1))
    obj_from_bm('Rastrillo', bm, MAT['iron'])
    return w


def build_gate_doors():
    """Dos hojas de madera: una abierta del todo, la otra entornada y meciéndose."""
    def leaf(name, hinge_x, side, missing=()):
        bm = bmesh.new()
        n = 5
        w = GATE_HALF_W / n
        for i in range(n):
            if i in missing:
                continue
            xc = side * (-(i + 0.5) * w)      # coordenada local: la hoja crece hacia el centro
            xg = hinge_x + xc
            arch = GATE_SPRING + math.sqrt(max(0.0, GATE_HALF_W ** 2 - (xg - 0) ** 2)) - 0.08
            h = arch + 0.0
            if i == 2 and side < 0:
                h *= 0.62  # tabla partida
            add_box(bm, (xc, 0, h / 2), (w * 0.95, 0.11, h))
        for z in (0.8, 2.6, 4.4):
            add_box(bm, (side * -GATE_HALF_W / 2, -0.08, z), (GATE_HALF_W * 0.98, 0.04, 0.16))
        ob = obj_from_bm(name, bm, MAT['wood'])
        # el último elemento (herrajes) con hierro
        return ob

    pivot_y = 1.6
    L = leaf('Hoja_izquierda', -GATE_HALF_W, -1)
    L.location = (-GATE_HALF_W + 0.05, pivot_y, 0.0)
    L.rotation_euler = (0, 0, math.radians(-96))
    R = leaf('Hoja_derecha', GATE_HALF_W, 1, missing=(3,))
    R.location = (GATE_HALF_W - 0.05, pivot_y, 0.0)
    # Bisagras / herrajes
    bm = bmesh.new()
    for sx in (-1, 1):
        for z in (0.8, 2.6, 4.4):
            add_cyl(bm, (sx * (GATE_HALF_W - 0.02), pivot_y, z), 0.07, 0.35, seg=8)
    obj_from_bm('Goznes', bm, MAT['iron'])
    return L, R


# ---------------------------------------------------------------------------
# Palacio
# ---------------------------------------------------------------------------
PAL_Y = 56.0            # fachada principal
PAL_FLOOR = 1.54        # cota de la planta noble (7 peldaños)


def window_cutters(bm, xs, zs, w, h, y, depth=1.2):
    for x in xs:
        for z in zs:
            add_box(bm, (x, y, z), (w, depth, h))


def build_palace():
    # Cuerpo principal
    bm = bmesh.new()
    add_box(bm, (0, 63.5, 8.0), (42.0, 15.0, 16.0))
    main = obj_from_bm('Palacio_cuerpo', bm, MAT['palace'])
    cut = bmesh.new()
    xs = [x for x in (-19, -15.5, -12, -8.5, 8.5, 12, 15.5, 19)]
    window_cutters(cut, xs, [PAL_FLOOR + 2.0], 1.5, 2.7, PAL_Y)
    window_cutters(cut, xs, [PAL_FLOOR + 6.6], 1.5, 3.0, PAL_Y)
    window_cutters(cut, xs, [PAL_FLOOR + 11.0], 1.3, 2.1, PAL_Y)
    # ventanas laterales
    for z in (PAL_FLOOR + 2.0, PAL_FLOOR + 6.6, PAL_FLOOR + 11.0):
        for y in (60, 64, 68):
            add_box(cut, (-21, y, z), (1.2, 1.5, 2.5))
            add_box(cut, (21, y, z), (1.2, 1.5, 2.5))
    boolean_cut(main, cut, MAT['void'])

    # Pabellón central
    bm = bmesh.new()
    add_box(bm, (0, 61.5, 10.25), (13.0, 16.0, 20.5))
    pav = obj_from_bm('Palacio_pabellon', bm, MAT['palace'])
    cut = bmesh.new()
    # puerta en arco
    arch_prism(cut, 0, 53.5, PAL_FLOOR, PAL_FLOOR + 4.4, 1.8, 1.6, seg=32)
    window_cutters(cut, (-4.0, 4.0), [PAL_FLOOR + 2.2], 1.4, 2.8, 53.5)
    window_cutters(cut, (-4.0, 0.0, 4.0), [PAL_FLOOR + 8.2], 1.5, 3.4, 53.5)
    window_cutters(cut, (-4.0, 0.0, 4.0), [PAL_FLOOR + 13.4], 1.3, 2.4, 53.5)
    # óculo
    boolean_cut(pav, cut, MAT['void'])
    cut = bmesh.new()
    add_cyl(cut, (0, 53.5, 18.3), 1.1, 1.6, seg=32, rot=(math.pi / 2, 0, 0))
    boolean_cut(pav, cut, MAT['void'])

    trim = bmesh.new()
    # Zócalo, impostas y cornisa
    add_box(trim, (0, PAL_Y - 0.2, 0.6), (42.4, 0.5, 2.0))
    for z in (PAL_FLOOR + 4.25, PAL_FLOOR + 9.1):
        add_box(trim, (-14.6, PAL_Y - 0.15, z), (13.2, 0.35, 0.32))
        add_box(trim, (14.6, PAL_Y - 0.15, z), (13.2, 0.35, 0.32))
        add_box(trim, (0, 53.35, z), (13.4, 0.35, 0.32))
    add_box(trim, (0, 63.5, 15.95), (42.8, 15.8, 0.5))
    add_box(trim, (0, 61.5, 20.5), (13.8, 16.6, 0.55))
    # Pilastras del pabellón
    for x in (-6.2, -2.1, 2.1, 6.2):
        add_box(trim, (x, 53.35, 10.2), (0.75, 0.4, 20.2))
    # Marcos de ventanas con frontón alterno (aire de Edad Moderna)
    def frame(x, z, w, h, y, pediment=0):
        t = 0.22
        add_box(trim, (x - w / 2 - t / 2, y - 0.12, z), (t, 0.3, h + 2 * t))
        add_box(trim, (x + w / 2 + t / 2, y - 0.12, z), (t, 0.3, h + 2 * t))
        add_box(trim, (x, y - 0.12, z + h / 2 + t / 2), (w + 2 * t, 0.3, t))
        add_box(trim, (x, y - 0.2, z - h / 2 - 0.1), (w + 0.6, 0.45, 0.18))
        if pediment == 1:
            for s in (-1, 1):
                add_box(trim, (x + s * (w / 4 + 0.15), y - 0.18, z + h / 2 + 0.55), (w / 2 + 0.55, 0.4, 0.16),
                        (0, s * 0.42, 0))
        elif pediment == 2:
            add_box(trim, (x, y - 0.2, z + h / 2 + 0.45), (w + 0.8, 0.45, 0.2))
    for x in xs:
        frame(x, PAL_FLOOR + 2.0, 1.5, 2.7, PAL_Y, 2)
        frame(x, PAL_FLOOR + 6.6, 1.5, 3.0, PAL_Y, 1)
        frame(x, PAL_FLOOR + 11.0, 1.3, 2.1, PAL_Y, 0)
    for x in (-4.0, 4.0):
        frame(x, PAL_FLOOR + 2.2, 1.4, 2.8, 53.5, 2)
    for x in (-4.0, 0.0, 4.0):
        frame(x, PAL_FLOOR + 8.2, 1.5, 3.4, 53.5, 1)
        frame(x, PAL_FLOOR + 13.4, 1.3, 2.4, 53.5, 0)
    # Arco de la puerta principal
    for i in range(13):
        a0, a1 = math.pi * i / 13, math.pi * (i + 1) / 13
        am = (a0 + a1) / 2
        rm = 1.8 + 0.35
        add_box(trim, (rm * math.cos(am), 53.25, PAL_FLOOR + 4.4 + rm * math.sin(am)),
                (0.7, 0.4, (a1 - a0) * rm * 0.95), (0, math.pi / 2 - am, 0))
    # Frontón triangular
    for s in (-1, 1):
        add_box(trim, (s * 3.45, 54.0, 22.0), (7.6, 1.0, 0.5), (0, s * 0.4, 0))
    # Parapeto almenado sobre la cornisa (toque medieval)
    for x0, x1 in ((-21.2, -6.9), (6.9, 21.2)):
        add_box(trim, ((x0 + x1) / 2, PAL_Y + 0.25, 16.6), (x1 - x0, 0.6, 0.9))
        x = x0 + 0.6
        r = random.Random(int(x0))
        while x < x1 - 0.4:
            if r.random() > 0.15:
                add_box(trim, (x, PAL_Y + 0.25, 17.55), (0.8, 0.6, 1.0 * r.uniform(0.7, 1.0)),
                        (0, r.uniform(-0.05, 0.05), 0))
            x += 1.6
    obj_from_bm('Palacio_molduras', trim, MAT['trim'])

    # Fondos oscuros y cristales rotos
    glass = bmesh.new()
    r = random.Random(5)
    panes = []
    for x in xs:
        for z, h in ((PAL_FLOOR + 2.0, 2.7), (PAL_FLOOR + 6.6, 3.0), (PAL_FLOOR + 11.0, 2.1)):
            panes.append((x, z, 1.5, h, PAL_Y + 0.25))
    for x in (-4.0, 0.0, 4.0):
        panes.append((x, PAL_FLOOR + 8.2, 1.5, 3.4, 53.75))
        panes.append((x, PAL_FLOOR + 13.4, 1.3, 2.4, 53.75))
    for (x, z, w, h, y) in panes:
        if r.random() < 0.55:
            # trozo de cristal irregular colgando en el marco
            for k in range(r.randint(1, 3)):
                cx = x + r.uniform(-w / 3, w / 3)
                cz = z + r.uniform(-h / 3, h / 3)
                pts = [glass.verts.new((cx + r.uniform(-0.4, 0.4), y + r.uniform(-0.02, 0.02),
                                        cz + r.uniform(-0.5, 0.5))) for _ in range(3)]
                glass.faces.new(pts)
            # parteluz y travesaño de madera
            add_box(glass, (x, y + 0.02, z), (0.06, 0.06, h * 0.98))
            add_box(glass, (x, y + 0.02, z + h * 0.15), (w * 0.98, 0.06, 0.06))
    obj_from_bm('Ventanas_restos', glass, [MAT['glass']])
    # Contraventanas tapiadas en algunas ventanas
    boards = bmesh.new()
    for (x, z, w, h, y) in panes:
        if r.random() < 0.2:
            for k in range(4):
                add_box(boards, (x, y - 0.32, z - h / 3 + k * h / 4.5), (w * 1.15, 0.05, 0.28),
                        (0, r.uniform(-0.25, 0.25), 0))
    obj_from_bm('Tablones', boards, MAT['wood'])

    # Tejado a cuatro aguas con un hueco hundido
    bm = bmesh.new()
    a = [bm.verts.new(p) for p in ((-21.6, 55.4, 16.2), (21.6, 55.4, 16.2), (21.6, 71.6, 16.2),
                                   (-21.6, 71.6, 16.2), (-13.5, 63.5, 23.0), (13.5, 63.5, 23.0))]
    bm.faces.new((a[0], a[1], a[5], a[4]))
    bm.faces.new((a[2], a[3], a[4], a[5]))
    bm.faces.new((a[1], a[2], a[5]))
    bm.faces.new((a[3], a[0], a[4]))
    bm.faces.new((a[0], a[3], a[2], a[1]))
    roof = obj_from_bm('Tejado', bm, MAT['slate'])
    hole = bmesh.new()
    vs = bmesh.ops.create_icosphere(hole, subdivisions=2, radius=3.2,
                                    matrix=Matrix.Translation((11.0, 58.5, 19.0)))['verts']
    for v in vs:
        v.co += v.co.normalized() * 0.0 + Vector((0, 0, 0))
        v.co.x += noise.noise(v.co * 0.7) * 0.9
        v.co.z += noise.noise(v.co * 0.9 + Vector((3, 0, 0))) * 0.7
    boolean_cut(roof, hole, MAT['void'])
    bm = bmesh.new()
    for i in range(6):  # vigas a la vista
        x = 8.6 + i * 0.95
        add_box(bm, (x, 59.3, 18.2), (0.18, 6.5, 0.22), (math.radians(-40 + i * 3), 0, math.radians(i * 2)))
    add_box(bm, (11.4, 57.8, 17.6), (0.2, 4.0, 0.2), (0.3, 0.6, 1.2))
    obj_from_bm('Vigas_rotas', bm, MAT['wood'])
    # Buhardillas y chimeneas
    bm = bmesh.new()
    sl = bmesh.new()
    for x in (-17.5, -11.5, 16.5):
        zb = 16.2 + (57.2 - 55.4) * 6.8 / 8.1
        add_box(bm, (x, 57.9, zb + 1.2), (1.9, 1.8, 2.6))
        for s in (-1, 1):
            add_box(sl, (x + s * 0.62, 58.0, zb + 2.95), (1.55, 2.3, 0.14), (0, s * 0.72, 0))
    for (x, y, hgt) in ((-15, 66, 5.5), (15, 66, 5.0), (-4.5, 68, 6.5), (4.5, 68, 4.2)):
        add_box(bm, (x, y, 20.5 + hgt / 2), (1.3, 2.4, hgt))
        add_box(bm, (x, y, 20.5 + hgt + 0.15), (1.6, 2.7, 0.3))
    dorm = obj_from_bm('Buhardillas_chimeneas', bm, MAT['palace'])
    cut = bmesh.new()
    for x in (-17.5, -11.5, 16.5):
        zb = 16.2 + (57.2 - 55.4) * 6.8 / 8.1
        add_box(cut, (x, 57.0, zb + 1.0), (0.9, 0.6, 1.4))
    boolean_cut(dorm, cut, MAT['void'])
    obj_from_bm('Buhardillas_tejado', sl, MAT['slate'])

    # Campanario detrás del frontón
    bm = bmesh.new()
    add_box(bm, (0, 64.0, 26.0), (7.0, 7.0, 11.0))
    bel = obj_from_bm('Campanario', bm, MAT['palace'])
    for axis in ('Y', 'X'):
        cut = bmesh.new()
        arch_prism(cut, 0, 64.0, 23.8, 28.2, 1.0, 9.0, axis=axis)
        boolean_cut(bel, cut, MAT['void'])
    bm = bmesh.new()
    a = [bm.verts.new(p) for p in ((-4.0, 60.0, 31.5), (4.0, 60.0, 31.5), (4.0, 68.0, 31.5), (-4.0, 68.0, 31.5),
                                   (0, 64.0, 38.5))]
    for i in range(4):
        bm.faces.new((a[i], a[(i + 1) % 4], a[4]))
    bm.faces.new((a[3], a[2], a[1], a[0]))
    obj_from_bm('Campanario_tejado', bm, MAT['slate'])
    bm = bmesh.new()
    add_box(bm, (0, 64.0, 31.6), (8.2, 8.2, 0.35))
    add_cyl(bm, (0, 64.0, 39.6), 0.05, 2.2, seg=6)
    add_cyl(bm, (0, 64.0, 39.0), 0.18, 0.4, seg=12, r2=0.05)
    obj_from_bm('Campanario_remate', bm, [MAT['iron']])

    # Torres circulares con tejado cónico
    for sx in (-1, 1):
        cx, cy = sx * 25.0, 58.5
        bm = bmesh.new()
        add_cyl(bm, (cx, cy, 12.0), 4.6, 26.0, seg=40)
        tw = obj_from_bm('Torre_redonda_%s' % ('izq' if sx < 0 else 'der'), bm, MAT['palace'])
        cut = bmesh.new()
        for z in (6.0, 11.5, 17.0):
            for ang in (-1.25, -1.95):
                a = ang if sx > 0 else math.pi - ang
                a = math.atan2(math.sin(ang), math.cos(ang) * sx)
                px, py = cx + 4.6 * math.cos(a), cy + 4.6 * math.sin(a)
                add_box(cut, (px, py, z), (0.9, 1.6, 1.8), (0, 0, a + math.pi / 2))
        boolean_cut(tw, cut, MAT['void'])
        bm = bmesh.new()
        for i in range(30):
            a = TAU * i / 30
            add_box(bm, (cx + 4.75 * math.cos(a), cy + 4.75 * math.sin(a), 22.7), (0.4, 0.55, 0.9),
                    (0, 0, a + math.pi / 2))
        add_cyl(bm, (cx, cy, 24.0), 5.15, 2.0, seg=40)
        add_cyl(bm, (cx, cy, 25.15), 5.35, 0.3, seg=40)
        obj_from_bm('Torre_matacan_%d' % sx, bm, MAT['trim'])
        bm = bmesh.new()
        add_cyl(bm, (cx, cy, 25.3 + 6.0), 5.6, 12.0, seg=40, r2=0.05)
        add_cyl(bm, (cx, cy, 38.0), 0.04, 2.5, seg=6)
        obj_from_bm('Torre_cono_%d' % sx, bm, MAT['slate'])

    # Escalinata rota
    bm = bmesh.new()
    r = random.Random(9)
    for i in range(7):
        y0 = 53.4 - (7 - i) * 0.42
        hgt = 0.22 * (i + 1)
        for seg in range(5):
            x = -4.5 + seg * 1.8 + 0.9
            drop = r.uniform(0, 0.04) + (0.15 if r.random() < 0.1 else 0)
            add_box(bm, (x, (y0 + 53.4) / 2, (hgt - drop) / 2 - 0.2),
                    (1.78, 53.4 - y0, hgt + 0.4 - drop),
                    (r.uniform(-0.012, 0.012), r.uniform(-0.012, 0.012), r.uniform(-0.01, 0.01)))
    add_box(bm, (0, 54.6, PAL_FLOOR / 2 - 0.2), (9.2, 2.5, PAL_FLOOR + 0.4))
    for s in (-1, 1):
        add_box(bm, (s * 5.0, 51.3, 0.5), (0.8, 4.4, 1.6))
        add_box(bm, (s * 5.0, 49.4, 1.55), (1.0, 1.0, 0.5))
    obj_from_bm('Escalinata', bm, MAT['trim'])
    bm = bmesh.new()
    vs = bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=0.45,
                                   matrix=Matrix.Translation((-5.0, 49.4, 2.25)))
    add_cyl(bm, (-5.0, 49.4, 1.95), 0.18, 0.3, seg=12)
    # jarrón caído
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=0.45,
                              matrix=Matrix.Translation((6.3, 48.6, 0.3)) @ Matrix.Rotation(1.2, 4, 'X'))
    obj_from_bm('Jarrones', bm, MAT['trim'], smooth=True)
    # Puerta principal destrozada
    bm = bmesh.new()
    for i in range(4):
        add_box(bm, (-1.3 + i * 0.42, 54.0 + i * 0.12, PAL_FLOOR + 2.4), (0.4, 0.08, 4.4 - (1.2 if i == 3 else 0)),
                (0, 0, 0.35))
    obj_from_bm('Puerta_palacio', bm, MAT['wood'])
    return main


# ---------------------------------------------------------------------------
# Elementos del patio
# ---------------------------------------------------------------------------
def build_courtyard():
    # Fuente seca y medio derruida
    fx, fy = -11.0, 31.0
    bm = bmesh.new()
    add_cyl(bm, (fx, fy, 0.3), 3.2, 1.0, seg=48)
    basin = obj_from_bm('Fuente', bm, MAT['trim'])
    cut = bmesh.new()
    add_cyl(cut, (fx, fy, 0.75), 2.85, 1.0, seg=48)
    boolean_cut(basin, cut, MAT['trim'])
    cut = bmesh.new()
    add_box(cut, (fx + 3.0, fy - 0.6, 0.85), (1.6, 1.2, 0.6), (0, 0, 0.3))  # trozo roto del borde
    boolean_cut(basin, cut, MAT['trim'])
    bm = bmesh.new()
    add_cyl(bm, (fx, fy, 1.1), 0.38, 2.2, seg=16)
    add_cyl(bm, (fx, fy, 2.25), 0.9, 0.25, seg=24, r2=0.5)
    obj_from_bm('Fuente_columna', bm, MAT['trim'])
    bm = bmesh.new()
    add_cyl(bm, (fx, fy, 0.48), 2.85, 0.02, seg=48)
    obj_from_bm('Fuente_agua', bm, MAT['water'])
    # Pedestal con columna rota y fustes caídos
    bm = bmesh.new()
    add_box(bm, (10.5, 39.0, 0.6), (1.6, 1.6, 1.6))
    add_cyl(bm, (10.5, 39.0, 2.6), 0.42, 2.6, seg=20)
    add_cyl(bm, (13.0, 34.5, 0.38), 0.42, 2.4, seg=20, rot=(math.pi / 2, 0, 0.6))
    add_cyl(bm, (14.8, 33.2, 0.36), 0.42, 1.3, seg=20, rot=(math.pi / 2, 0.1, 1.2))
    obj_from_bm('Columnas', bm, MAT['trim'], smooth=False)
    # Valla de madera rota a lo largo del camino exterior
    bm = bmesh.new()
    r = random.Random(3)
    for side in (-1, 1):
        y = -38.0
        while y < -6:
            x = side * (3.6 + r.uniform(-0.15, 0.15))
            if r.random() > 0.15:
                lean = (r.uniform(-0.12, 0.12), r.uniform(-0.15, 0.15), 0)
                add_box(bm, (x, y, ground_h(x, y) + 0.55), (0.14, 0.14, 1.3), lean)
            if r.random() > 0.35:
                for zz in (0.45, 0.95):
                    add_box(bm, (x, y + 1.25, ground_h(x, y) + zz + r.uniform(-0.1, 0.1)), (0.06, 2.5, 0.12),
                            (r.uniform(-0.1, 0.1), 0, r.uniform(-0.04, 0.04)))
            y += 2.5
    # Tablones y escombros de madera cerca de la puerta
    for i in range(6):
        add_box(bm, (r.uniform(-2.0, 2.0), r.uniform(4.5, 9.0), 0.08), (0.25, r.uniform(1.2, 2.4), 0.05),
                (0, r.uniform(-0.1, 0.1), r.uniform(0, math.pi)))
    obj_from_bm('Valla_tablones', bm, MAT['wood'])


def build_rubble():
    bm = bmesh.new()
    r = random.Random(21)
    spots = []
    for _ in range(140):  # al pie de la muralla y de las brechas
        side = r.choice((-1, 1))
        x = side * r.uniform(7.5, 44)
        y = r.choice((-1, 1)) * r.uniform(1.8, 5.0)
        spots.append((x, y, r.uniform(0.15, 0.6)))
    for _ in range(60):  # en el patio
        x = r.choice((-1, 1)) * r.uniform(2.6, 20)
        y = r.uniform(6, 50)
        spots.append((x, y, r.uniform(0.1, 0.45)))
    for _ in range(45):  # frente al palacio
        x = r.uniform(-22, 22)
        if abs(x) < 5.5:
            continue
        spots.append((x, r.uniform(50.5, 55.5), r.uniform(0.15, 0.55)))
    for (x, y, s) in spots:
        vs = bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)['verts']
        seed = Vector((x, y, s))
        sc = Vector((s * r.uniform(0.9, 1.6), s * r.uniform(0.8, 1.3), s * r.uniform(0.5, 0.9)))
        rot = Euler((r.uniform(0, 3), r.uniform(0, 3), r.uniform(0, 3))).to_matrix()
        for v in vs:
            d = noise.noise(v.co * 1.3 + seed) * 0.35
            p = v.co * (1 + d)
            p = rot @ Vector((p.x * sc.x, p.y * sc.y, p.z * sc.z))
            v.co = p + Vector((x, y, ground_h(x, y) + sc.z * 0.35))
    obj_from_bm('Escombros', bm, MAT['rock'], smooth=True)


# ---------------------------------------------------------------------------
# Vegetación
# ---------------------------------------------------------------------------
VEG = bpy.data.collections.new('Vegetacion_fuentes')
ROOT.children.link(VEG)


def hidden_coll(name):
    c = bpy.data.collections.new(name)
    VEG.children.link(c)
    return c


def blade(bm, base, height, lean_dir, lean, width, segs=4, curl=0.0):
    pts = []
    for i in range(segs + 1):
        t = i / segs
        bend = lean * t * t
        p = Vector(base) + Vector((lean_dir.x * bend, lean_dir.y * bend, height * t * (1 - 0.15 * lean * t)))
        w = width * (1 - t) ** 0.8
        side = Vector((-lean_dir.y, lean_dir.x, 0)) * (w / 2)
        pts.append((bm.verts.new(p + side), bm.verts.new(p - side)))
    for i in range(segs):
        a, b = pts[i], pts[i + 1]
        bm.faces.new((a[0], a[1], b[1], b[0]))


def make_grass_variants():
    coll = hidden_coll('Hierba_variantes')
    r = random.Random(11)
    for k in range(5):
        bm = bmesh.new()
        tall = k >= 3
        nb = 14 if not tall else 9
        for _ in range(nb):
            ang = r.uniform(0, TAU)
            d = Vector((math.cos(ang), math.sin(ang), 0))
            base = (r.uniform(-0.06, 0.06), r.uniform(-0.06, 0.06), -0.02)
            h = r.uniform(0.25, 0.55) if not tall else r.uniform(0.6, 1.0)
            blade(bm, base, h, d, r.uniform(0.05, 0.3) * h, r.uniform(0.008, 0.016))
        ob = obj_from_bm('hierba_%d' % k, bm, MAT['grass'], coll=coll)
    # flores silvestres (colección aparte, mucho más dispersas)
    global FLOWER_COLL
    FLOWER_COLL = hidden_coll('Flores')
    for k, mname in enumerate(('flower_w', 'flower_y', 'flower_p')):
        bm = bmesh.new()
        for _ in range(3):
            ang = r.uniform(0, TAU)
            d = Vector((math.cos(ang), math.sin(ang), 0))
            h = r.uniform(0.35, 0.6)
            base = Vector((r.uniform(-0.05, 0.05), r.uniform(-0.05, 0.05), 0))
            blade(bm, base, h, d, 0.05, 0.006, segs=3)
        head = bmesh.new()
        for _ in range(3):
            ang = r.uniform(0, TAU)
            bmesh.ops.create_icosphere(head, subdivisions=1, radius=0.025,
                                       matrix=Matrix.Translation((math.cos(ang) * 0.04, math.sin(ang) * 0.04,
                                                                  r.uniform(0.38, 0.6))))
        me = bpy.data.meshes.new('tmp')
        head.to_mesh(me)
        head.free()
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
        ob = obj_from_bm('flor_%d' % k, bm, [MAT['grass'], MAT[mname]], coll=FLOWER_COLL)
        # las caras de la cabeza (últimas) con material de flor
        n_head = 3 * 20
        for p in ob.data.polygons[-n_head:]:
            p.material_index = 1
    coll.hide_render = False
    return coll


def leaf_geom(bm, center, normal, size, r):
    """Hoja sencilla con nervio central doblado."""
    z = normal.normalized()
    t = z.orthogonal().normalized()
    t.rotate(Matrix.Rotation(r.uniform(0, TAU), 3, z))
    b = z.cross(t)
    c = Vector(center)
    tip = c + t * size
    base = c - t * size * 0.15
    l = c + t * size * 0.4 + b * size * 0.32 - z * size * 0.08
    rr = c + t * size * 0.4 - b * size * 0.32 - z * size * 0.08
    vb, vl, vt, vr = (bm.verts.new(p) for p in (base, l, tip, rr))
    bm.faces.new((vb, vl, vt))
    bm.faces.new((vb, vt, vr))


def make_leaf_clumps():
    coll = hidden_coll('Hojas_racimos')
    r = random.Random(17)
    for k in range(3):
        bm = bmesh.new()
        for _ in range(70):
            p = Vector((r.gauss(0, 1), r.gauss(0, 1), r.gauss(0, 0.8))).normalized() * (r.random() ** 0.5) * 0.55
            leaf_geom(bm, p, Vector((r.uniform(-1, 1), r.uniform(-1, 1), r.uniform(0.2, 1))), r.uniform(0.07, 0.11), r)
        obj_from_bm('racimo_%d' % k, bm, MAT['leaf'], coll=coll)
    return coll


def make_ivy_leaves():
    coll = hidden_coll('Hiedra_hojas')
    r = random.Random(23)
    for k in range(3):
        bm = bmesh.new()
        for _ in range(4):
            p = Vector((r.uniform(-0.08, 0.08), r.uniform(-0.08, 0.08), 0.03 + r.uniform(0, 0.03)))
            leaf_geom(bm, p, Vector((r.uniform(-0.3, 0.3), r.uniform(-0.3, 0.3), 1)), r.uniform(0.05, 0.08), r)
        obj_from_bm('hiedra_%d' % k, bm, MAT['ivy'], coll=coll)
    return coll


def gn_scatter(name, target, inst_coll, density, seed, smin, smax, prob_fn=None, align=False,
               tilt=0.15, nvariants=3):
    ng = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    ng.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    nt = ng
    gi = nt.nodes.new('NodeGroupInput')
    go = nt.nodes.new('NodeGroupOutput')
    dist = node(nt, 'GeometryNodeDistributePointsOnFaces', distribute_method='RANDOM')
    nt.links.new(gi.outputs[0], dist.inputs['Mesh'])
    dist.inputs['Density'].default_value = density
    dist.inputs['Seed'].default_value = seed
    pts = dist.outputs['Points']
    if prob_fn is not None:
        prob = prob_fn(nt)
        rv = node(nt, 'FunctionNodeRandomValue', data_type='FLOAT')
        rv.inputs[8].default_value = seed + 1
        cmp = node(nt, 'FunctionNodeCompare', data_type='FLOAT', operation='GREATER_EQUAL')
        nt.links.new(rv.outputs[1], cmp.inputs[0])
        setin(nt, cmp.inputs[1], prob)
        dl = node(nt, 'GeometryNodeDeleteGeometry', domain='POINT')
        nt.links.new(pts, dl.inputs[0])
        nt.links.new(cmp.outputs[0], dl.inputs[1])
        pts = dl.outputs[0]
    iop = nt.nodes.new('GeometryNodeInstanceOnPoints')
    nt.links.new(pts, iop.inputs['Points'])
    ci = nt.nodes.new('GeometryNodeCollectionInfo')
    ci.inputs['Collection'].default_value = inst_coll
    ci.inputs['Separate Children'].default_value = True
    ci.inputs['Reset Children'].default_value = True
    nt.links.new(ci.outputs[0], iop.inputs['Instance'])
    iop.inputs['Pick Instance'].default_value = True
    ri = node(nt, 'FunctionNodeRandomValue', data_type='INT')
    ri.inputs[4].default_value = 0
    ri.inputs[5].default_value = nvariants - 1
    ri.inputs[8].default_value = seed + 2
    nt.links.new(ri.outputs[2], iop.inputs['Instance Index'])
    rr = node(nt, 'FunctionNodeRandomValue', data_type='FLOAT_VECTOR')
    rr.inputs[0].default_value = (-tilt, -tilt, 0)
    rr.inputs[1].default_value = (tilt, tilt, TAU)
    rr.inputs[8].default_value = seed + 3
    e2r = nt.nodes.new('FunctionNodeEulerToRotation')
    nt.links.new(rr.outputs[0], e2r.inputs[0])
    if align:
        al = node(nt, 'FunctionNodeAlignRotationToVector', axis='Z')
        nt.links.new(dist.outputs['Normal'], al.inputs['Vector'])
        rot = node(nt, 'FunctionNodeRotateRotation', rotation_space='LOCAL')
        nt.links.new(al.outputs[0], rot.inputs[0])
        nt.links.new(e2r.outputs[0], rot.inputs[1])
        nt.links.new(rot.outputs[0], iop.inputs['Rotation'])
    else:
        nt.links.new(e2r.outputs[0], iop.inputs['Rotation'])
    rs = node(nt, 'FunctionNodeRandomValue', data_type='FLOAT')
    rs.inputs[2].default_value = smin
    rs.inputs[3].default_value = smax
    rs.inputs[8].default_value = seed + 4
    nt.links.new(rs.outputs[1], iop.inputs['Scale'])
    j = nt.nodes.new('GeometryNodeJoinGeometry')
    nt.links.new(gi.outputs[0], j.inputs[0])
    nt.links.new(iop.outputs[0], j.inputs[0])
    nt.links.new(j.outputs[0], go.inputs[0])
    if target is not None:
        mod = target.modifiers.new(name, 'NODES')
        mod.node_group = ng
    return ng


def grass_prob(nt):
    pos = nt.nodes.new('GeometryNodeInputPosition')
    sp = nt.nodes.new('ShaderNodeSeparateXYZ')
    nt.links.new(pos.outputs[0], sp.inputs[0])
    ax = M(nt, 'ABSOLUTE', sp.outputs[0])
    edge = MAPR(nt, ax, 1.75, 2.9, interp='SMOOTHSTEP')
    inside = M(nt, 'MULTIPLY', MAPR(nt, sp.outputs[1], -36, -30), MAPR(nt, sp.outputs[1], 76, 70))
    inside = M(nt, 'MULTIPLY', inside, MAPR(nt, ax, 50, 44))
    tunnel = M(nt, 'GREATER_THAN', M(nt, 'ABSOLUTE', sp.outputs[1]), 3.8)
    nz = NOISE(nt, pos.outputs[0], scale=0.12, detail=3)
    patch = MAPR(nt, nz.outputs[0], 0.35, 0.6, 0.35, 1.0)
    p = M(nt, 'MULTIPLY', M(nt, 'MULTIPLY', edge, inside), M(nt, 'MULTIPLY', tunnel, patch))
    return p


def ivy_prob(nt):
    pos = nt.nodes.new('GeometryNodeInputPosition')
    nrm = nt.nodes.new('GeometryNodeInputNormal')
    sp = nt.nodes.new('ShaderNodeSeparateXYZ')
    nt.links.new(pos.outputs[0], sp.inputs[0])
    sn = nt.nodes.new('ShaderNodeSeparateXYZ')
    nt.links.new(nrm.outputs[0], sn.inputs[0])
    vertical = MAPR(nt, M(nt, 'ABSOLUTE', sn.outputs[2]), 0.6, 0.3)
    nz = NOISE(nt, pos.outputs[0], scale=0.16, detail=5, rough=0.6)
    patch = MAPR(nt, nz.outputs[0], 0.5, 0.62)
    low = MAPR(nt, sp.outputs[2], 14.0, 2.0, 0.35, 1.0)
    return M(nt, 'MULTIPLY', M(nt, 'MULTIPLY', vertical, patch), low)


def build_tree(name, base, height, seed, leafy=True, lean=0.0):
    r = random.Random(seed)
    bm = bmesh.new()
    tips = []

    def branch(p, d, length, rad, depth):
        segs = 5
        ring_prev = None
        cur = Vector(p)
        dd = Vector(d).normalized()
        for s in range(segs + 1):
            t = s / segs
            rr = rad * (1 - 0.65 * t)
            z = dd
            x = z.orthogonal().normalized()
            y = z.cross(x)
            ring = [bm.verts.new(cur + (x * math.cos(a) + y * math.sin(a)) * rr * (1 + 0.15 * noise.noise(cur * 3 + Vector((a, 0, 0)))))
                    for a in [TAU * k / 7 for k in range(7)]]
            if ring_prev:
                for k in range(7):
                    bm.faces.new((ring_prev[k], ring_prev[(k + 1) % 7], ring[(k + 1) % 7], ring[k]))
            ring_prev = ring
            if s < segs:
                jitter = Vector((r.uniform(-1, 1), r.uniform(-1, 1), r.uniform(-0.3, 0.6))) * 0.28
                dd = (dd + jitter).normalized()
                cur = cur + dd * (length / segs)
        if depth == 0 or rad < 0.02:
            tips.append(cur.copy())
            return
        n = r.randint(2, 3)
        for i in range(n):
            ang = r.uniform(0, TAU)
            side = Vector((math.cos(ang), math.sin(ang), r.uniform(0.2, 0.9)))
            nd = (dd * 0.6 + side.normalized() * 0.8).normalized()
            branch(cur, nd, length * r.uniform(0.55, 0.75), rad * 0.62, depth - 1)
        if r.random() < 0.6:
            branch(cur, dd, length * 0.7, rad * 0.7, depth - 1)

    branch(Vector(base), Vector((lean, 0, 1)), height * 0.42, height * 0.035, 4 if leafy else 4)
    tree = obj_from_bm(name, bm, MAT['bark'], smooth=True)
    if leafy and tips:
        bm = bmesh.new()
        for t in tips:
            bm.verts.new(t)
        me = bpy.data.meshes.new(name + '_puntas')
        bm.to_mesh(me)
        bm.free()
        pt = link(bpy.data.objects.new(name + '_hojas', me))
        ng = bpy.data.node_groups.get('copa')
        if ng is None:
            ng = bpy.data.node_groups.new('copa', 'GeometryNodeTree')
            ng.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
            ng.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
            gi = ng.nodes.new('NodeGroupInput')
            go = ng.nodes.new('NodeGroupOutput')
            m2p = ng.nodes.new('GeometryNodeMeshToPoints')
            ng.links.new(gi.outputs[0], m2p.inputs[0])
            iop = ng.nodes.new('GeometryNodeInstanceOnPoints')
            ng.links.new(m2p.outputs[0], iop.inputs['Points'])
            ci = ng.nodes.new('GeometryNodeCollectionInfo')
            ci.inputs['Collection'].default_value = LEAF_COLL
            ci.inputs['Separate Children'].default_value = True
            ci.inputs['Reset Children'].default_value = True
            iop.inputs['Pick Instance'].default_value = True
            ng.links.new(ci.outputs[0], iop.inputs['Instance'])
            rr = node(ng, 'FunctionNodeRandomValue', data_type='FLOAT_VECTOR')
            rr.inputs[1].default_value = (TAU, TAU, TAU)
            e2r = ng.nodes.new('FunctionNodeEulerToRotation')
            ng.links.new(rr.outputs[0], e2r.inputs[0])
            ng.links.new(e2r.outputs[0], iop.inputs['Rotation'])
            rs = node(ng, 'FunctionNodeRandomValue', data_type='FLOAT')
            rs.inputs[2].default_value = 1.2
            rs.inputs[3].default_value = 2.2
            ng.links.new(rs.outputs[1], iop.inputs['Scale'])
            ri = node(ng, 'FunctionNodeRandomValue', data_type='INT')
            ri.inputs[5].default_value = 2
            ng.links.new(ri.outputs[2], iop.inputs['Instance Index'])
            ng.links.new(iop.outputs[0], go.inputs[0])
        pt.modifiers.new('copa', 'NODES').node_group = ng
    return tree


def build_bush(name, center, radius, seed):
    r = random.Random(seed)
    bm = bmesh.new()
    for _ in range(int(40 * radius)):
        p = Vector((r.gauss(0, 1), r.gauss(0, 1), abs(r.gauss(0, 0.8)))).normalized() * (r.random() ** 0.4) * radius
        p.z *= 0.75
        bm.verts.new(Vector(center) + p)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = link(bpy.data.objects.new(name, me))
    ob.modifiers.new('copa', 'NODES').node_group = bpy.data.node_groups['copa']
    return ob


def build_far_forest():
    coll = hidden_coll('Arboles_lejanos')
    r = random.Random(31)
    for k in range(3):
        bm = bmesh.new()
        add_cyl(bm, (0, 0, 2.5), 0.4, 5.0, seg=6)
        for _ in range(7):
            c = Vector((r.uniform(-2, 2), r.uniform(-2, 2), r.uniform(5, 10)))
            vs = bmesh.ops.create_icosphere(bm, subdivisions=2, radius=r.uniform(2.0, 3.5),
                                            matrix=Matrix.Translation(c))['verts']
            for v in vs:
                v.co += (v.co - c).normalized() * noise.noise(v.co * 0.8) * 0.8
        obj_from_bm('arbol_lejano_%d' % k, bm, MAT['farleaf'], coll=coll)
    bm = bmesh.new()
    for _ in range(1600):
        ang = r.uniform(0, TAU)
        d = r.uniform(85, 320)
        x, y = math.cos(ang) * d, 25 + math.sin(ang) * d
        if -60 < y < 0 and abs(x) < 50:
            continue
        rr = math.hypot(x, y - 25)
        h = -0.4
        h += (rr - 70) * 0.05 * (0.5 + 0.5 * (noise.noise(Vector((x * 0.006, y * 0.006, 9.0))) + 1))
        h += noise.noise(Vector((x * 0.02, y * 0.02, 3.0))) * 4.0 * min(1, (rr - 70) / 100)
        bm.verts.new((x, y, h - 0.5))
    me = bpy.data.meshes.new('bosque_puntos')
    bm.to_mesh(me)
    bm.free()
    ob = link(bpy.data.objects.new('Bosque_lejano', me))
    ng = bpy.data.node_groups.new('bosque', 'GeometryNodeTree')
    ng.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    gi = ng.nodes.new('NodeGroupInput')
    go = ng.nodes.new('NodeGroupOutput')
    m2p = ng.nodes.new('GeometryNodeMeshToPoints')
    ng.links.new(gi.outputs[0], m2p.inputs[0])
    iop = ng.nodes.new('GeometryNodeInstanceOnPoints')
    ng.links.new(m2p.outputs[0], iop.inputs['Points'])
    ci = ng.nodes.new('GeometryNodeCollectionInfo')
    ci.inputs['Collection'].default_value = coll
    ci.inputs['Separate Children'].default_value = True
    ci.inputs['Reset Children'].default_value = True
    iop.inputs['Pick Instance'].default_value = True
    ng.links.new(ci.outputs[0], iop.inputs['Instance'])
    rr = node(ng, 'FunctionNodeRandomValue', data_type='FLOAT_VECTOR')
    rr.inputs[1].default_value = (0, 0, TAU)
    e2r = ng.nodes.new('FunctionNodeEulerToRotation')
    ng.links.new(rr.outputs[0], e2r.inputs[0])
    ng.links.new(e2r.outputs[0], iop.inputs['Rotation'])
    rs = node(ng, 'FunctionNodeRandomValue', data_type='FLOAT')
    rs.inputs[2].default_value = 1.0
    rs.inputs[3].default_value = 2.0
    ng.links.new(rs.outputs[1], iop.inputs['Scale'])
    ri = node(ng, 'FunctionNodeRandomValue', data_type='INT')
    ri.inputs[5].default_value = 2
    ng.links.new(ri.outputs[2], iop.inputs['Instance Index'])
    ng.links.new(iop.outputs[0], go.inputs[0])
    ob.modifiers.new('bosque', 'NODES').node_group = ng


# ---------------------------------------------------------------------------
# Construcción
# ---------------------------------------------------------------------------
ground = build_ground()
walls = build_walls()
door_L, door_R = build_gate_doors()
palace = build_palace()
build_courtyard()
build_rubble()

GRASS_COLL = make_grass_variants()
LEAF_COLL = make_leaf_clumps()
IVY_COLL = make_ivy_leaves()

gn_scatter('hierba', ground, GRASS_COLL, density=55.0, seed=1, smin=0.7, smax=1.35, prob_fn=grass_prob,
           tilt=0.2, nvariants=5)
gn_scatter('flores', ground, FLOWER_COLL, density=0.8, seed=9, smin=0.8, smax=1.2, prob_fn=grass_prob,
           tilt=0.15, nvariants=3)
for obname in ('Muralla', 'Torre_puerta', 'Palacio_cuerpo', 'Palacio_pabellon', 'Torre_redonda_izq',
               'Torre_redonda_der', 'Torres_esquina'):
    ob = bpy.data.objects[obname]
    gn_scatter('hiedra_' + obname, ob, IVY_COLL, density=650.0, seed=hash(obname) % 997, smin=0.8, smax=1.4,
               prob_fn=ivy_prob, align=True, tilt=0.5, nvariants=3)

# Árboles
build_tree('Arbol_seco_1', (-8.5, -9.0, ground_h(-8.5, -9.0) - 0.2), 9.0, 5, leafy=False, lean=0.15)
build_tree('Arbol_seco_2', (17.0, 22.0, ground_h(17, 22) - 0.2), 11.0, 8, leafy=False, lean=-0.1)
build_tree('Arbol_1', (-19.0, 18.0, ground_h(-19, 18) - 0.2), 12.0, 13, leafy=True)
build_tree('Arbol_2', (24.0, 44.0, ground_h(24, 44) - 0.2), 13.0, 19, leafy=True, lean=0.05)
build_tree('Arbol_3', (12.0, -16.0, ground_h(12, -16) - 0.2), 10.0, 29, leafy=True, lean=-0.1)
build_tree('Arbol_4', (-30.0, 50.0, ground_h(-30, 50) - 0.2), 12.0, 37, leafy=True)
r = random.Random(41)
for i in range(26):
    side = r.choice((-1, 1))
    x = side * r.uniform(3.2, 30)
    y = r.uniform(-30, 52)
    if abs(y) < 5 or (abs(x) < 26 and 52 < y):
        continue
    build_bush('Arbusto_%d' % i, (x, y, ground_h(x, y)), r.uniform(0.6, 1.6), i)
for (x, y, s) in ((-5.5, 51.0, 1.2), (6.0, 52.0, 1.0), (-9.0, 54.5, 1.3), (13.0, 54.5, 1.1),
                  (-38, 2.5, 1.5), (30, 3.0, 1.3), (-5.0, 7.0, 0.6), (5.2, -6.5, 0.7)):
    build_bush('Arbusto_e_%d_%d' % (x, y), (x, y, ground_h(x, y)), s, int(x * 7 + y))
build_far_forest()
VEG.hide_render = True
for c in VEG.children:
    c.hide_render = True


# ---------------------------------------------------------------------------
# Cuervos sobrevolando el campanario
# ---------------------------------------------------------------------------
def build_crows():
    birds = []
    r = random.Random(77)
    for i in range(5):
        bm = bmesh.new()
        add_box(bm, (0, 0, 0), (0.12, 0.45, 0.12))
        body = obj_from_bm('Cuervo_%d' % i, bm, MAT['bird'])
        wings = []
        for s in (-1, 1):
            bm = bmesh.new()
            v = [bm.verts.new(p) for p in ((0, 0.12, 0), (s * 0.55, 0.0, 0), (s * 0.5, -0.18, 0), (0, -0.1, 0))]
            bm.faces.new(v)
            w = obj_from_bm('Cuervo_%d_ala_%d' % (i, s), bm, MAT['bird'])
            w.parent = body
            wings.append((w, s))
        birds.append((body, wings, r.uniform(14, 24), r.uniform(33, 42), r.uniform(0, TAU),
                      r.choice((-1, 1)) * r.uniform(0.18, 0.3), r.uniform(4.0, 5.0)))
    return birds


birds = build_crows()


# ---------------------------------------------------------------------------
# Luz: cielo físico + sol bajo de atardecer + bruma volumétrica
# ---------------------------------------------------------------------------
world = bpy.data.worlds.new('Cielo')
scene.world = world
world.use_nodes = True
wnt = world.node_tree
wnt.nodes.clear()
sky = node(wnt, 'ShaderNodeTexSky', sky_type='MULTIPLE_SCATTERING')
SUN_ELEV = math.radians(24.0)
SUN_AZ = math.radians(-115.0)   # sol a la izquierda y algo por detrás de la cámara
sky.sun_elevation = SUN_ELEV
sky.sun_rotation = SUN_AZ
sky.sun_disc = False
sky.air_density = 1.2
sky.aerosol_density = 2.0
bg = wnt.nodes.new('ShaderNodeBackground')
bg.inputs['Strength'].default_value = 0.22
wnt.links.new(sky.outputs[0], bg.inputs['Color'])
wo = wnt.nodes.new('ShaderNodeOutputWorld')
wnt.links.new(bg.outputs[0], wo.inputs['Surface'])

sun_data = bpy.data.lights.new('Sol', 'SUN')
sun_data.energy = 4.8
sun_data.color = (1.0, 0.80, 0.58)
sun_data.angle = math.radians(1.2)
sun = link(bpy.data.objects.new('Sol', sun_data))
sdir = Vector((math.sin(SUN_AZ) * math.cos(SUN_ELEV) * -1, math.cos(SUN_AZ) * math.cos(SUN_ELEV) * -1,
               -math.sin(SUN_ELEV)))
# dirección en que viaja la luz: desde atrás-izquierda hacia delante-derecha
h_dir = Vector((0.80, 0.60, 0.0)).normalized() * math.cos(SUN_ELEV)
sdir = Vector((h_dir.x, h_dir.y, -math.sin(SUN_ELEV))).normalized()
sun.rotation_euler = sdir.to_track_quat('-Z', 'Y').to_euler()

fogm, fnt, fout = new_mat('Bruma')
vol = fnt.nodes.new('ShaderNodeVolumePrincipled')
setin(fnt, vol.inputs['Color'], (0.92, 0.88, 0.82))
vol.inputs['Density'].default_value = 0.006
vol.inputs['Anisotropy'].default_value = 0.55
fnt.links.new(vol.outputs[0], fout.inputs['Volume'])
bm = bmesh.new()
add_box(bm, (0, 60, 28), (400, 360, 60))
fog = obj_from_bm('Bruma', bm, fogm)
fog.visible_shadow = True


# ---------------------------------------------------------------------------
# Cámara: paseo a pie con balanceo sinusoidal
# ---------------------------------------------------------------------------
cam_data = bpy.data.cameras.new('Camara')
cam_data.lens = 22.0
cam_data.sensor_width = 36.0
cam_data.sensor_fit = 'HORIZONTAL'
cam_data.clip_end = 2000
cam = link(bpy.data.objects.new('Camara', cam_data))
scene.camera = cam
cam.rotation_mode = 'XYZ'

Y_START = -14.0
V0 = 1.75
STEP_HZ = 1.85


def speed(t):
    if t < 0.6:
        return V0 * (0.85 + 0.15 * t / 0.6)
    if t > 16.5:
        u = min(1.0, (t - 16.5) / 5.0)
        return V0 * (1 - (3 * u * u - 2 * u * u * u))
    return V0


def smooth(a, b, x):
    u = min(1.0, max(0.0, (x - a) / (b - a)))
    return u * u * (3 - 2 * u)


dt = 1.0 / (FPS * 20)
t = 0.0
s = 0.0
phase = 0.0
samples = {}
steps = []
next_frame = 0
prev_phase = 0.0
while next_frame < FRAMES:
    ft = next_frame / FPS
    if t >= ft - 1e-9:
        samples[next_frame] = (s, phase, speed(t))
        next_frame += 1
    v = speed(t)
    s += v * dt
    prev_phase = phase
    phase += TAU * STEP_HZ * (v / V0) ** 0.6 * dt
    if int(prev_phase / TAU) != int(phase / TAU) and v > 0.15:
        steps.append({'t': round(t, 4), 'lado': 'izq' if len(steps) % 2 == 0 else 'der',
                      'y': round(Y_START + s, 3), 'fuerza': round(min(1.0, v / V0), 3)})
    t += dt

door_curve = []
for f in range(FRAMES):
    tt = f / FPS
    s_, ph, v = samples[f]
    amp = min(1.0, v / V0)
    y = Y_START + s_
    bob = -0.042 * amp * math.cos(ph)
    sway = 0.028 * amp * math.sin(ph / 2)
    zc = ground_h(0, y) + 1.66 + bob
    cam.location = (sway, y, zc)
    # objetivo de la mirada
    ahead = Vector((0.0, y + 14.0, 1.9 + 3.2 * (1 - smooth(-9, -4.5, y))))
    palace_pt = Vector((0.0, 56.0, 11.5))
    look = ahead.lerp(palace_pt, smooth(1.5, 24.0, y) * 0.85)
    glance = math.exp(-((tt - 12.8) / 1.5) ** 2)
    look.x += -7.0 * glance
    direction = look - Vector(cam.location)
    q = direction.to_track_quat('-Z', 'Y')
    e = q.to_euler()
    m = q.to_matrix()
    roll = math.radians(0.55) * amp * math.sin(ph / 2)
    pitch = math.radians(0.35) * amp * math.sin(ph)
    rotm = m @ Matrix.Rotation(pitch, 3, 'X') @ Matrix.Rotation(roll, 3, 'Z')
    cam.rotation_euler = rotm.to_euler('XYZ', cam.rotation_euler)
    cam.keyframe_insert('location', frame=f + 1)
    cam.keyframe_insert('rotation_euler', frame=f + 1)
    # puerta derecha meciéndose con el viento
    ang = math.radians(58 + 4.0 * math.sin(TAU * tt / 4.3) + 1.5 * math.sin(TAU * tt / 1.7 + 1.0))
    door_R.rotation_euler = (0, 0, ang)
    door_R.keyframe_insert('rotation_euler', frame=f + 1)
    door_curve.append(round(math.degrees(ang), 3))
    # cuervos
    for i, (body, wings, rad, alt, ph0, om, flap) in enumerate(birds):
        a = ph0 + om * tt
        body.location = (rad * math.cos(a), 64 + rad * math.sin(a) * 0.8, alt + 1.5 * math.sin(tt * 0.7 + i))
        body.rotation_euler = (0, -0.35 * math.copysign(1, om), a + (math.pi if om > 0 else 0))
        body.keyframe_insert('location', frame=f + 1)
        body.keyframe_insert('rotation_euler', frame=f + 1)
        for (w, sgn) in wings:
            w.rotation_euler = (0, sgn * 0.55 * math.sin(TAU * flap * tt + i), 0)
            w.keyframe_insert('rotation_euler', frame=f + 1)

for ob in bpy.data.objects:
    ad = ob.animation_data
    if ad and ad.action:
        for fc in getattr(ad.action, 'fcurves', []):
            for kp in fc.keyframe_points:
                kp.interpolation = 'LINEAR'

# momentos útiles para el sonido
tunnel_in = tunnel_out = None
for f in range(FRAMES):
    y = Y_START + samples[f][0]
    if tunnel_in is None and y > GATE_Y0 - 0.5:
        tunnel_in = f / FPS
    if tunnel_out is None and y > GATE_Y1 + 0.5:
        tunnel_out = f / FPS


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
scene.render.engine = 'CYCLES'
cy = scene.cycles
cy.device = 'CPU'
cy.samples = 48
cy.use_adaptive_sampling = True
cy.adaptive_threshold = 0.03
cy.use_denoising = True
cy.denoiser = 'OPENIMAGEDENOISE'
cy.max_bounces = 5
cy.diffuse_bounces = 2
cy.glossy_bounces = 2
cy.transmission_bounces = 4
cy.volume_bounces = 0
cy.transparent_max_bounces = 8
cy.caustics_reflective = False
cy.caustics_refractive = False
cy.sample_clamp_indirect = 6.0
cy.blur_glossy = 1.0
scene.render.use_persistent_data = True
scene.render.resolution_x = 1600
scene.render.resolution_y = 670
scene.render.resolution_percentage = 100
scene.render.fps = FPS
scene.frame_start = 1
scene.frame_end = FRAMES
scene.render.use_motion_blur = True
scene.render.motion_blur_shutter = 0.4
scene.view_settings.view_transform = 'AgX'
try:
    scene.view_settings.look = 'AgX - Medium High Contrast'
except Exception:
    pass
scene.view_settings.exposure = 0.35
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGB'
scene.render.filepath = os.path.join(HERE, 'render', 'frames', 'f_')
scene.render.use_overwrite = False
scene.render.use_placeholder = True

timing = {
    'fps': FPS, 'frames': FRAMES, 'duracion': DURATION,
    'pasos': steps,
    'tunel': [tunnel_in, tunnel_out],
    'puerta_grados': door_curve,
}
with open(os.path.join(HERE, 'timing.json'), 'w') as fh:
    json.dump(timing, fh, indent=1)

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, 'palacio_abandonado.blend'), compress=True)
print('OK escena guardada; pasos:', len(steps), 'tunel:', tunnel_in, tunnel_out)
