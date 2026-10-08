"""La locomotora que arranca: se separa en máquina y ténder, se le ponen los mandos de la
cabina (hogar, regulador, freno, manómetros), los faroles, asideros y estribos; y se anima:
patina, arranca, sale del túnel, frena en el viaducto y cae por el hueco del puente.
Las ruedas giran con la distancia recorrida y las bielas se mueven con las muñequillas."""
import bpy, bmesh, math
import numpy as np
from mathutils import Vector, Matrix, Quaternion, Euler
from . import cfg
from .util import coll, box, cyl, bm_obj, bevel, rng, join, NB
from . import materiales as M
from . import anim as A

F = cfg.LOCO_FRONT
PIV_M = Vector((0.0, 52.0, 1.9))     # centro de masas aproximado de la máquina
PIV_T = Vector((0.0, 42.6, 1.9))     # y del ténder
CAB = cfg.CAB_Y                       # 47.4: la cabina va de 46.35 a 48.45
BACKHEAD_Y = 47.2                     # cara trasera del hogar, dentro de la cabina
EDGE_Y = cfg.GAP[0]                   # donde se acaba la vía en el viaducto
R_DRIVE, R_BOGIE, R_TENDER = 0.74, 0.43, 0.5
RC = 0.74 * 0.42                      # radio de la manivela
CRANK = {-1: math.radians(35.0), 1: math.radians(125.0)}

G = {}        # objetos importantes (se rellena en prepare)
P = {}        # parámetros del movimiento (se rellena en plan)


def Y(d):
    return F - d


# ------------------------------------------------------------------ preparación
def _empty(name, c, loc, size=0.5):
    e = bpy.data.objects.new(name, None)
    c.objects.link(e)
    e.location = loc
    e.empty_display_size = size
    return e


def _world(ob):
    """Matriz del mundo calculada a mano (matrix_world no se actualiza hasta evaluar la escena)."""
    if ob.parent is None:
        return ob.matrix_basis.copy()
    return _world(ob.parent) @ ob.matrix_parent_inverse @ ob.matrix_basis


def _parent_keep(ob, parent):
    mw = _world(ob)
    ob.parent = parent
    ob.matrix_parent_inverse = _world(parent).inverted()
    ob.matrix_basis = mw


def prepare(main, ctx):
    c = bpy.data.collections['Locomotora']
    root = ctx['loco']['root']
    # la locomotora de "Vía muerta" está derecha sobre la vía (no hundida ni ladeada)
    root.rotation_euler = (0, 0, 0)
    root.location = (0, 0, 0)
    bpy.context.view_layer.update()
    maq = _empty('Maquina', c, PIV_M, 1.5)
    ten = _empty('Tender', c, PIV_T, 1.5)
    G['maq'], G['ten'] = maq, ten
    kids = [o for o in c.objects if o.parent == root]
    for o in kids:
        if o.type == 'MESH':
            bb = [o.matrix_world @ Vector(v) for v in o.bound_box]
            yc = sum(v.y for v in bb) / 8
        else:
            yc = o.matrix_world.translation.y
        _parent_keep(o, ten if yc < 45.9 else maq)
    bpy.data.objects.remove(root)
    # ejes de las ruedas: cada rueda cuelga de un vacío en su eje, que es lo que gira
    G['wheels'] = []
    for o in list(c.objects):
        if o.type == 'MESH' and o.name.startswith(('Rueda motriz', 'Rueda bogie', 'Rueda tender')):
            if ' ' in o.name and o.name.split(' ')[-1] in ('bandaje', 'radio', 'cubo', 'tapa', 'pestana'):
                continue
            loc = o.matrix_world.translation.copy()
            ax = _empty('Eje ' + o.name, c, loc, 0.3)
            _parent_keep(ax, o.parent)
            _parent_keep(o, ax)
            r = R_DRIVE if 'motriz' in o.name else (R_BOGIE if 'bogie' in o.name else R_TENDER)
            G['wheels'].append((ax, r, 'motriz' in o.name))
    # bielas, crucetas y vástagos (por lado)
    G['rods'] = {}
    for o in c.objects:
        for key in ('Biela acoplamiento', 'Biela motriz', 'Cruceta', 'Vastago'):
            if o.name.startswith(key):
                s = 1 if o.matrix_world.translation.x > 0 else -1
                G['rods'][(key, s)] = (o, o.location.copy(), o.rotation_euler.copy())
    cab_extras(c, maq, ctx)
    lamps(c, maq, ten)
    return {'maq': maq, 'ten': ten}


