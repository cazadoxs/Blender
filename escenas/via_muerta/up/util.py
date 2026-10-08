"""Utilidades comunes: colecciones, mallas desde numpy, constructor de nodos y recursos."""
import bpy, bmesh, os, json, math
import numpy as np
from mathutils import Vector, Matrix

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAN = {'texturas': {}, 'modelos': {}}


def load_manifest():
    p = os.path.join(HERE, 'recursos', 'manifiesto.json')
    if os.path.exists(p):
        m = json.load(open(p, encoding='utf-8'))
        MAN.update(m)
    print('Recursos: %d texturas, %d grupos de modelos, HDRI: %s' % (
        len(MAN.get('texturas', {})), len(MAN.get('modelos', {})), MAN.get('hdri', {}).get('id', 'no')))
    return MAN


def res_path(rel):
    return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(HERE, rel))


# ------------------------------------------------------------------ colecciones
def coll(name, parent=None):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    par = parent or bpy.context.scene.collection
    if c.name not in [x.name for x in par.children]:
        par.children.link(c)
    return c


def hidden_coll(name):
    """Colección que no se ve en el render (fuente de instancias)."""
    c = coll(name)
    lc = bpy.context.view_layer.layer_collection.children[c.name]
    lc.exclude = True
    return c


def put(obj, c):
    for old in list(obj.users_collection):
        old.objects.unlink(obj)
    c.objects.link(obj)
    return obj


# ------------------------------------------------------------------ mallas
def mesh_obj(name, verts, faces, c, uv=None, smooth=False, mat=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    if uv is not None:
        layer = me.uv_layers.new(name='UVMap')
        data = []
        for f, fu in zip(faces, uv):
            data.extend(fu)
        layer.data.foreach_set('uv', np.array(data, dtype=np.float32).ravel())
    me.validate()
    me.update()
    if smooth:
        me.shade_smooth()
    if mat:
        me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    c.objects.link(ob)
    return ob


def grid_mesh(name, nx, ny, fn, c, uvscale=1.0, mat=None):
    """Malla rejilla: fn(u, v) -> (x, y, z) con u, v en [0,1]. UV = coordenadas planas / uvscale."""
    us = np.linspace(0, 1, nx + 1)
    vs = np.linspace(0, 1, ny + 1)
    verts = [fn(u, v) for v in vs for u in us]
    faces, uvs = [], []
    W = nx + 1
    for j in range(ny):
        for i in range(nx):
            a = j * W + i
            f = (a, a + 1, a + 1 + W, a + W)
            faces.append(f)
            uvs.append([(verts[k][0] / uvscale, verts[k][1] / uvscale) for k in f])
    return mesh_obj(name, verts, faces, c, uv=uvs, mat=mat)


def bm_obj(bm, name, c, mat=None, smooth=False):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        me.shade_smooth()
    if mat:
        if isinstance(mat, (list, tuple)):
            for m in mat:
                me.materials.append(m)
        else:
            me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    c.objects.link(ob)
    return ob


def box(name, c, size, loc, mat=None, rot=(0, 0, 0), bevel=0.0):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    ob = bm_obj(bm, name, c, mat)
    ob.location = loc
    ob.rotation_euler = rot
    if bevel > 0:
        m = ob.modifiers.new('bisel', 'BEVEL')
        m.width = bevel
        m.segments = 2
        m.limit_method = 'ANGLE'
    return ob


def cyl(name, c, r, depth, loc, mat=None, rot=(0, 0, 0), seg=48, r2=None, cap=True, smooth=True):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=cap, segments=seg, radius1=r, radius2=r if r2 is None else r2, depth=depth)
    ob = bm_obj(bm, name, c, mat, smooth=smooth)
    ob.location = loc
    ob.rotation_euler = rot
    return ob


def bevel(ob, w=0.01, seg=2, angle=40):
    m = ob.modifiers.new('bisel', 'BEVEL')
    m.width = w
    m.segments = seg
    m.limit_method = 'ANGLE'
    m.angle_limit = math.radians(angle)
    m.harden_normals = False
    return m


def adaptive(ob, rate=1.0):
    """Subdivisión adaptativa para desplazamiento real en Cycles."""
    m = ob.modifiers.new('desplazamiento', 'SUBSURF')
    m.subdivision_type = 'SIMPLE'
    m.levels = 0
    try:
        m.use_adaptive_subdivision = True
        m.adaptive_space = 'PIXEL'
        m.adaptive_pixel_size = rate
    except Exception:
        m.render_levels = 3
    return m


def join(obs, name):
    ctx = bpy.context
    with ctx.temp_override(active_object=obs[0], selected_editable_objects=obs, selected_objects=obs):
        bpy.ops.object.join()
    obs[0].name = name
    return obs[0]


def apply_mods(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev)
    ob.modifiers.clear()
    old = ob.data
    ob.data = me
    bpy.data.meshes.remove(old)


def look_at(ob, target, roll=0.0):
    d = Vector(target) - ob.location
    ob.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    if roll:
        ob.rotation_euler.rotate_axis('Z', roll)


