"""Ajustes de render: Cycles, formato cine, gestión de color y composición."""
import bpy
from . import cfg

W, H = 1920, 804          # 2,39:1 (formato cine)
FRAMES = 1800             # 75 s a 24 fps


def render_settings(scene):
    r = scene.render
    r.engine = 'CYCLES'
    r.resolution_x, r.resolution_y = W, H
    r.resolution_percentage = 100
    r.fps = cfg.FPS
    scene.frame_start = 1
    scene.frame_end = FRAMES
    r.use_motion_blur = True
    r.motion_blur_shutter = 0.5
    r.film_transparent = False
    r.image_settings.file_format = 'PNG'
    r.image_settings.color_depth = '8'
    r.image_settings.compression = 15
    cy = scene.cycles
    cy.samples = 256
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.012
    cy.use_denoising = True
    cy.denoiser = 'OPENIMAGEDENOISE'
    cy.max_bounces = 10
    cy.diffuse_bounces = 4
    cy.glossy_bounces = 4
    cy.transmission_bounces = 8
    cy.transparent_max_bounces = 24      # hojas con alfa
    cy.volume_bounces = 1
    cy.sample_clamp_indirect = 8.0
    cy.caustics_reflective = False
    cy.caustics_refractive = False
    cy.use_light_tree = True
    cy.volume_step_rate = 1.0
    cy.volume_max_steps = 1024
    cy.dicing_rate = 1.0
    cy.offscreen_dicing_scale = 6.0
    cy.blur_glossy = 1.0
    try:
        cy.use_guiding = True             # path guiding: ayuda mucho con la luz que entra por los huecos
        cy.use_volume_guiding = True
    except Exception:
        pass
    vs = scene.view_settings
    vs.view_transform = 'AgX'
    try:
        vs.look = 'AgX - Medium High Contrast'
    except TypeError:
        pass
    vs.exposure = 0.0
    compositor(scene)


def compositor(scene):
    """Un poco de resplandor (bloom) sobre las altas luces, como en una lente real."""
    try:
        ng = bpy.data.node_groups.new('Composicion', 'CompositorNodeTree')
        ng.interface.new_socket('Image', in_out='OUTPUT', socket_type='NodeSocketColor')
        rl = ng.nodes.new('CompositorNodeRLayers')
        gl = ng.nodes.new('CompositorNodeGlare')
        gl.inputs['Type'].default_value = 'Bloom'
        gl.inputs['Highlights Threshold'].default_value = 1.2
        gl.inputs['Strength'].default_value = 0.35
        gl.inputs['Size'].default_value = 0.6
        out = ng.nodes.new('NodeGroupOutput')
        ng.links.new(rl.outputs['Image'], gl.inputs['Image'])
        ng.links.new(gl.outputs['Image'], out.inputs[0])
        scene.compositing_node_group = ng
        scene.render.use_compositing = True
    except Exception as e:
        print('Aviso: composición sin bloom (%s)' % e)