def cab_extras(c, maq, ctx):
    """Mandos de la cabina, estribos y asideros de la puerta."""
    paint = bpy.data.materials.get('Locomotora pintura') or M.mat_metal_loco()
    rust = bpy.data.materials.get('Oxido loco') or M.mat_oxido('Oxido loco')
    brass = bpy.data.materials.get('Laton viejo') or M.mat_laton()
    glass = bpy.data.materials.get('Vidrio sucio') or M.mat_vidrio_sucio()
    obs = []
    by = BACKHEAD_Y
    # placa trasera del hogar (cara de la caldera dentro de la cabina)
    obs.append(box('Placa hogar', c, (1.56, 0.03, 1.36), (0, by - 0.015, 2.35), rust, bevel=0.01))
    # puerta del hogar: marco y dos hojas (la de la derecha se abre)
    obs.append(box('Marco puerta hogar', c, (0.56, 0.04, 0.42), (0, by - 0.03, 2.22), rust, bevel=0.01))
    door = box('Puerta hogar', c, (0.26, 0.03, 0.36), (0.13, by - 0.065, 2.22), rust, bevel=0.008)
    hinge = _empty('Bisagra puerta hogar', c, (0.26, by - 0.065, 2.22), 0.1)
    _parent_keep(door, hinge)
    G['door'] = hinge
    obs.append(box('Puerta hogar fija', c, (0.26, 0.03, 0.36), (-0.13, by - 0.065, 2.22), rust, bevel=0.008))
    # brasas dentro: un plano con emisión (se aviva cuando arranca)
    fire = box('Brasas', c, (0.5, 0.02, 0.36), (0, by + 0.05, 2.22), None)
    fm, nb = M.new_material('Brasas hogar')
    if nb:
        tc = nb.n('ShaderNodeTexCoord')
        n1 = nb.out(nb.noise(nb.out(tc, 'Object'), scale=9.0, detail=6, rough=0.65, dims='4D', w=0.0), 'Factor')
        col = nb.out(nb.ramp(n1, [(0.35, (0.02, 0.0, 0.0)), (0.55, (0.9, 0.12, 0.01)), (0.75, (1.0, 0.45, 0.05))]))
        oi = nb.n('ShaderNodeObjectInfo')
        a = nb.out(oi, 'Alpha')
        em = nb.n('ShaderNodeEmission', {'Color': col, 'Strength': nb.math('MULTIPLY', a, 40.0)})
        M.output(nb, nb.out(em))
    fire.data.materials.append(fm)
    fire.color = (1, 1, 1, 0.08)
    G['fire'] = fire
    # regulador: palanca larga arriba a la derecha, gira hacia el maquinista
    piv = _empty('Eje regulador', c, (0.32, by - 0.06, 2.92), 0.1)
    lev = box('Regulador', c, (0.035, 0.035, 0.55), (0.32, by - 0.09, 2.92 - 0.24), brass, bevel=0.006)
    knob = cyl('Puño regulador', c, 0.03, 0.12, (0.32, by - 0.09, 2.92 - 0.5), rust, rot=(0, math.pi / 2, 0), seg=16)
    _parent_keep(lev, piv)
    _parent_keep(knob, piv)
    G['regulator'] = piv
    obs.append(cyl('Caja regulador', c, 0.07, 0.12, (0.32, by - 0.06, 2.92), brass, rot=(math.pi / 2, 0, 0), seg=24))
    # freno: volante a la izquierda
    fpiv = _empty('Eje freno', c, (-0.62, by - 0.25, 2.45), 0.1)
    wheel = bpy.data.objects.new('Volante freno', None)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=False, segments=24, radius1=0.17, radius2=0.17, depth=0.025)
    rim = bm_obj(bm, 'Volante freno', c, rust)
    rim.location = fpiv.location
    rim.rotation_euler = (math.pi / 2, 0, 0)
    for k in range(3):
        a = k * 2 * math.pi / 3
        sp = box('Radio volante', c, (0.015, 0.012, 0.17), (fpiv.location.x + 0.085 * math.sin(a), fpiv.location.y,
                                                            fpiv.location.z + 0.085 * math.cos(a)), rust, rot=(0, a, 0))
        _parent_keep(sp, fpiv)
    _parent_keep(rim, fpiv)
    obs.append(cyl('Columna freno', c, 0.03, 0.6, (-0.62, by - 0.25, 2.12), rust, seg=12))
    G['brake'] = fpiv
    # manómetros y nivel de agua
    for x in (-0.28, 0.05):
        obs.append(cyl('Manometro', c, 0.085, 0.05, (x, by - 0.05, 3.05), brass, rot=(math.pi / 2, 0, 0), seg=32))
        obs.append(cyl('Esfera manometro', c, 0.072, 0.01, (x, by - 0.078, 3.05), glass, rot=(math.pi / 2, 0, 0), seg=32))
    obs.append(cyl('Nivel agua', c, 0.015, 0.32, (-0.45, by - 0.05, 2.75), glass, seg=12))
    for dz in (0.17, -0.17):
        obs.append(box('Grifo nivel', c, (0.05, 0.06, 0.04), (-0.45, by - 0.05, 2.75 + dz), brass))
    # tuberías por la placa
    obs.append(cyl('Tubo cabina', c, 0.02, 1.3, (0.55, by - 0.05, 2.45), rust, seg=10))
    obs.append(cyl('Tubo cabina', c, 0.018, 1.1, (0, by - 0.05, 2.95), rust, rot=(0, math.pi / 2, 0), seg=10))
    # estribos y asideros de las dos puertas
    door_y = CAB - 0.75
    for s in (-1, 1):
        obs.append(box('Estribo puerta', c, (0.28, 0.42, 0.03), (s * 1.5, door_y, 1.05), rust, bevel=0.006))
        obs.append(box('Estribo puerta bajo', c, (0.25, 0.4, 0.03), (s * 1.52, door_y, 0.6), rust, bevel=0.006))
        for dy in (-0.3, 0.3):
            obs.append(box('Soporte estribo', c, (0.03, 0.03, 0.5), (s * 1.52, door_y + dy * 0.6, 0.83), rust))
            obs.append(cyl('Asidero', c, 0.016, 1.05, (s * 1.43, door_y + dy, 2.42), brass, seg=10))
    ex = join(obs, 'Mandos cabina')
    bevel(ex, 0.004, 1)
    for o in [ex, fire, hinge, piv, fpiv]:
        _parent_keep(o, maq)