# ------------------------------------------------------------------ nodos
class NB:
    """Constructor compacto de árboles de nodos."""

    def __init__(self, tree, clear=True):
        self.t = tree
        if clear:
            tree.nodes.clear()
        self.x = 0

    def n(self, kind, inputs=None, **props):
        node = self.t.nodes.new(kind)
        for k, v in props.items():
            setattr(node, k, v)
        for k, v in (inputs or {}).items():
            self.set(node.inputs[k] if isinstance(k, int) else self._sock(node.inputs, k), v)
        return node

    @staticmethod
    def _sock(socks, key):
        for s in socks:
            if s.identifier == key and s.enabled:
                return s
        for s in socks:
            if s.name == key and s.enabled:
                return s
        for s in socks:
            if s.identifier == key or s.name == key:
                return s
        # Blender 5.2: nodos con un solo juego de sockets ('Min_002' -> 'Min')
        base, _, suf = key.rpartition('_')
        if base and suf.isdigit():
            return NB._sock(socks, base)
        raise KeyError(key)

    def out(self, node, key=0):
        if isinstance(key, int):
            outs = [s for s in node.outputs if s.enabled]
            return outs[key]
        return self._sock(node.outputs, key)

    def set(self, sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            self.t.links.new(v, sock)
        elif isinstance(v, bpy.types.Node):
            self.t.links.new(self.out(v), sock)
        else:
            try:
                sock.default_value = v
            except (TypeError, ValueError):
                if isinstance(v, (int, float)) and hasattr(sock.default_value, '__len__'):
                    sock.default_value = [v] * len(sock.default_value)
                else:
                    sock.default_value = tuple(v) + (1.0,) * (len(sock.default_value) - len(v))

    def link(self, a, b):
        self.t.links.new(a, b)

    # atajos de matemáticas
    def math(self, op, a, b=0.0, c=0.0, clamp=False):
        return self.out(self.n('ShaderNodeMath', {0: a, 1: b, 2: c}, operation=op, use_clamp=clamp))

    def vmath(self, op, a, b=(0, 0, 0), scale=1.0):
        node = self.n('ShaderNodeVectorMath', {0: a, 1: b, 'Scale': scale}, operation=op)
        return self.out(node, 'Value' if op in ('LENGTH', 'DOT_PRODUCT', 'DISTANCE') else 'Vector')

    def mix(self, fac, a, b, kind='RGBA', blend='MIX'):
        idx = {'RGBA': 'Color', 'FLOAT': 'Float', 'VECTOR': 'Vector'}[kind]
        node = self.n('ShaderNodeMix', data_type=kind)
        if kind == 'RGBA':
            node.blend_type = blend
        self.set(self._sock(node.inputs, 'Factor_Float'), fac)
        self.set(self._sock(node.inputs, 'A_' + idx), a)
        self.set(self._sock(node.inputs, 'B_' + idx), b)
        return self._sock(node.outputs, 'Result_' + idx)

    def ramp(self, fac, stops):
        node = self.n('ShaderNodeValToRGB')
        self.set(node.inputs[0], fac)
        el = node.color_ramp.elements
        while len(el) > len(stops):
            el.remove(el[-1])
        while len(el) < len(stops):
            el.new(0.5)
        for e, (p, col) in zip(el, stops):
            e.position = p
            e.color = col if len(col) == 4 else tuple(col) + (1.0,)
        return node

    def maprange(self, v, a, b, c=0.0, d=1.0, clamp=True):
        node = self.n('ShaderNodeMapRange', clamp=clamp)
        self.set(node.inputs['Value'], v)
        node.inputs['From Min'].default_value = a
        node.inputs['From Max'].default_value = b
        node.inputs['To Min'].default_value = c
        node.inputs['To Max'].default_value = d
        return self.out(node, 'Result')

    def noise(self, vec=None, scale=5.0, detail=4.0, rough=0.5, dist=0.0, dims='3D', w=0.0):
        node = self.n('ShaderNodeTexNoise', noise_dimensions=dims)
        if vec is not None:
            self.set(node.inputs['Vector'], vec)
        node.inputs['Scale'].default_value = scale
        node.inputs['Detail'].default_value = detail
        node.inputs['Roughness'].default_value = rough
        node.inputs['Distortion'].default_value = dist
        if dims in ('4D', '1D'):
            node.inputs['W'].default_value = w
        return node

    def separate(self, vec):
        node = self.n('ShaderNodeSeparateXYZ')
        self.set(node.inputs[0], vec)
        return node

    def combine(self, x=0.0, y=0.0, z=0.0):
        return self.out(self.n('ShaderNodeCombineXYZ', {0: x, 1: y, 2: z}))


def new_material(name):
    m = bpy.data.materials.get(name)
    if m:
        return m, None
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    return m, NB(m.node_tree)


_img_cache = {}


def image(path, noncolor=False):
    path = res_path(path)
    key = (path, noncolor)
    if key not in _img_cache:
        img = bpy.data.images.load(path, check_existing=True)
        if noncolor:
            img.colorspace_settings.is_data = True
            try:
                img.colorspace_settings.name = 'Non-Color'
            except TypeError:
                pass
        _img_cache[key] = img
    return _img_cache[key]


def rng(seed):
    return np.random.default_rng(seed)
