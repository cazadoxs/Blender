"""Sol de atardecer, cielo HDRI (o cielo físico de reserva) y volúmenes:
polvo en suspensión dentro del túnel, bruma lejana y niebla en el fondo del valle."""
import bpy, math
import numpy as np
from mathutils import Vector
from . import cfg
from .util import MAN, NB, coll, box, res_path
from . import materiales as M


def sun(c):
    d = bpy.data.lights.new('Sol', 'SUN')
    d.energy = 5.5
    d.angle = math.radians(0.9)
    try:
        d.use_temperature = True
        d.temperature = 3700
    except AttributeError:
        d.color = (1.0, 0.72, 0.46)
    ob = bpy.data.objects.new('Sol', d)
    c.objects.link(ob)
    ob.rotation_euler = (-cfg.SUN_DIR).to_track_quat('-Z', 'Y').to_euler()
    return ob


def hdri_sun_azimuth(img):
    """Acimut (rad, atan2(y, x) en coordenadas de mundo) del píxel más brillante del HDRI."""
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)[::4, ::4]
    lum = px[..., 0] * 0.2126 + px[..., 1] * 0.7152 + px[..., 2] * 0.0722
    j, i = np.unravel_index(np.argmax(lum), lum.shape)
    u = (i * 4 + 2) / w
    phi = (u - 0.5) * 2 * math.pi
    # en Blender: u = atan2(dir.y, -dir.x) / 2pi + 0.5  ->  dir = (-cos(phi), sin(phi))
    return math.atan2(math.sin(phi), -math.cos(phi))


def world():
    w = bpy.data.worlds.new('Cielo')
    bpy.context.scene.world = w
    try:
        w.use_nodes = True
    except Exception:
        pass
    nb = NB(w.node_tree)
    out = nb.n('ShaderNodeOutputWorld')
    hd = MAN.get('hdri')
    if hd:
        img = bpy.data.images.load(res_path(hd['path']), check_existing=True)
        az_h = hdri_sun_azimuth(img)
        az_s = math.atan2(cfg.SUN_DIR.y, cfg.SUN_DIR.x)
        tc = nb.n('ShaderNodeTexCoord')
        mp = nb.n('ShaderNodeMapping', {'Vector': nb.out(tc, 'Generated'), 'Rotation': (0, 0, az_h - az_s)})
        env = nb.n('ShaderNodeTexEnvironment', image=img, interpolation='Cubic')
        nb.set(env.inputs['Vector'], nb.out(mp))
        col = nb.out(env)
        # para iluminar se recorta el sol del HDRI (el sol de verdad es la lámpara)
        clamp = nb.vmath('MINIMUM', col, (6.0, 6.0, 6.0))
        lp = nb.n('ShaderNodeLightPath')
        mix = nb.mix(nb.out(lp, 'Is Camera Ray'), clamp, col)
        bg = nb.n('ShaderNodeBackground', {'Color': mix, 'Strength': 0.85})
    else:
        sky = nb.n('ShaderNodeTexSky', sky_type='MULTIPLE_SCATTERING')
        try:
            sky.sun_elevation = cfg.SUN_ELEV
            sky.sun_rotation = (math.pi / 2 - math.atan2(cfg.SUN_DIR.y, cfg.SUN_DIR.x))
            sky.altitude = 600
            sky.air_density = 1.2
            sky.aerosol_density = 2.5
            sky.sun_disc = False
        except Exception as e:
            print('Aviso cielo:', e)
        bg = nb.n('ShaderNodeBackground', {'Color': nb.out(sky), 'Strength': 0.22})
    nb.set(out.inputs['Surface'], nb.out(bg))
    return w


def volumes(c):
    obs = []
    # polvo dentro del túnel: es lo que hace visibles los haces de luz
    m = M.mat_volumen('Polvo tunel', 0.014, aniso=0.62, color=(1.0, 0.97, 0.92), noise_scale=0.25, noise_amt=0.55)
    b = box('Volumen tunel', c, (2 * cfg.HALF_W + 0.2, cfg.Y1 + 6 - cfg.Y0, cfg.CROWN + 0.1),
            (0, (cfg.Y0 + cfg.Y1 + 6) / 2, cfg.CROWN / 2), m)
    b.display_type = 'BOUNDS'
    obs.append(b)
    # bruma general (perspectiva aérea) que se aclara con la altura
    # (la caja baja hasta -400 m para que el suelo no asome por debajo de la bruma con un corte duro)
    m = M.mat_volumen('Bruma', 0.00024, aniso=0.7, color=(0.95, 0.9, 0.85), height_falloff=(0.246, 0.577))
    b = box('Volumen bruma', c, (9000, 8000, 1300), (0, 3000, 250), m)
    b.display_type = 'BOUNDS'
    obs.append(b)
    # niebla en el fondo del valle
    m = M.mat_volumen('Niebla valle', 0.005, aniso=0.6, color=(1, 0.98, 0.96), noise_scale=0.012, noise_amt=0.8,
                      height_falloff=(0.0, 1.0))
    b = box('Volumen niebla', c, (2400, 900, 34), (0, 420, cfg.VALLEY_Z + 15), m)
    b.display_type = 'BOUNDS'
    obs.append(b)
    for o in obs:
        o.visible_shadow = True
    return obs


def build(main, ctx):
    c = coll('Luz y atmosfera', main)
    s = sun(c)
    world()
    volumes(c)
    return {'sol': s}