def lamps(c, maq, ten):
    # farol delantero: se enciende al arrancar
    ld = bpy.data.lights.new('Farol', 'SPOT')
    ld.energy = 0.0
    ld.spot_size = math.radians(38)
    ld.spot_blend = 0.55
    ld.shadow_soft_size = 0.08
    ld.color = (1.0, 0.78, 0.5)
    ob = bpy.data.objects.new('Farol luz', ld)
    c.objects.link(ob)
    ob.location = (0, Y(0.72), 2.65 + 1.02)
    ob.rotation_euler = (math.radians(86), 0, math.pi)     # mira a +Y, un poco hacia abajo
    _parent_keep(ob, maq)
    G['headlamp'] = ob
    lens = bpy.data.objects.get('Farol cristal')
    m, nb = M.new_material('Farol encendido')
    if nb:
        oi = nb.n('ShaderNodeObjectInfo')
        em = nb.n('ShaderNodeEmission', {'Color': (1.0, 0.75, 0.45), 'Strength': nb.math('MULTIPLY', nb.out(oi, 'Alpha'), 30.0)})
        gl = nb.n('ShaderNodeBsdfGlass', {'Roughness': 0.15})
        add = nb.n('ShaderNodeAddShader', {0: nb.out(em), 1: nb.out(gl)})
        M.output(nb, nb.out(add))
    if lens:
        lens.data.materials.clear()
        lens.data.materials.append(m)
        lens.color = (1, 1, 1, 0.0)
        G['lens'] = lens
    # farol de cola rojo en el ténder (ilumina al monstruo por detrás)
    t1 = 17.3
    lp = box('Farol cola', c, (0.2, 0.16, 0.26), (0.95, Y(t1 + 0.25), 2.75), bpy.data.materials.get('Hollin'), bevel=0.015)
    rl = cyl('Farol cola cristal', c, 0.065, 0.02, (0.95, Y(t1 + 0.34), 2.75), None, rot=(math.pi / 2, 0, 0), seg=24)
    rm, nb = M.new_material('Farol rojo')
    if nb:
        oi = nb.n('ShaderNodeObjectInfo')
        em = nb.n('ShaderNodeEmission', {'Color': (1.0, 0.04, 0.02), 'Strength': nb.math('MULTIPLY', nb.out(oi, 'Alpha'), 25.0)})
        M.output(nb, nb.out(em))
    rl.data.materials.append(rm)
    rl.color = (1, 1, 1, 0.0)
    G['tail_lens'] = rl
    pl = bpy.data.lights.new('Farol cola', 'POINT')
    pl.energy = 0.0
    pl.color = (1.0, 0.05, 0.02)
    pl.shadow_soft_size = 0.05
    po = bpy.data.objects.new('Farol cola luz', pl)
    c.objects.link(po)
    po.location = (0.95, Y(t1 + 0.42), 2.75)
    for o in (lp, rl, po):
        _parent_keep(o, ten)
    G['tail'] = po
    # resplandor del hogar en la cabina
    fl = bpy.data.lights.new('Fuego hogar', 'POINT')
    fl.energy = 0.0
    fl.color = (1.0, 0.36, 0.08)
    fl.shadow_soft_size = 0.18
    fo = bpy.data.objects.new('Fuego hogar luz', fl)
    c.objects.link(fo)
    fo.location = (0.05, BACKHEAD_Y - 0.25, 2.2)
    _parent_keep(fo, maq)
    G['firelight'] = fo
    # brasas que caen al cenicero: un resplandor anaranjado bajo la caldera, entre las ruedas
    al = bpy.data.lights.new('Brasas cenicero', 'POINT')
    al.energy = 0.0
    al.color = (1.0, 0.32, 0.06)
    al.shadow_soft_size = 0.3
    ao = bpy.data.objects.new('Brasas cenicero luz', al)
    c.objects.link(ao)
    ao.location = (0.0, BACKHEAD_Y + 1.0, 0.55)
    _parent_keep(ao, maq)
    G['ashlight'] = ao


