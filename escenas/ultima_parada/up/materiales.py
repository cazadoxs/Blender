"""Materiales PBR. Usan las texturas escaneadas de recursos/ y, si falta alguna,
un sustituto procedural con colores parecidos (para pruebas sin descargas)."""
import bpy, math
from .util import MAN, NB, new_material, image

# colores de reserva (color medio, variación, rugosidad) por papel
FALLBACK = {
    'ladrillo': ((0.20, 0.085, 0.055), (0.11, 0.07, 0.05), 0.85),
    'sillar': ((0.30, 0.27, 0.22), (0.18, 0.16, 0.13), 0.85),
    'roca': ((0.24, 0.22, 0.19), (0.12, 0.11, 0.10), 0.9),
    'balasto': ((0.20, 0.19, 0.17), (0.09, 0.085, 0.08), 0.9),
    'tierra': ((0.10, 0.065, 0.035), (0.05, 0.04, 0.02), 0.9),
    'musgo': ((0.045, 0.065, 0.02), (0.025, 0.035, 0.012), 0.85),
    'oxido': ((0.23, 0.08, 0.025), (0.11, 0.04, 0.015), 0.8),
    'metal_pintado': ((0.05, 0.09, 0.06), (0.03, 0.05, 0.035), 0.55),
    'madera': ((0.14, 0.11, 0.08), (0.07, 0.055, 0.04), 0.85),
    'corteza': ((0.12, 0.10, 0.08), (0.05, 0.045, 0.04), 0.9),
    'pradera': ((0.10, 0.13, 0.04), (0.06, 0.07, 0.03), 0.9),
}


def has(role):
    return role in MAN.get('texturas', {})


class TexSet:
    """Sockets de un conjunto PBR: color, rough, height y normal (vector)."""

    def __init__(self, color, rough, height, normal, ao=None):
        self.color, self.rough, self.height, self.normal, self.ao = color, rough, height, normal, ao


def texset(nb, role, vec, box=False, blend=0.3, bump=1.0, bump_dist=0.02, tint=None, seed=0.0):
    """Crea los nodos de un juego de texturas. vec: vector de coordenadas ya escalado."""
    info = MAN.get('texturas', {}).get(role)
    if info:
        mp = info['mapas']

        def tex(key, noncolor):
            node = nb.n('ShaderNodeTexImage', image=image(mp[key], noncolor),
                        interpolation='Cubic' if key == 'disp' else 'Linear')
            if box:
                node.projection = 'BOX'
                node.projection_blend = blend
            nb.set(node.inputs['Vector'], vec)
            return nb.out(node, 'Color')

        color = tex('color', False)
        if 'ao' in mp:
            ao = tex('ao', True)
            color = nb.mix(0.6, color, ao, blend='MULTIPLY')
        rough = tex('rough', True) if 'rough' in mp else 0.8
        if not isinstance(rough, float):
            rough = nb.out(nb.n('ShaderNodeRGBToBW', {0: rough}))
        height = nb.out(nb.n('ShaderNodeRGBToBW', {0: tex('disp', True)})) if 'disp' in mp else None
        normal = None
        if 'normal' in mp and not box:
            nm = nb.n('ShaderNodeNormalMap', {'Color': tex('normal', True), 'Strength': 1.0})
            normal = nb.out(nm)
        if height is not None:
            b = nb.n('ShaderNodeBump', {'Height': height, 'Strength': bump * (0.6 if normal else 1.0),
                                        'Distance': bump_dist})
            if normal is not None:
                nb.set(b.inputs['Normal'], normal)
            normal = nb.out(b)
    elif role in ('ladrillo', 'sillar'):
        big = role == 'sillar'
        br = nb.n('ShaderNodeTexBrick', offset=0.5, squash=1.0)
        nb.set(br.inputs['Vector'], vec)
        base, var, r = FALLBACK[role]
        n1 = nb.noise(vec, scale=4.0, detail=6.0)
        dark = tuple(max(0.0, b - v) for b, v in zip(base, var))
        light = tuple(b + v for b, v in zip(base, var))
        nb.set(br.inputs['Color1'], nb.mix(nb.out(n1, 'Factor'), dark, light))
        nb.set(br.inputs['Color2'], base)
        nb.set(br.inputs['Mortar'], (0.12, 0.11, 0.1))
        br.inputs['Scale'].default_value = 1.0
        br.inputs['Mortar Size'].default_value = 0.003 if not big else 0.006
        br.inputs['Brick Width'].default_value = 0.08 if not big else 0.3
        br.inputs['Row Height'].default_value = 0.025 if not big else 0.15
        color = nb.out(br, 'Color')
        rough = nb.maprange(nb.out(n1, 'Factor'), 0.3, 0.7, r - 0.1, r + 0.08)
        height = nb.math('SUBTRACT', 1.0, nb.out(br, 'Fac'))
        height = nb.math('ADD', nb.math('MULTIPLY', height, 0.7), nb.math('MULTIPLY', nb.out(n1, 'Factor'), 0.3))
        normal = nb.out(nb.n('ShaderNodeBump', {'Height': height, 'Strength': 0.6 * bump, 'Distance': bump_dist}))
    else:
        base, var, r = FALLBACK.get(role, ((0.3, 0.3, 0.3), (0.1, 0.1, 0.1), 0.8))
        n1 = nb.noise(vec, scale=3.0, detail=8.0, rough=0.62, w=seed)
        n2 = nb.noise(vec, scale=22.0, detail=4.0, rough=0.7)
        vor = nb.n('ShaderNodeTexVoronoi', {'Vector': vec, 'Scale': 6.0})
        f = nb.math('MULTIPLY_ADD', nb.out(n1, 'Factor'), 0.7, nb.math('MULTIPLY', nb.out(n2, 'Factor'), 0.3))
        dark = tuple(max(0.0, b - v) for b, v in zip(base, var))
        light = tuple(b + v for b, v in zip(base, var))
        color = nb.out(nb.ramp(f, [(0.3, dark), (0.5, base), (0.72, light)]))
        rough = nb.maprange(nb.out(n2, 'Factor'), 0.3, 0.7, r - 0.1, min(1.0, r + 0.1))
        height = nb.math('ADD', nb.math('MULTIPLY', nb.out(vor, 'Distance'), 0.4), nb.math('MULTIPLY', f, 0.6))
        normal = nb.out(nb.n('ShaderNodeBump', {'Height': height, 'Strength': 0.5 * bump, 'Distance': bump_dist}))
    if tint is not None:
        color = nb.mix(1.0, color, tint, blend='MULTIPLY')
    return TexSet(color, rough, height, normal)


