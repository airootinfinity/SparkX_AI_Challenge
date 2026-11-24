"""Shared Blender helpers for the SparkX asset scripts (run inside `blender -b --python ...`).

Conventions: metres, +X forward, +Y left, +Z up (ROS REP-103). Every helper returns the created
object; objects are tagged with one material each and later joined per export file.
"""
import json
import math
import os

import bmesh
import bpy
from mathutils import Matrix, Vector

INK = (0.098, 0.098, 0.098)
CRIMSON = (0.898, 0.008, 0.153)
OFFWHITE = (0.941, 0.937, 0.949)

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, '..', '..', 'src'))
MEDIA = os.path.join(SRC, 'sparkx_worlds', 'models', 'sparkx_media')


def srgb_to_linear(c):
    return tuple(((v / 12.92) if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4) for v in c)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


_MATS = {}


def mat(name, color=(0.5, 0.5, 0.5), rough=0.5, metal=0.0, emit=None, emit_strength=0.0, tex=None,
        normal=None, rough_tex=None, alpha=1.0):
    """Principled material. `color` is sRGB 0..1. tex / normal / rough_tex are image file paths."""
    if name in _MATS:
        return _MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m.use_backface_culling = True          # exported single-sided: a camera inside a housing sees out of it
    nt = m.node_tree
    b = nt.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*srgb_to_linear(color), 1.0)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    if alpha < 1.0:
        b.inputs['Alpha'].default_value = alpha
        m.blend_method = 'BLEND'
    if emit is not None:
        b.inputs['Emission Color'].default_value = (*srgb_to_linear(emit), 1.0)
        b.inputs['Emission Strength'].default_value = emit_strength

    def image_node(path, non_color=False):
        n = nt.nodes.new('ShaderNodeTexImage')
        n.image = bpy.data.images.load(path, check_existing=True)
        if non_color:
            n.image.colorspace_settings.name = 'Non-Color'
        return n
    if tex:
        nt.links.new(image_node(tex).outputs['Color'], b.inputs['Base Color'])
    if rough_tex:
        nt.links.new(image_node(rough_tex, True).outputs['Color'], b.inputs['Roughness'])
    if normal:
        nm = nt.nodes.new('ShaderNodeNormalMap')
        nt.links.new(image_node(normal, True).outputs['Color'], nm.inputs['Color'])
        nt.links.new(nm.outputs['Normal'], b.inputs['Normal'])
    _MATS[name] = m
    return m


def _new_object(name, bm, material):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    if material is not None:
        me.materials.append(material)
    return ob


def place(ob, loc=(0, 0, 0), rot=(0, 0, 0)):
    ob.location = loc
    ob.rotation_euler = rot
    return ob


def bevel(ob, width, segments=2):
    if width > 0:
        m = ob.modifiers.new('bevel', 'BEVEL')
        m.width, m.segments, m.limit_method, m.angle_limit = width, segments, 'ANGLE', math.radians(40)
        m.harden_normals = False
    return ob


def box(name, size, loc, material, rot=(0, 0, 0), bev=0.0, seg=2):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    return bevel(place(_new_object(name, bm, material), loc, rot), bev, seg)