def attach_vegetation(ctx):
    """La hierba, los helechos y la hiedra que crecen sobre la locomotora se van con ella."""
    maq, ten = G['maq'], G['ten']
    for o in bpy.data.objects:
        if o.name.startswith(('Hierba loco', 'Helechos tender', 'Arbustos tender', 'Hiedra loco')):
            mods = [m for m in o.modifiers if m.type == 'NODES']
            surf = None
            if mods:
                for n in mods[0].node_group.nodes:
                    if n.bl_idname == 'GeometryNodeObjectInfo':
                        surf = n.inputs['Object'].default_value
            par = maq
            if surf is not None and surf.parent is not None:
                par = surf.parent
                while par not in (maq, ten) and par.parent is not None:
                    par = par.parent
            _parent_keep(o, par if par in (maq, ten) else maq)


# ------------------------------------------------------------------ movimiento
def plan(t_reg, v_max=11.0, accel=1.2, decel=1.2, v_edge=3.5, slip=0.6):
    """t_reg: momento en que se abre el regulador. Calcula s(t) (avance de la máquina) hasta el borde
    y después la caída. Devuelve los instantes clave."""
    P.clear()
    t0 = t_reg + 0.45                     # el vapor llega a los cilindros
    t1 = t0 + slip                        # patina y luego agarra
    ta = v_max / accel
    sa = 0.5 * accel * ta * ta
    s_edge = EDGE_Y - F                   # 155 m: el frente llega al borde
    s_brake = s_edge - (v_max ** 2 - v_edge ** 2) / (2 * decel)
    tb = t1 + ta + (s_brake - sa) / v_max
    te = tb + (v_max - v_edge) / decel
    P.update(dict(t_reg=t_reg, t0=t0, t1=t1, ta=ta, sa=sa, v_max=v_max, accel=accel, decel=decel, s_brake=s_brake,
                  tb=tb, te=te, v_edge=v_edge, s_edge=s_edge))
    # salida del túnel (frente en la boca) y momento en que el centro de masas pasa el borde
    P['t_boca'] = t_of_s(cfg.Y1 - F)
    _integrate_wheels()
    _simulate_fall()
    _tender_plan()
    return P


def _integrate_wheels():
    """Giro de las ruedas: rodadura (sin girar con el freno bloqueado) y patinazo de las motrices."""
    dt = 1 / 240
    ts = np.arange(P['t0'] - 1, P['te'] + 30, dt)
    base = np.zeros(len(ts))
    slip = np.zeros(len(ts))
    for i in range(1, len(ts)):
        tt = ts[i]
        lock = A.smoothstep(P['tb'] + 0.3, P['tb'] + 0.7, tt)
        base[i] = base[i - 1] + v_of_t(tt) * (1 - lock) * dt
        ws = 9.0 * A.smoothstep(P['t0'], P['t0'] + 0.25, tt) * (1 - A.smoothstep(P['t1'], P['t1'] + 0.35, tt))
        w_roll = v_of_t(tt) / R_DRIVE
        slip[i] = slip[i - 1] + max(0.0, ws - w_roll) * dt
    P['wt'], P['wbase'], P['wslip'] = ts, base, slip


def s_of_t(t):
    p = P
    if t <= p['t1']:
        return 0.0
    if t <= p['t1'] + p['ta']:
        u = t - p['t1']
        return 0.5 * p['accel'] * u * u
    if t <= p['tb']:
        return p['sa'] + p['v_max'] * (t - p['t1'] - p['ta'])
    if t <= p['te']:
        u = t - p['tb']
        return p['s_brake'] + p['v_max'] * u - 0.5 * p['decel'] * u * u
    return p['s_edge'] + p['v_edge'] * (t - p['te'])


def v_of_t(t):
    return (s_of_t(t + 0.01) - s_of_t(t - 0.01)) / 0.02


def t_of_s(s):
    lo, hi = P['t1'], P['te'] + 60
    for _ in range(60):
        mid = (lo + hi) / 2
        if s_of_t(mid) < s:
            lo = mid
        else:
            hi = mid
    return hi