def coords(nb, scale, kind='Object', mapping_rot=(0, 0, 0)):
    tc = nb.n('ShaderNodeTexCoord')
    m = nb.n('ShaderNodeMapping', {'Vector': nb.out(tc, kind), 'Scale': (scale, scale, scale),
                                   'Rotation': mapping_rot})
    return nb.out(m)


def principled(nb, color, rough, normal=None, **kw):
    p = nb.n('ShaderNodeBsdfPrincipled')
    nb.set(p.inputs['Base Color'], color)
    nb.set(p.inputs['Roughness'], rough)
    if normal is not None:
        nb.set(p.inputs['Normal'], normal)
    for k, v in kw.items():
        nb.set(p.inputs[k.replace('_', ' ')], v)
    return p


def output(nb, shader, disp=None, mat=None, method='BUMP'):
    o = nb.n('ShaderNodeOutputMaterial')
    nb.set(o.inputs['Surface'], shader)
    if disp is not None:
        nb.set(o.inputs['Displacement'], disp)
    if mat is not None:
        try:
            mat.displacement_method = method
        except Exception:
            pass
    return o


def displacement(nb, height, scale, mid=0.5):
    d = nb.n('ShaderNodeDisplacement', {'Height': height, 'Midlevel': mid, 'Scale': scale})
    return nb.out(d)


def mix_sets(nb, fac, a, b):
    color = nb.mix(fac, a.color, b.color)
    rough = nb.mix(fac, a.rough, b.rough, kind='FLOAT')
    normal = nb.mix(fac, a.normal, b.normal, kind='VECTOR') if (a.normal is not None and b.normal is not None) else (a.normal or b.normal)
    h = None
    if a.height is not None and b.height is not None:
        h = nb.mix(fac, a.height, b.height, kind='FLOAT')
    return TexSet(color, rough, h if h is not None else a.height, normal)


def up_mask(nb, lo=0.45, hi=0.85, noise_scale=1.5, noise_amt=0.35, vec=None):
    """Máscara de superficies que miran hacia arriba (donde crece el musgo), con ruido."""
    geo = nb.n('ShaderNodeNewGeometry')
    z = nb.out(nb.separate(nb.out(geo, 'Normal')), 'Z')
    nz = nb.noise(vec if vec is not None else nb.out(geo, 'Position'), scale=noise_scale, detail=6, rough=0.65)
    v = nb.math('ADD', z, nb.math('MULTIPLY', nb.math('SUBTRACT', nb.out(nz, 'Factor'), 0.5), noise_amt * 2))
    return nb.maprange(v, lo, hi)