def cyl(name, radius, depth, loc, material, axis='z', verts=32, rot=None, bev=0.0, seg=2, r2=None):
    """Cylinder (or cone frustum with r2) along `axis`."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=verts, radius1=radius, radius2=radius if r2 is None else r2,
                          depth=depth)
    ob = _new_object(name, bm, material)
    if rot is None:
        rot = {'z': (0, 0, 0), 'x': (0, math.pi / 2, 0), 'y': (-math.pi / 2, 0, 0)}[axis]
    return bevel(place(ob, loc, rot), bev, seg)


def sphere(name, radius, loc, material, segs=16, rings=10, scale=(1, 1, 1)):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=radius)
    ob = place(_new_object(name, bm, material), loc)
    ob.scale = scale
    return ob


def prism(name, outline, z0, z1, material, bev=0.0, seg=2):
    """Vertical extrusion of a 2D outline [(x, y), ...] between z0 and z1."""
    bm = bmesh.new()
    vs = [bm.verts.new((x, y, z0)) for x, y in outline]
    f = bm.faces.new(vs)
    r = bmesh.ops.extrude_face_region(bm, geom=[f])
    bmesh.ops.translate(bm, vec=Vector((0, 0, z1 - z0)), verts=[e for e in r['geom'] if isinstance(e, bmesh.types.BMVert)])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bevel(_new_object(name, bm, material), bev, seg)


def octagon(lx, ly, chamfer):
    hx, hy, c = lx / 2, ly / 2, chamfer
    return [(hx - c, -hy), (hx, -hy + c), (hx, hy - c), (hx - c, hy), (-hx + c, hy), (-hx, hy - c), (-hx, -hy + c),
            (-hx + c, -hy)]


def lathe(name, profile, material, segments=48, axis='y'):
    """Surface of revolution. profile: closed loop of (radius, along_axis) points."""
    bm = bmesh.new()
    rings = []
    for k in range(segments):
        a = 2 * math.pi * k / segments
        ring = []
        for r, t in profile:
            if axis == 'y':
                ring.append(bm.verts.new((r * math.cos(a), t, r * math.sin(a))))
            else:
                ring.append(bm.verts.new((r * math.cos(a), r * math.sin(a), t)))
        rings.append(ring)
    n = len(profile)
    for k in range(segments):
        a, b = rings[k], rings[(k + 1) % segments]
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((a[i], a[j], b[j], b[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _new_object(name, bm, material)


def tube(name, path, radius, material, verts=10):
    """Round tube swept along a 3D polyline (cables, hoses, rebar, pipes)."""
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    sp = cu.splines.new('POLY')
    sp.points.add(len(path) - 1)
    for p, co in zip(sp.points, path):
        p.co = (*co, 1.0)
    cu.bevel_depth, cu.bevel_resolution, cu.use_fill_caps = radius, max(0, verts // 4 - 1), True
    ob = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(ob)
    cu.materials.append(material)
    return ob


def flat_tris(name, tris2d, origin, u_axis, v_axis, material, flip=False):
    """Flat mesh from 2D triangles placed in 3D: p = origin + u * u_axis + v * v_axis."""
    bm = bmesh.new()
    o, ua, va = Vector(origin), Vector(u_axis), Vector(v_axis)
    for t in tris2d:
        vs = [bm.verts.new(o + ua * u + va * v) for u, v in t]
        try:
            bm.faces.new(vs[::-1] if flip else vs)
        except ValueError:
            pass
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    return _new_object(name, bm, material)


def airoot_logo():
    with open(os.path.join(MEDIA, 'brand', 'airoot_logo_tris.json')) as f:
        return json.load(f)


def text(name, body, size, loc, material, rot=(0, 0, 0), extrude=0.0, align='CENTER', font_path=None):
    cu = bpy.data.curves.new(name, 'FONT')
    cu.body, cu.size, cu.extrude, cu.align_x, cu.align_y = body, size, extrude, align, 'CENTER'
    font_path = font_path or '/usr/share/fonts/truetype/lato/Lato-Black.ttf'
    if os.path.exists(font_path):
        cu.font = bpy.data.fonts.load(font_path, check_existing=True)
    ob = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(ob)
    cu.materials.append(material)
    return place(ob, loc, rot)


def uv_project(ob, axis='z', size=None, offset=(0.0, 0.0)):
    """Planar UVs along an axis mapped to 0..1 over the object's bounds (or `size` metres per repeat)."""
    me = ob.data
    if not me.uv_layers:
        me.uv_layers.new(name='UVMap')
    uv = me.uv_layers.active.data
    idx = {'z': (0, 1), 'y': (0, 2), 'x': (1, 2)}[axis]
    cs = [v.co for v in me.vertices]
    lo = [min(c[i] for c in cs) for i in idx]
    hi = [max(c[i] for c in cs) for i in idx]
    for poly in me.polygons:
        for li in poly.loop_indices:
            c = me.vertices[me.loops[li].vertex_index].co
            if size:
                uv[li].uv = (c[idx[0]] / size + offset[0], c[idx[1]] / size + offset[1])
            else:
                uv[li].uv = ((c[idx[0]] - lo[0]) / max(hi[0] - lo[0], 1e-9), (c[idx[1]] - lo[1]) / max(hi[1] - lo[1], 1e-9))
    return ob