def _simulate_fall():
    """Vuelco y caída de la máquina y el ténder: pivotan sobre el borde y caen al valle."""
    # la máquina: inclinación (cabeceo) y caída
    dt = 1 / 240
    track = []
    t = P['te']
    # mientras el frente sobresale del borde: cabecea un poco
    state = {'y': PIV_M.y + s_of_t(t), 'z': PIV_M.z, 'vy': P['v_edge'], 'vz': 0.0, 'th': 0.0, 'w': 0.0, 'roll': 0.0, 'wr': 0.0}
    phase = 'borde'
    t_rel = None
    while t < P['te'] + 14:
        y_cm = state['y']
        over = y_cm - EDGE_Y                         # >0: el centro de masas ya pasó el borde
        if phase == 'borde':
            state['vy'] = P['v_edge']
            state['y'] += state['vy'] * dt
            front_over = (y_cm + 5.0) - EDGE_Y
            state['th'] = -math.radians(7) * A.smoothstep(0, 5.0, front_over)
            state['z'] = PIV_M.z - 0.12 * A.smoothstep(0, 5.0, front_over)
            if over > 0:
                phase = 'vuelco'
                P['t_tip'] = t
        elif phase == 'vuelco':
            # gira sobre el borde: aceleración angular por el par del peso
            arm = max(0.2, over)
            alpha = 9.81 * arm / (2.6 ** 2 + arm ** 2) * math.cos(state['th'])
            state['w'] -= alpha * dt
            state['th'] += state['w'] * dt
            state['y'] += state['vy'] * dt
            # el centro de masas baja siguiendo el giro alrededor del borde
            state['z'] = 0.51 + (PIV_M.z - 0.51) * math.cos(state['th']) + arm * math.sin(state['th'])
            if state['th'] < -math.radians(48):
                phase = 'caida'
                t_rel = t
                state['vz'] = state['w'] * arm * 0.9
                state['wr'] = 0.22
                P['t_caida'] = t
        else:
            state['vz'] -= 9.81 * dt
            state['y'] += state['vy'] * dt
            state['z'] += state['vz'] * dt
            state['th'] += state['w'] * dt
            state['w'] *= (1 - 0.15 * dt)
            state['roll'] += state['wr'] * dt
            if state['z'] < cfg.VALLEY_Z + 4.0:
                P['t_impacto'] = t
                break
        track.append((t, state['y'], state['z'], state['th'], state['roll']))
        t += dt
    P['fall_maq'] = np.array(track)
    P.setdefault('t_impacto', t)


def _tender_plan():
    """El ténder sigue por la vía, arrastrado cada vez más deprisa cuando la máquina cae;
    al llegar su centro al borde repite el vuelco y la caída de la máquina."""
    tr = P['fall_maq']
    t_c = P.get('t_caida', P['te'] + 3)
    s_c = s_of_t(t_c)
    P['ten_tc'], P['ten_sc'] = t_c, s_c
    t = t_c
    while PIV_T.y + _s_ten(t) < EDGE_Y and t < t_c + 10:
        t += 1 / 240
    P['ten_edge'] = t


def _s_ten(t):
    t_c = P['ten_tc']
    if t <= t_c:
        return s_of_t(t)
    u = t - t_c
    return P['ten_sc'] + P['v_edge'] * u + 0.5 * 4.0 * u * u


def _fall_at(t_ref):
    tr = P['fall_maq']
    i = int(np.clip((t_ref - tr[0, 0]) * 240, 0, len(tr) - 1))
    return tr[i]


def group_state(name, t):
    """(desplazamiento, cuaternión) del grupo 'maq' o 'ten' en el instante t."""
    tr = P.get('fall_maq')
    if name == 'maq':
        if tr is None or t < tr[0, 0]:
            return Vector((0, s_of_t(t), 0)), Quaternion()
        _, y, z, th, roll = _fall_at(t)
        return Vector((0, y - PIV_M.y, z - PIV_M.z)), Euler((th, roll, roll * 0.4)).to_quaternion()
    if tr is None or t < P['ten_edge']:
        return Vector((0, _s_ten(t), 0)), Quaternion()
    # mismo vuelco que la máquina, empezando cuando el ténder llega al borde
    t_ref = P['t_tip'] + (t - P['ten_edge'])
    _, y, z, th, roll = _fall_at(t_ref)
    return Vector((0, y - PIV_T.y, z - PIV_T.z)), Euler((th * 0.92, -roll * 0.7, -roll * 0.3)).to_quaternion()


def group_matrix(name, t):
    """Matriz que lleva coordenadas de la escena en reposo a su sitio en el instante t."""
    piv = PIV_M if name == 'maq' else PIV_T
    off, q = group_state(name, t)
    return Matrix.Translation(piv + off) @ q.to_matrix().to_4x4() @ Matrix.Translation(-piv)


def wheel_angle(t, r, driven):
    """Ángulo girado (rad): rodando, más el patinazo al arrancar, y sin girar con el freno bloqueado."""
    b = float(np.interp(t, P['wt'], P['wbase']))
    a = b / r
    if driven:
        a += float(np.interp(t, P['wt'], P['wslip']))
    return a