# ---------------------------------------------------------------- materiales concretos
def mat_ladrillo_tunel():
    m, nb = new_material('Ladrillo tunel')
    if nb is None:
        return m
    tc = nb.n('ShaderNodeTexCoord')
    uv = nb.out(nb.n('ShaderNodeMapping', {'Vector': nb.out(tc, 'UV'), 'Scale': (0.33, 0.33, 1)}))
    obj = nb.out(tc, 'Object')
    brick = texset(nb, 'ladrillo', uv, bump=1.0, bump_dist=0.03)
    moss = texset(nb, 'musgo', nb.out(nb.n('ShaderNodeMapping', {'Vector': nb.out(tc, 'UV'), 'Scale': (0.6, 0.6, 1)})),
                  bump=1.0)
    # suciedad y humedad: chorretones verticales y zona baja húmeda
    sep = nb.separate(obj)
    zc = nb.out(sep, 'Z')
    streak_vec = nb.n('ShaderNodeMapping', {'Vector': obj, 'Scale': (3.0, 3.0, 0.15)})
    streak = nb.out(nb.noise(nb.out(streak_vec), scale=2.5, detail=6, rough=0.6), 'Factor')
    wet = nb.maprange(streak, 0.5, 0.7)
    low = nb.maprange(zc, 1.8, 0.2)       # parte baja del muro
    grime = nb.math('MAXIMUM', nb.math('MULTIPLY', wet, 0.8), nb.math('MULTIPLY', low, 0.7))
    color = nb.mix(nb.math('MULTIPLY', grime, 0.6), brick.color, (0.02, 0.018, 0.012), blend='MULTIPLY')
    color = nb.mix(nb.math('MULTIPLY', grime, 0.5), brick.color, color)
    rough = nb.mix(nb.math('MULTIPLY', wet, 0.7), brick.rough, 0.25, kind='FLOAT')
    # musgo: en la parte baja, en las juntas (alturas bajas del mapa) y cerca del suelo
    geo = nb.n('ShaderNodeNewGeometry')
    n_big = nb.out(nb.noise(obj, scale=0.35, detail=5, rough=0.6), 'Factor')
    hmask = nb.math('SUBTRACT', 1.0, brick.height) if brick.height is not None else 0.5
    mm = nb.math('ADD', nb.math('MULTIPLY', low, 0.55), nb.math('MULTIPLY', n_big, 0.9))
    mm = nb.math('ADD', mm, nb.math('MULTIPLY', hmask, 0.35))
    moss_f = nb.maprange(mm, 0.95, 1.12)
    base = type(brick)(color, rough, brick.height, brick.normal)
    s = mix_sets(nb, moss_f, base, moss)
    p = principled(nb, s.color, s.rough, s.normal)
    disp = displacement(nb, brick.height, 0.035) if brick.height is not None else None
    output(nb, p, disp, m, 'BOTH')
    return m


def mat_generic(name, role, scale, box=True, disp_scale=0.0, moss=0.0, tint=None, wet=0.0, bump=1.0,
                kind='Object', uv_scale=None, sat=1.0):
    """Material de un solo juego de texturas con musgo opcional en las caras de arriba."""
    m, nb = new_material(name)
    if nb is None:
        return m
    if uv_scale is not None:
        vec = coords(nb, uv_scale, 'UV')
        box = False
    else:
        vec = coords(nb, scale, kind)
    a = texset(nb, role, vec, box=box, tint=tint, bump=bump)
    if sat != 1.0:
        hs = nb.n('ShaderNodeHueSaturation', {'Saturation': sat, 'Color': a.color})
        a = TexSet(nb.out(hs), a.rough, a.height, a.normal)
    s = a
    if moss > 0:
        mvec = coords(nb, scale * 1.7, kind) if uv_scale is None else coords(nb, uv_scale * 1.7, 'UV')
        b = texset(nb, 'musgo', mvec, box=box)
        f = up_mask(nb, lo=1.0 - moss, hi=1.25 - moss * 0.6)
        s = mix_sets(nb, f, a, b)
    rough = s.rough
    if wet > 0:
        geo = nb.n('ShaderNodeNewGeometry')
        wn = nb.out(nb.noise(nb.out(geo, 'Position'), scale=0.4, detail=3), 'Factor')
        rough = nb.mix(nb.maprange(wn, 0.55 - wet * 0.2, 0.62), rough, 0.15, kind='FLOAT')
    p = principled(nb, s.color, rough, s.normal)
    disp = displacement(nb, s.height, disp_scale) if (disp_scale > 0 and s.height is not None) else None
    output(nb, p, disp, m, 'BOTH' if disp is not None else 'BUMP')
    return m


