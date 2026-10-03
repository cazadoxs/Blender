"""La noche: luz de luna (fría), cielo nocturno (HDRI de noche o cielo procedural con estrellas
y luna) y la niebla: polvo denso dentro del túnel (hace visible el haz del frontal), niebla baja
que se arrastra por el monte siguiendo el terreno, bruma general y un mar de niebla en el valle."""
import bpy, math, bmesh
import numpy as np
from mathutils import Vector
from . import cfg
from .util import MAN, NB, coll, box, res_path
from . import materiales as M
from .util import new_material

MOON_COLOR = (0.58, 0.70, 1.0)


def sky_nodes(nb, moon_only=False):
    """Cielo de noche procedural: degradado azul muy oscuro, estrellas, nubes finas iluminadas por
    la luna, el disco de la luna (con mares) y su halo. Devuelve el color."""
    tc = nb.n('ShaderNodeTexCoord')
    d = nb.vmath('NORMALIZE', nb.out(tc, 'Generated'))
    M = tuple(cfg.SUN_DIR)
    dm = nb.vmath('DOT_PRODUCT', d, M)
    z = nb.out(nb.separate(d), 'Z')
    r_in, r_out = math.radians(0.95), math.radians(1.05)
    disc = nb.maprange(dm, math.cos(r_out), math.cos(r_in), 0.0, 1.0)
    maria = nb.maprange(nb.out(nb.noise(d, scale=160.0, detail=5, rough=0.6), 'Factor'), 0.35, 0.7, 0.55, 1.0)
    moon = nb.math('MULTIPLY', nb.math('MULTIPLY', disc, maria), 9.0)
    halo = nb.math('ADD', nb.math('MULTIPLY', nb.math('POWER', nb.math('MAXIMUM', dm, 0.0), 900.0), 0.6),
                   nb.math('MULTIPLY', nb.math('POWER', nb.math('MAXIMUM', dm, 0.0), 30.0), 0.035))
    moon_col = nb.mix(1.0, (0, 0, 0), (0.85, 0.9, 1.0))
    lum = nb.math('ADD', moon, halo)
    moon_rgb = nb.vmath('SCALE', moon_col, scale=1.0)
    moon_rgb = nb.vmath('MULTIPLY', moon_rgb, nb.combine(lum, lum, lum))
    if moon_only:
        return moon_rgb
    # degradado: horizonte un poco más claro (luz difusa de la luna en la bruma)
    zc = nb.math('MAXIMUM', z, 0.0)
    grad = nb.mix(nb.math('POWER', zc, 0.45), (0.022, 0.03, 0.055), (0.003, 0.0055, 0.014))
    # estrellas: celdas de Voronoi, solo algunas se encienden, con brillos distintos
    vor = nb.n('ShaderNodeTexVoronoi', {'Vector': d, 'Scale': 420.0})
    dist = nb.out(vor, 'Distance')
    pick = nb.out(nb.separate(nb.out(vor, 'Color')), 'X')
    on = nb.maprange(pick, 0.82, 0.86, 0.0, 1.0)
    bright = nb.maprange(nb.out(nb.separate(nb.out(vor, 'Color')), 'Y'), 0.0, 1.0, 0.15, 2.5)
    star = nb.math('MULTIPLY', nb.maprange(dist, 0.07, 0.0, 0.0, 1.0), nb.math('MULTIPLY', on, bright))
    star = nb.math('MULTIPLY', star, nb.maprange(z, 0.02, 0.25, 0.0, 1.0))
    star = nb.math('MULTIPLY', star, nb.maprange(dm, 0.97, 0.995, 1.0, 0.0))
    # nubes finas y alargadas que tapan estrellas y cogen el borde de la luz de la luna
    sq = nb.vmath('MULTIPLY', d, (1.0, 1.0, 3.0))
    cn = nb.out(nb.noise(sq, scale=2.2, detail=6, rough=0.62, dist=0.3), 'Factor')
    cloud = nb.math('MULTIPLY', nb.maprange(cn, 0.48, 0.72, 0.0, 1.0), nb.maprange(z, 0.0, 0.15, 0.3, 1.0))
    lit = nb.math('ADD', 0.012, nb.math('MULTIPLY', nb.math('POWER', nb.math('MAXIMUM', dm, 0.0), 12.0), 0.09))
    cloud_col = nb.vmath('MULTIPLY', (0.75, 0.8, 0.95), nb.combine(lit, lit, lit))
    stars_rgb = nb.combine(star, star, nb.math('MULTIPLY', star, 1.1))
    sky = nb.vmath('ADD', grad, stars_rgb)
    sky = nb.mix(nb.math('MULTIPLY', cloud, 0.85), sky, cloud_col)
    sky = nb.vmath('ADD', sky, nb.vmath('MULTIPLY', moon_rgb, nb.combine(*(nb.math('SUBTRACT', 1.0, nb.math('MULTIPLY', cloud, 0.7)),) * 3)))
    # por debajo del horizonte: oscuro
    below = nb.maprange(z, -0.02, 0.0, 0.0, 1.0)
    return nb.mix(below, (0.002, 0.0025, 0.004), sky)