def bake(t_end):
    """Escribe las curvas del tren desde el regulador hasta t_end."""
    frames = A.frames_range(P['t_reg'] - 0.5, t_end)
    ts = [A.time_of(f) for f in frames]
    for name in ('maq', 'ten'):
        ob = G[name]
        piv = PIV_M if name == 'maq' else PIV_T
        locs, quats = [], []
        for t in ts:
            off, q = group_state(name, t)
            # vibración en marcha
            v = v_of_t(t) if t < P['te'] else 0
            sh = 0.004 * min(1.0, v / 6.0)
            locs.append(piv + off + Vector((A.nz(t, 3, 9) * sh, 0, A.nz(t, 5, 13) * sh)))
            quats.append(q @ Euler((A.nz(t, 7, 7) * sh * 0.4, A.nz(t, 8, 6) * sh * 1.2, 0)).to_quaternion())
        A.bake_obj(ob, frames, locs, quats)
    # ruedas (las del ténder y las de la máquina se integran por separado)
    ang_cache = {}
    for ax, r, driven in G['wheels']:
        key = (r, driven)
        if key not in ang_cache:
            ang_cache[key] = [wheel_angle(t, r, driven) for t in ts]
        A.bake(ax, 'rotation_euler', frames, np.array([[-a, 0, 0] for a in ang_cache[key]]))
    # bielas
    dr = ang_cache[(R_DRIVE, True)]
    for s in (-1, 1):
        c0 = CRANK[s]
        rod = G['rods'].get(('Biela acoplamiento', s))
        main = G['rods'].get(('Biela motriz', s))
        cross = G['rods'].get(('Cruceta', s))
        vast = G['rods'].get(('Vastago', s))
        x_axle_mid_y = Y(6.75)
        zc = cfg.RAIL_TOP + R_DRIVE
        if rod:
            ob, l0, r0 = rod
            locs = [l0 + Vector((0, RC * (math.sin(c0 + a) - math.sin(c0)), RC * (math.cos(c0 + a) - math.cos(c0)))) for a in dr]
            A.bake(ob, 'location', frames, locs)
        if main:
            ob, l0, r0 = main
            M0 = Vector((0, x_axle_mid_y + RC * math.sin(c0), zc + RC * math.cos(c0)))
            C0 = Vector((0, Y(3.85), 1.35))
            Lr = (C0 - M0).length
            locs, rots, dys = [], [], []
            for a in dr:
                Mp = Vector((0, x_axle_mid_y + RC * math.sin(c0 + a), zc + RC * math.cos(c0 + a)))
                cy = Mp.y + math.sqrt(max(0.0, Lr ** 2 - (Mp.z - 1.35) ** 2))
                Cp = Vector((0, cy, 1.35))
                mid = (Cp + Mp) / 2
                d = Mp - Cp
                locs.append(Vector((l0.x, mid.y, mid.z)))
                rots.append((math.atan2(d.z, d.y), r0.y, r0.z))
                dys.append(cy - C0.y)
            A.bake(ob, 'location', frames, locs)
            A.bake(ob, 'rotation_euler', frames, rots)
            for part in (cross, vast):
                if part:
                    o2, l2, _ = part
                    A.bake(o2, 'location', frames, [l2 + Vector((0, dy, 0)) for dy in dys])
    # luces: hogar, farol, cola
    tr = P['t_reg']
    A.bake_prop(G['door'], 'rotation_euler', [(tr - 1.6, (0, 0, 0)), (tr - 1.1, (0, 0, math.radians(-100)))])
    fire_keys, fl_keys, ash_keys = [], [], []
    for k in range(int((t_end - tr + 3) * 8)):
        t = tr - 1.4 + k / 8
        flick = 0.75 + 0.25 * A.nz(t, 11, 6) + 0.1 * A.nz(t, 12, 17)
        on = A.smoothstep(tr - 1.4, tr + 0.6, t)
        fire_keys.append((t, (1, 1, 1, 0.08 + 0.92 * on * flick)))
        fl_keys.append((t, 6.0 + 140.0 * on * flick))
        ash_keys.append((t, 3.0 + 45.0 * on * (0.6 + 0.4 * flick)))
    A.bake_prop(G['fire'], 'color', fire_keys)
    A.bake_prop(G['firelight'].data, 'energy', fl_keys)
    A.bake_prop(G['ashlight'].data, 'energy', ash_keys)
    on = [(tr + 0.2, 0.0), (tr + 0.35, 0.6), (tr + 0.45, 0.1), (tr + 0.6, 1.0)]     # parpadea al encenderse
    A.bake_prop(G['headlamp'].data, 'energy', [(t, v * 1800.0) for t, v in on])
    if 'lens' in G:
        A.bake_prop(G['lens'], 'color', [(t, (1, 1, 1, v)) for t, v in on])
    A.bake_prop(G['tail'].data, 'energy', [(tr + 0.4, 0.0), (tr + 0.7, 35.0)])
    A.bake_prop(G['tail_lens'], 'color', [(tr + 0.4, (1, 1, 1, 0.0)), (tr + 0.7, (1, 1, 1, 1.0))])
    # regulador y freno
    A.bake_prop(G['regulator'], 'rotation_euler', [(tr - 0.25, (0, 0, 0)), (tr + 0.3, (math.radians(-55), 0, 0))])
    tb = P['tb']
    A.bake_prop(G['brake'], 'rotation_euler', [(tb - 0.6, (0, 0, 0)), (tb + 0.4, (0, math.radians(-320), 0))])
    steam(t_end)
    sparks()