def mat_paisaje(name, scale=0.12, rock_tint=(0.62, 0.62, 0.64), disp_scale=0.0):
    """Suelo de paisaje a gran escala: pradera y musgo mezclados con manchas grandes (para que no se
    vea la repetición desde lejos), tierra seca en claros y roca en las pendientes fuertes."""
    m, nb = new_material(name)
    if nb is None:
        return m
    geo = nb.n('ShaderNodeNewGeometry')
    pos = nb.out(geo, 'Position')
    grass = texset(nb, 'pradera', coords(nb, scale), box=True, tint=(0.7, 0.92, 0.5))
    moss = texset(nb, 'musgo', coords(nb, scale * 2.3), box=True, tint=(0.85, 1.0, 0.8))
    dry = texset(nb, 'tierra', coords(nb, scale * 3.1), box=True, tint=(0.9, 0.85, 0.75))
    rock = texset(nb, 'roca', coords(nb, scale * 0.6), box=True, tint=rock_tint, bump=1.4)
    rock = TexSet(nb.out(nb.n('ShaderNodeHueSaturation', {'Saturation': 0.35, 'Color': rock.color})),
                  rock.rough, rock.height, rock.normal)
    big = nb.out(nb.noise(pos, scale=0.012, detail=5, rough=0.6), 'Factor')
    mid = nb.out(nb.noise(pos, scale=0.06, detail=4, rough=0.55), 'Factor')
    s_ = mix_sets(nb, nb.maprange(mid, 0.42, 0.62), grass, moss)
    s_ = mix_sets(nb, nb.maprange(big, 0.6, 0.7), s_, dry)
    z = nb.out(nb.separate(nb.out(geo, 'Normal')), 'Z')
    steep = nb.maprange(nb.math('ADD', z, nb.math('MULTIPLY', nb.math('SUBTRACT', mid, 0.5), 0.3)), 0.82, 0.68)
    s_ = mix_sets(nb, steep, s_, rock)
    # variación de brillo y tono a gran escala
    var = nb.maprange(big, 0.3, 0.7, 0.7, 1.15)
    col = nb.mix(1.0, s_.color, nb.combine(var, var, var), blend='MULTIPLY')
    p = principled(nb, col, s_.rough, s_.normal)
    disp = displacement(nb, s_.height, disp_scale) if (disp_scale > 0 and s_.height is not None) else None
    output(nb, p, disp, m, 'BOTH' if disp is not None else 'BUMP')
    return m


def mat_metal_loco(name='Locomotora pintura', paint=(0.05, 0.09, 0.065)):
    """Chapa pintada (verde oscuro de ferrocarril) comida por el óxido, con musgo arriba."""
    m, nb = new_material(name)
    if nb is None:
        return m
    vec = coords(nb, 1.2)
    paint_s = texset(nb, 'metal_pintado', vec, box=True, tint=None)
    rust = texset(nb, 'oxido', coords(nb, 0.9), box=True, bump=1.5)
    moss = texset(nb, 'musgo', coords(nb, 2.0), box=True)
    # el color de la pintura se lleva al verde de ferrocarril sin perder el detalle escaneado
    bw = nb.out(nb.n('ShaderNodeRGBToBW', {0: paint_s.color}))
    pc = nb.mix(1.0, paint, nb.math('MULTIPLY', bw, 2.2), blend='MULTIPLY')
    pc = nb.mix(0.7, paint_s.color, pc)
    paint_s = type(paint_s)(pc, paint_s.rough, paint_s.height, paint_s.normal)
    geo = nb.n('ShaderNodeNewGeometry')
    pt = nb.out(geo, 'Pointiness')
    edge = nb.maprange(pt, 0.5, 0.6)
    n1 = nb.out(nb.noise(nb.out(geo, 'Position'), scale=1.4, detail=10, rough=0.7, dist=0.3), 'Factor')
    n2 = nb.out(nb.noise(nb.out(geo, 'Position'), scale=9.0, detail=6, rough=0.6), 'Factor')
    z = nb.out(nb.separate(nb.out(geo, 'Position')), 'Z')
    low = nb.maprange(z, 1.6, 0.4)
    rm = nb.math('ADD', nb.math('ADD', n1, nb.math('MULTIPLY', n2, 0.3)), nb.math('ADD', nb.math('MULTIPLY', edge, 0.3), nb.math('MULTIPLY', low, 0.3)))
    rust_f = nb.maprange(rm, 0.78, 0.9)
    s = mix_sets(nb, rust_f, paint_s, rust)
    mf = up_mask(nb, lo=0.55, hi=0.9, noise_scale=2.0, noise_amt=0.6)
    s = mix_sets(nb, nb.math('MULTIPLY', mf, 0.92), s, moss)
    metal = nb.math('MULTIPLY', nb.math('SUBTRACT', 1.0, rust_f), nb.math('MULTIPLY', edge, 0.6))
    p = principled(nb, s.color, s.rough, s.normal, Metallic=metal)
    output(nb, p, None, m)
    return m