def box_uv(ob, size=1.0):
    """Per-face box projection in metres / size (after transforms are applied)."""
    me = ob.data
    if not me.uv_layers:
        me.uv_layers.new(name='UVMap')
    uv = me.uv_layers.active.data
    for poly in me.polygons:
        n = poly.normal
        ax = max(range(3), key=lambda i: abs(n[i]))
        i0, i1 = [(1, 2), (0, 2), (0, 1)][ax]
        for li in poly.loop_indices:
            c = me.vertices[me.loops[li].vertex_index].co
            uv[li].uv = (c[i0] / size, c[i1] / size)
    return ob


def finalize(objs, name, smooth_angle=35.0):
    """Convert to meshes, apply modifiers and transforms, join into one object named `name`."""
    bpy.ops.object.select_all(action='DESELECT')
    objs = [o for o in objs if o is not None]
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.convert(target='MESH')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for o in objs:
        if not o.data.uv_layers:
            o.data.uv_layers.new(name='UVMap')
    if len(objs) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = ob.data.name = name
    for p in ob.data.polygons:
        p.use_smooth = True
    m = ob.modifiers.new('split', 'EDGE_SPLIT')
    m.split_angle = math.radians(smooth_angle)
    bpy.ops.object.modifier_apply(modifier=m.name)
    bpy.ops.object.select_all(action='DESELECT')
    return ob


def tri_count(ob):
    ob.data.calc_loop_triangles()
    return len(ob.data.loop_triangles)


def decimate(ob, ratio):
    m = ob.modifiers.new('dec', 'DECIMATE')
    m.ratio = ratio
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.modifier_apply(modifier=m.name)
    return ob


def export_glb(ob, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.export_scene.gltf(filepath=path, export_format='GLB', use_selection=True, export_apply=True,
                              export_yup=False, export_image_format='JPEG', export_jpeg_quality=88)
    return path


def export_obj(ob, path):
    """Wavefront OBJ in ROS axes (+X forward, +Z up) with normals, UVs and an .mtl."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True, forward_axis='Y', up_axis='Z',
                          export_triangulated_mesh=True, export_normals=True, export_uv=True,
                          export_materials=True, path_mode='STRIP')
    return path


def render(path, target=(0, 0, 0.3), dist=2.2, az=35.0, el=22.0, res=(1100, 760), samples=48, lens=55,
           ground=True, sun=3.5):
    """Quick studio render (Cycles, CPU) for review images."""
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.samples, sc.cycles.use_denoising = samples, True
    sc.cycles.device = 'CPU'
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.view_settings.view_transform = 'Filmic' if 'Filmic' in [i.identifier for i in type(sc.view_settings).bl_rna.properties['view_transform'].enum_items] else 'Standard'
    if sc.world is None:
        sc.world = bpy.data.worlds.new('world')
    sc.world.use_nodes = True
    bg = sc.world.node_tree.nodes['Background']
    bg.inputs[0].default_value = (0.62, 0.68, 0.76, 1)
    bg.inputs[1].default_value = 0.9
    for o in [o for o in sc.objects if o.name.startswith('_rv_')]:
        bpy.data.objects.remove(o, do_unlink=True)
    if ground:
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=30)
        g = _new_object('_rv_ground', bm, mat('_rv_ground', (0.42, 0.42, 0.43), 0.9))
        g.location = (0, 0, -0.001)
    ld = bpy.data.lights.new('_rv_sun', 'SUN')
    ld.energy, ld.angle = sun, math.radians(6)
    lo = bpy.data.objects.new('_rv_sun', ld)
    sc.collection.objects.link(lo)
    lo.rotation_euler = (math.radians(48), 0, math.radians(az + 70))
    cam = bpy.data.objects.new('_rv_cam', bpy.data.cameras.new('_rv_cam'))
    sc.collection.objects.link(cam)
    cam.data.lens = lens
    a, e = math.radians(az), math.radians(el)
    t = Vector(target)
    cam.location = t + Vector((dist * math.cos(e) * math.cos(a), dist * math.cos(e) * math.sin(a), dist * math.sin(e)))
    cam.rotation_euler = (t - cam.location).to_track_quat('-Z', 'Y').to_euler()
    sc.camera = cam
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    for o in [o for o in sc.objects if o.name.startswith('_rv_')]:
        bpy.data.objects.remove(o, do_unlink=True)