def moon(c):
    d = bpy.data.lights.new('Luna', 'SUN')
    d.energy = 0.55
    d.angle = math.radians(0.6)
    d.color = MOON_COLOR
    ob = bpy.data.objects.new('Luna', d)
    c.objects.link(ob)
    ob.rotation_euler = (-cfg.SUN_DIR).to_track_quat('-Z', 'Y').to_euler()
    return ob


def world():
    w = bpy.data.worlds.new('Cielo de noche')
    bpy.context.scene.world = w
    try:
        w.use_nodes = True
    except Exception:
        pass
    nb = NB(w.node_tree)
    out = nb.n('ShaderNodeOutputWorld')
    hd = MAN.get('hdri')
    col = None
    if hd:
        try:
            img = bpy.data.images.load(res_path(hd['path']), check_existing=True)
            tc = nb.n('ShaderNodeTexCoord')
            env = nb.n('ShaderNodeTexEnvironment', image=img, interpolation='Cubic')
            nb.set(env.inputs['Vector'], nb.out(tc, 'Generated'))
            # el HDRI de noche se enfría y se oscurece un poco; se le suma la luna en su sitio
            hsv = nb.n('ShaderNodeHueSaturation', {'Color': nb.out(env), 'Saturation': 0.75, 'Value': 0.8})
            col = nb.mix(0.35, nb.out(hsv), (0.25, 0.33, 0.55), blend='MULTIPLY')
            col = nb.vmath('ADD', col, sky_nodes(nb, moon_only=True))
        except Exception as e:
            print('Aviso HDRI de noche:', e)
            col = None
    if col is None:
        col = sky_nodes(nb)
    # la luz que el cielo da a la escena es muy poca: la cámara lo ve más claro que lo que ilumina
    lp = nb.n('ShaderNodeLightPath')
    strength = nb.mix(nb.out(lp, 'Is Camera Ray'), 0.35, 1.0, kind='FLOAT')
    bg = nb.n('ShaderNodeBackground', {'Color': col})
    nb.set(bg.inputs['Strength'], strength)
    nb.set(out.inputs['Surface'], nb.out(bg))
    return w


def terrain_shell(name, c, mat, x0, x1, y0, y1, z_lo, z_hi, ground, step=2.0, clip=None):
    """Capa de niebla que sigue el terreno: un sólido cerrado entre ground+z_lo y ground+z_hi."""
    nx = int((x1 - x0) / step) + 1
    ny = int((y1 - y0) / step) + 1
    bm = bmesh.new()
    lo, hi = {}, {}
    for j in range(ny):
        for i in range(nx):
            x = x0 + (x1 - x0) * i / (nx - 1)
            y = y0 + (y1 - y0) * j / (ny - 1)
            g = ground(x, y)
            lo[i, j] = bm.verts.new((x, y, g + z_lo))
            hi[i, j] = bm.verts.new((x, y, g + z_hi))
    for j in range(ny - 1):
        for i in range(nx - 1):
            bm.faces.new((lo[i, j], lo[i, j + 1], lo[i + 1, j + 1], lo[i + 1, j]))
            bm.faces.new((hi[i, j], hi[i + 1, j], hi[i + 1, j + 1], hi[i, j + 1]))
    for i in range(nx - 1):
        for j, flip in ((0, False), (ny - 1, True)):
            f = (lo[i, j], lo[i + 1, j], hi[i + 1, j], hi[i, j])
            bm.faces.new(f[::-1] if flip else f)
    for j in range(ny - 1):
        for i, flip in ((0, True), (nx - 1, False)):
            f = (lo[i, j], lo[i, j + 1], hi[i, j + 1], hi[i, j])
            bm.faces.new(f[::-1] if not flip else f)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    c.objects.link(ob)
    me.materials.append(mat)
    ob.display_type = 'BOUNDS'
    return ob