def mat_oxido(name='Oxido', scale=1.0, moss=0.35):
    return mat_generic(name, 'oxido', scale, moss=moss, bump=1.5)


def mat_rail():
    m, nb = new_material('Carril')
    if nb is None:
        return m
    rust = texset(nb, 'oxido', coords(nb, 1.5), box=True, bump=1.2)
    geo = nb.n('ShaderNodeNewGeometry')
    nz = nb.out(nb.separate(nb.out(geo, 'Normal')), 'Z')
    top = nb.maprange(nz, 0.8, 0.95)
    # la cabeza del carril: óxido más oscuro y liso, restos de metal
    dark = nb.mix(1.0, rust.color, (0.35, 0.3, 0.28), blend='MULTIPLY')
    color = nb.mix(top, rust.color, dark)
    rough = nb.mix(top, rust.rough, 0.45, kind='FLOAT')
    p = principled(nb, color, rough, rust.normal, Metallic=nb.math('MULTIPLY', top, 0.35))
    output(nb, p, None, m)
    return m


def mat_laton():
    m, nb = new_material('Laton viejo')
    if nb is None:
        return m
    geo = nb.n('ShaderNodeNewGeometry')
    n = nb.out(nb.noise(nb.out(geo, 'Position'), scale=18, detail=8, rough=0.7), 'Factor')
    pat = nb.maprange(n, 0.4, 0.65)
    color = nb.mix(pat, (0.55, 0.38, 0.12), (0.10, 0.13, 0.09))   # latón y cardenillo
    rough = nb.mix(pat, 0.32, 0.8, kind='FLOAT')
    p = principled(nb, color, rough, None, Metallic=nb.math('SUBTRACT', 1.0, pat))
    output(nb, p, None, m)
    return m


def mat_vidrio_sucio():
    m, nb = new_material('Vidrio sucio')
    if nb is None:
        return m
    geo = nb.n('ShaderNodeNewGeometry')
    n = nb.out(nb.noise(nb.out(geo, 'Position'), scale=12, detail=6), 'Factor')
    dirt = nb.maprange(n, 0.35, 0.7)
    glass = nb.n('ShaderNodeBsdfGlass', {'Color': (0.85, 0.88, 0.8), 'Roughness': 0.08, 'IOR': 1.5})
    dirt_s = principled(nb, (0.08, 0.07, 0.05), 0.9, None)
    mix = nb.n('ShaderNodeMixShader', {0: dirt, 1: nb.out(glass), 2: nb.out(dirt_s)})
    output(nb, nb.out(mix), None, m)
    return m


def mat_negro_hollin():
    return mat_generic('Hollin', 'oxido', 1.5, tint=(0.25, 0.22, 0.2), moss=0.2)