# ------------------------------------------------------------------ vapor y chispas
def mat_vapor(name='Vapor', color=(0.9, 0.9, 0.92), density=3.0):
    m, nb = M.new_material(name)
    if nb is None:
        return m
    tc = nb.n('ShaderNodeTexCoord')
    obj = nb.out(tc, 'Object')
    d = nb.vmath('LENGTH', obj)
    oi = nb.n('ShaderNodeObjectInfo')
    n = nb.noise(obj, scale=2.2, detail=5, rough=0.6, dist=0.4, dims='4D')
    nb.set(n.inputs['W'], nb.math('MULTIPLY', nb.out(oi, 'Random'), 40.0))
    fall = nb.maprange(d, 1.0, 0.25)
    dens = nb.math('MULTIPLY', nb.math('MULTIPLY', fall, nb.maprange(nb.out(n, 'Factor'), 0.42, 0.7)),
                   nb.math('MULTIPLY', nb.out(oi, 'Alpha'), density))
    v = nb.n('ShaderNodeVolumePrincipled', {'Color': color, 'Anisotropy': 0.35})
    nb.set(v.inputs['Density'], dens)
    o = nb.n('ShaderNodeOutputMaterial')
    nb.set(o.inputs['Volume'], nb.out(v))
    return m


PUFFS = []


def puff_pool(n, name, mat):
    c = coll('Vapor')
    pool = []
    for i in range(n):
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
        ob = bm_obj(bm, '%s %d' % (name, i), c, mat)
        ob.display_type = 'BOUNDS'
        ob.scale = (0.001, 0.001, 0.001)
        ob.color = (1, 1, 1, 0.0)
        ob.visible_shadow = False
        pool.append(ob)
    return pool


class PuffEmitter:
    """Reparte bocanadas de vapor entre un grupo de objetos de volumen reutilizables."""

    def __init__(self, n, name, mat, life=3.0):
        self.pool = puff_pool(n, name, mat)
        self.keys = {ob.name: [] for ob in self.pool}
        self.busy = {ob.name: -1e9 for ob in self.pool}
        self.life = life

    def emit(self, t, pos, vel, size0=0.25, size1=2.2, rise=1.2, alpha=1.0, ceiling=None, life=None):
        life = life or self.life
        ob = min(self.pool, key=lambda o: self.busy[o.name])
        if self.busy[ob.name] > t:
            return
        self.busy[ob.name] = t + life + 0.1
        ks = self.keys[ob.name]
        pos = Vector(pos)
        vel = Vector(vel)
        for k in range(9):
            u = k / 8
            tt = t + u * life
            # frenado por el aire: la bocanada se queda atrás enseguida
            drift = vel * (1 - math.exp(-3.0 * u * life)) / 3.0
            p = pos + drift + Vector((0, 0, rise * (u * life) ** 0.8))
            if ceiling is not None:
                p.z = min(p.z, ceiling)
            s = size0 + (size1 - size0) * (1 - (1 - u) ** 2.2)
            a = alpha * (A.smoothstep(0, 0.08, u) * (1 - A.smoothstep(0.35, 1.0, u)))
            ks.append((tt, p, s, a))
        ks.append((t - 1 / 24, pos, 0.001, 0.0))
        ks.append((t + life + 1 / 24, pos, 0.001, 0.0))

    def bake(self):
        for ob in self.pool:
            ks = sorted(self.keys[ob.name], key=lambda k: k[0])
            if not ks:
                ob.hide_render = True
                ob.hide_viewport = True
                continue
            fr = [A.frame_of(k[0]) for k in ks]
            # entre bocanadas no hay salto: el objeto queda escondido (escala casi cero)
            A.bake(ob, 'location', fr, [k[1] for k in ks])
            A.bake(ob, 'scale', fr, [(k[2], k[2], k[2]) for k in ks])
            A.bake(ob, 'color', fr, [(1, 1, 1, k[3]) for k in ks])


def chuffs():
    return list(G.get('chuffs', []))


def steam(t_end):
    G['chuffs'] = []
    em = PuffEmitter(40, 'Vapor tren', mat_vapor(), life=2.8)
    G['steam'] = em
    # purga de los cilindros al abrir el regulador: chorros laterales blancos
    tr = P['t_reg']
    for k in range(10):
        t = tr + 0.4 + k * 0.25
        mtx = group_matrix('maq', t)
        for s in (-1, 1):
            p = mtx @ Vector((s * 1.25, Y(1.7), 1.0))
            em.emit(t, p, Vector((s * 6.0, 0.5, -0.5)), 0.15, 1.6, rise=0.5, alpha=1.2, life=1.8)
    # escape por la chimenea: cuatro golpes por vuelta de rueda
    t = P['t1']
    last = -1
    while t < min(t_end, P.get('t_caida', t_end)):
        ang = wheel_angle(t, R_DRIVE, True)
        k = int(ang / (math.pi / 2))
        if k != last:
            last = k
            G.setdefault('chuffs', []).append(t)
            mtx = group_matrix('maq', t)
            p = mtx @ Vector((0, Y(1.85), 2.65 + 1.9))
            v = v_of_t(t)
            inside = p.y < cfg.Y1 + 2
            em.emit(t, p, Vector((0, v * 0.1, 7.0)), 0.25, 2.4 if not inside else 1.8, rise=1.6,
                    alpha=1.0, ceiling=cfg.CROWN - 0.9 if inside else None)
        t += 1 / 48
    em.bake()