def mat_niebla(name, density, scale, amt, color=(0.86, 0.9, 1.0), aniso=0.45, drift=(0.0, 0.0, 0.0)):
    """Volumen con densidad irregular a dos escalas (jirones). drift: desplazamiento por segundo
    del ruido (la niebla se mueve; se anima con un driver de la escena)."""
    m, nb = new_material(name)
    if nb is None:
        return m
    tc = nb.n('ShaderNodeTexCoord')
    obj = nb.out(tc, 'Object')
    mp = nb.n('ShaderNodeMapping', {'Vector': obj})
    m['drift'] = drift
    n1 = nb.out(nb.noise(nb.out(mp), scale=scale, detail=4, rough=0.55), 'Factor')
    n2 = nb.out(nb.noise(nb.out(mp), scale=scale * 4.3, detail=3, rough=0.6), 'Factor')
    d = nb.maprange(nb.math('ADD', nb.math('MULTIPLY', n1, 0.75), nb.math('MULTIPLY', n2, 0.25)),
                    0.5 - 0.3 * amt, 0.5 + 0.3 * amt, 0.0, 1.0)
    d = nb.math('MULTIPLY', nb.math('POWER', d, 1.5), density)
    v = nb.n('ShaderNodeVolumePrincipled', {'Color': color, 'Anisotropy': aniso})
    nb.set(v.inputs['Density'], d)
    o = nb.n('ShaderNodeOutputMaterial')
    nb.set(o.inputs['Volume'], nb.out(v))
    # el ruido se desplaza con el tiempo (la niebla se arrastra)
    try:
        loc = mp.inputs['Location']
        for k in range(3):
            if drift[k]:
                fc = loc.driver_add('default_value', k)
                fc.driver.expression = '-frame/%d*%f' % (cfg.FPS, drift[k])
    except Exception as e:
        print('Aviso niebla animada:', e)
    return m


def volumes(c, ctx):
    from .tunel import top_z
    obs = []
    # túnel: polvo y humedad en suspensión, más denso hacia el fondo; el haz del frontal se ve
    m = mat_niebla('Niebla tunel', 0.045, 0.22, 0.8, color=(0.9, 0.93, 1.0), aniso=0.62, drift=(0.0, 0.05, 0.0))
    b = box('Volumen tunel', c, (2 * cfg.HALF_W + 0.2, cfg.Y1 + 4 - cfg.Y0, cfg.CROWN + 0.1),
            (0, (cfg.Y0 + cfg.Y1 + 4) / 2, cfg.CROWN / 2), m)
    b.display_type = 'BOUNDS'
    obs.append(b)
    # pozo: un poco de vaho que sube
    m = mat_niebla('Vaho pozo', 0.08, 1.5, 0.9, color=(0.9, 0.93, 1.0), aniso=0.5, drift=(0.0, 0.0, 0.12))
    sx, sy = cfg.SHAFT
    b = box('Volumen pozo', c, (1.2, 1.2, 9.0), (sx, sy, 5.0), m)
    b.display_type = 'BOUNDS'
    obs.append(b)
    # niebla baja que se arrastra por el monte (tres capas, cada vez más tenue)
    ground = lambda x, y: top_z(x, y)
    for k, (zl, zh, dens) in enumerate(((-0.5, 1.2, 0.05), (1.2, 3.0, 0.025), (3.0, 6.5, 0.009))):
        m = mat_niebla('Niebla monte %d' % k, dens, 0.035, 0.85, color=(0.82, 0.88, 1.0), aniso=0.5,
                       drift=(0.35, -0.12, 0.0))
        obs.append(terrain_shell('Niebla monte %d' % k, c, m, -125, 45, -175, -45, zl, zh, ground, step=2.5))
    # bruma general (perspectiva aérea nocturna): se aclara con la altura
    m = M.mat_volumen('Bruma noche', 0.0011, aniso=0.6, color=(0.75, 0.82, 1.0), height_falloff=(0.246, 0.5))
    b = box('Volumen bruma', c, (9000, 8000, 1300), (0, 3000, 250), m)
    b.display_type = 'BOUNDS'
    obs.append(b)
    # mar de niebla en el valle, bajo el viaducto roto
    m = mat_niebla('Niebla valle', 0.03, 0.012, 0.9, color=(0.85, 0.9, 1.0), aniso=0.6, drift=(0.6, 0.2, 0.0))
    b = box('Volumen niebla valle', c, (2400, 900, 40), (0, 420, cfg.VALLEY_Z + 18), m)
    b.display_type = 'BOUNDS'
    obs.append(b)
    for o in obs:
        o.visible_shadow = True
    return obs


def build(main, ctx):
    c = coll('Noche', main)
    mo = moon(c)
    world()
    vols = volumes(c, ctx)
    return {'luna': mo, 'volumenes': vols}