def mat_hoja(name='Hoja', base=(0.045, 0.11, 0.02), var=(0.03, 0.05, 0.01), autumn=0.12):
    """Hoja procedural: silueta con alfa a partir de la UV, nervio central y translucidez."""
    m, nb = new_material(name)
    if nb is None:
        return m
    tc = nb.n('ShaderNodeTexCoord')
    sep = nb.separate(nb.out(tc, 'UV'))
    u = nb.math('SUBTRACT', nb.math('MULTIPLY', nb.out(sep, 'X'), 2.0), 1.0)   # -1..1 a lo ancho
    v = nb.out(sep, 'Y')                                                        # 0..1 a lo largo
    # ancho de la hoja en función de v (forma de lanza)
    width = nb.math('POWER', nb.math('SINE', nb.math('MULTIPLY', nb.math('POWER', v, 0.8), math.pi)), 0.85)
    inside = nb.math('LESS_THAN', nb.math('ABSOLUTE', u), nb.math('MULTIPLY', width, 0.98))
    # color por hoja (Random del objeto/instancia) con algunas amarillentas
    oi = nb.n('ShaderNodeObjectInfo')
    rnd = nb.out(oi, 'Random')
    ga = nb.n('ShaderNodeAttribute', attribute_type='INSTANCER', attribute_name='hoja_rand')
    rr = nb.math('FRACT', nb.math('ADD', rnd, nb.out(ga, 'Fac')))
    dark = tuple(max(0, b - x) for b, x in zip(base, var))
    light = tuple(b + x for b, x in zip(base, var))
    col = nb.out(nb.ramp(rr, [(0.0, dark), (0.5, base), (1.0 - autumn, light), (1.0 - autumn + 0.01, (0.25, 0.17, 0.03)),
                              (1.0, (0.18, 0.09, 0.02))]))
    vein = nb.maprange(nb.math('ABSOLUTE', u), 0.0, 0.06, 1.0, 0.0)
    col = nb.mix(nb.math('MULTIPLY', vein, 0.4), col, (0.3, 0.35, 0.12))
    nz = nb.out(nb.noise(nb.out(tc, 'UV'), scale=30, detail=5), 'Factor')
    col = nb.mix(nb.math('MULTIPLY', nz, 0.35), col, (0.02, 0.03, 0.01), blend='MULTIPLY')
    bump = nb.n('ShaderNodeBump', {'Height': nb.math('ADD', nz, nb.math('MULTIPLY', vein, 0.5)), 'Strength': 0.15})
    p = principled(nb, col, 0.45, nb.out(bump), Subsurface_Weight=0.0, Transmission_Weight=0.0,
                   Specular_IOR_Level=0.4)
    tr = nb.n('ShaderNodeBsdfTranslucent', {'Color': nb.mix(1.0, col, (1.6, 1.9, 0.9), blend='MULTIPLY')})
    mix = nb.n('ShaderNodeMixShader', {0: 0.35, 1: nb.out(p), 2: nb.out(tr)})
    transp = nb.n('ShaderNodeBsdfTransparent')
    alpha = nb.n('ShaderNodeMixShader', {0: inside, 1: nb.out(transp), 2: nb.out(mix)})
    output(nb, nb.out(alpha), None, m)
    return m


def mat_agua():
    m, nb = new_material('Agua charco')
    if nb is None:
        return m
    geo = nb.n('ShaderNodeNewGeometry')
    n = nb.noise(nb.out(geo, 'Position'), scale=6, detail=4)
    bump = nb.n('ShaderNodeBump', {'Height': nb.out(n, 'Factor'), 'Strength': 0.04})
    p = principled(nb, (0.012, 0.012, 0.01), 0.03, nb.out(bump), IOR=1.33, Specular_IOR_Level=0.5)
    output(nb, nb.out(p), None, m)
    return m


def mat_polvo():
    m, nb = new_material('Motas de polvo')
    if nb is None:
        return m
    p = principled(nb, (0.8, 0.75, 0.65), 0.6, None, Transmission_Weight=0.4)
    output(nb, nb.out(p), None, m)
    return m


def mat_volumen(name, density, aniso=0.55, color=(1, 1, 1), noise_scale=0.0, noise_amt=0.0, height_falloff=None):
    m, nb = new_material(name)
    if nb is None:
        return m
    dens = density
    if noise_scale > 0:
        tc = nb.n('ShaderNodeTexCoord')
        n = nb.out(nb.noise(nb.out(tc, 'Object'), scale=noise_scale, detail=3, rough=0.55), 'Factor')
        dens = nb.math('MULTIPLY', density, nb.maprange(n, 0.3, 0.7, 1.0 - noise_amt, 1.0 + noise_amt))
    if height_falloff is not None:
        tc = nb.n('ShaderNodeTexCoord')
        z = nb.out(nb.separate(nb.out(tc, 'Generated')), 'Z')
        f = nb.maprange(z, height_falloff[0], height_falloff[1], 1.0, 0.0)
        dens = nb.math('MULTIPLY', dens, nb.math('POWER', f, 1.6))
    v = nb.n('ShaderNodeVolumePrincipled', {'Color': color, 'Anisotropy': aniso})
    nb.set(v.inputs['Density'], dens)
    o = nb.n('ShaderNodeOutputMaterial')
    nb.set(o.inputs['Volume'], nb.out(v))
    return m