def sparks():
    """Chispas en el contacto rueda-carril: al patinar y con el freno bloqueado."""
    c = coll('Chispas')
    m, nb = M.new_material('Chispa')
    if nb:
        oi = nb.n('ShaderNodeObjectInfo')
        em = nb.n('ShaderNodeEmission', {'Color': (1.0, 0.55, 0.18), 'Strength': nb.math('MULTIPLY', nb.out(oi, 'Alpha'), 60.0)})
        M.output(nb, nb.out(em))
    for s in (-1, 1):
        for d in (5.0, 6.75, 8.5):
            ob = spark_emitter('Chispas rueda', c, m, seed=int(d * 10) + s)
            ob.location = (s * 0.79, Y(d) + R_DRIVE * 0.75, cfg.RAIL_TOP + 0.02)
            _parent_keep(ob, G['maq'])
            keys = [(P['t0'] - 0.1, 0.0), (P['t0'] + 0.1, 1.0), (P['t1'] + 0.2, 1.0), (P['t1'] + 0.5, 0.0),
                    (P['tb'] + 0.3, 0.0), (P['tb'] + 0.6, 1.0), (P.get('t_tip', P['te'] + 1.5), 1.0),
                    (P.get('t_tip', P['te'] + 1.5) + 0.3, 0.0)]
            A.bake_prop(ob, 'color', [(t, (1, 1, 1, v)) for t, v in keys])


def spark_emitter(name, c, mat, seed=0, n=60):
    me = bpy.data.meshes.new(name)
    ob = bpy.data.objects.new(name, me)
    c.objects.link(ob)
    ng = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    ng.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    nb = NB(ng)
    gin = nb.n('NodeGroupInput')
    gout = nb.n('NodeGroupOutput')
    pts = nb.n('GeometryNodePoints', {'Count': n})
    idx = nb.n('GeometryNodeInputIndex')
    st = nb.n('GeometryNodeInputSceneTime')

    def rnd(k, lo, hi):
        r = nb.n('FunctionNodeRandomValue', data_type='FLOAT')
        NB._sock(r.inputs, 'Min_001').default_value = lo
        NB._sock(r.inputs, 'Max_001').default_value = hi
        nb.set(NB._sock(r.inputs, 'ID'), nb.out(idx))
        r.inputs['Seed'].default_value = seed * 10 + k
        return nb.out(r, 'Value_001')
    life = 0.35
    age = nb.math('MULTIPLY', nb.math('FRACT', nb.math('ADD', nb.math('MULTIPLY', nb.out(st, 'Seconds'), 1 / life), rnd(1, 0, 1))), life)
    vx, vy, vz = rnd(2, -1.5, 1.5), rnd(3, -7.0, -2.0), rnd(4, 0.5, 3.5)
    px = nb.math('MULTIPLY', vx, age)
    py = nb.math('MULTIPLY', vy, age)
    pz = nb.math('SUBTRACT', nb.math('MULTIPLY', vz, age), nb.math('MULTIPLY', nb.math('MULTIPLY', age, age), 4.9))
    sp = nb.n('GeometryNodeSetPosition')
    nb.set(sp.inputs['Geometry'], nb.out(pts, 'Points'))
    nb.set(sp.inputs['Position'], nb.combine(px, py, pz))
    cube = nb.n('GeometryNodeMeshCube', {'Size': (0.004, 0.06, 0.004)})
    vel = nb.combine(vx, vy, nb.math('SUBTRACT', vz, nb.math('MULTIPLY', age, 9.81)))
    align = nb.n('FunctionNodeAlignRotationToVector', axis='Y')
    nb.set(align.inputs['Vector'], vel)
    iop = nb.n('GeometryNodeInstanceOnPoints')
    nb.set(iop.inputs['Points'], nb.out(sp))
    nb.set(iop.inputs['Instance'], nb.out(cube, 'Mesh'))
    nb.set(iop.inputs['Rotation'], nb.out(align))
    nb.set(iop.inputs['Scale'], nb.maprange(age, 0.0, life, 1.0, 0.2))
    sm = nb.n('GeometryNodeSetMaterial')
    nb.set(sm.inputs['Geometry'], nb.out(iop))
    sm.inputs['Material'].default_value = mat
    nb.set(gout.inputs[0], nb.out(sm))
    ob.modifiers.new('chispas', 'NODES').node_group = ng
    ob.color = (1, 1, 1, 0.0)
    return ob
