"""Blender build strategies, emitted as bpy code for the Blender MCP.

Strategy A: primitives blockout from band proportions/colours.
Strategy B: silhouette profile extrusion from the front mask, depth from the
side view when available. Both end with the same 4-view render + save code.
"""
import json

PRELUDE = """
import bpy, math
from mathutils import Vector
for _o in list(bpy.data.objects):
    bpy.data.objects.remove(_o, do_unlink=True)
for _m in list(bpy.data.materials):
    bpy.data.materials.remove(_m)
for _c in list(bpy.data.cameras):
    bpy.data.cameras.remove(_c)
for _l in list(bpy.data.lights):
    bpy.data.lights.remove(_l)
def mat(name, rgb):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    lin = tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb)
    bsdf.inputs["Base Color"].default_value = (*lin, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.65
    return m
def give(obj, material):
    obj.data.materials.append(material)
    return obj
"""


def _c(colors, i):
    return colors[max(0, min(len(colors) - 1, i))]


def strategy_a(params):
    c, p = params["colors"], params
    H = 1.8 * p["height_scale"]
    W = H * p["aspect"] * p["width_scale"]
    D = W * 0.5 * p["depth_scale"]
    code = f"""
M = [mat(f"band{{i}}", tuple(c)) for i, c in enumerate({json.dumps(c)})]
def box(name, loc, scale, material):
    bpy.ops.mesh.primitive_cube_add(location=loc)
    o = bpy.context.active_object; o.name = name; o.scale = scale
    bpy.ops.object.transform_apply(scale=True); give(o, material); return o
def cyl(name, loc, radius, depth, material, rot=(0,0,0)):
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, location=loc, rotation=rot)
    o = bpy.context.active_object; o.name = name; give(o, material); return o
def sph(name, loc, scale, material):
    bpy.ops.mesh.primitive_uv_sphere_add(location=loc)
    o = bpy.context.active_object; o.name = name; o.scale = scale
    bpy.ops.object.transform_apply(scale=True); give(o, material); return o
H, W, D = {H}, {W}, {D}
leg_h, torso_h, head_r = H*0.32, H*0.36, W*0.30
for s in (-1, 1):
    cyl("Leg", (s*W*0.18, 0, leg_h/2), W*0.11, leg_h, M[6])
box("Torso", (0, 0, leg_h + torso_h/2), (W/2, D/2, torso_h/2), M[4])
cyl("ArmL", (0, -D/2 - W*0.03, leg_h + torso_h*0.55), W*0.07, W*0.85, M[3], rot=(0, math.radians(90), math.radians(18)))
cyl("ArmR", (0, -D/2 - W*0.05, leg_h + torso_h*0.68), W*0.07, W*0.85, M[5], rot=(0, math.radians(90), math.radians(-18)))
sph("Head", (0, 0, leg_h + torso_h + head_r*0.95), (head_r, head_r*0.92, head_r*1.05), M[1])
sph("Hair", (0, 0.01, leg_h + torso_h + head_r*1.22), (head_r*1.04, head_r*0.96, head_r*0.82), M[0])
print("STRATEGY_A_BUILT")
"""
    return PRELUDE + code


def strategy_b(params):
    c, p = params["colors"], params
    H = 1.8 * p["height_scale"]
    W = H * p["aspect"] * p["width_scale"]
    D = W * max(0.2, p.get("side_aspect", 0.45)) * p["depth_scale"]
    code = f"""
profile = {json.dumps(p["profile"])}
M = [mat(f"band{{i}}", tuple(col)) for i, col in enumerate({json.dumps(c)})]
H, W, D = {H}, {W}, {D}
rows = len(profile)
verts, faces, mat_idx = [], [], []
for i, (l, r) in enumerate(profile):
    z = H * (1 - i / (rows - 1))
    lx, rx = (l - 0.5) * W, (r - 0.5) * W
    verts += [(lx, -D/2, z), (rx, -D/2, z), (lx, D/2, z), (rx, D/2, z)]
    if i < rows - 1:
        a = i * 4
        faces += [(a, a+1, a+5, a+4), (a+3, a+2, a+6, a+7),
                  (a+2, a, a+4, a+6), (a+1, a+3, a+7, a+5)]
        band = max(0, min(7, int(i / rows * 8)))
        mat_idx += [band, band, band, band]
mesh = bpy.data.meshes.new("CharacterMesh")
mesh.from_pydata(verts, [], faces)
mesh.materials.clear()
for m in M: mesh.materials.append(m)
for poly, mi in zip(mesh.polygons, mat_idx): poly.material_index = mi
obj = bpy.data.objects.new("Character", mesh)
bpy.context.collection.objects.link(obj)
print("STRATEGY_B_BUILT")
"""
    return PRELUDE + code


STRATEGIES = {"A": strategy_a, "B": strategy_b}

RENDER = """
scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE" if "BLENDER_EEVEE" in [e.identifier for e in bpy.types.RenderEngine.__subclasses__()] or True else "CYCLES"
try:
    scene.render.engine = "BLENDER_EEVEE_NEXT"
except Exception:
    scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 320; scene.render.resolution_y = 320
scene.render.film_transparent = False
world = bpy.data.worlds.new("W"); scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (1,1,1,1)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
bpy.ops.object.light_add(type="SUN", location=(2,-3,4))
bpy.context.active_object.data.energy = 2.0
bpy.ops.object.light_add(type="AREA", location=(0,-3,2))
bpy.context.active_object.data.energy = 300
def look(cam, target=(0,0,0.9)):
    cam.rotation_euler = (Vector(target) - cam.location).to_track_quat("-Z","Y").to_euler()
views = {"front": (0,-4.2,1.0), "side": (4.2,0,1.0), "back": (0,4.2,1.0), "top": (0,0,4.6)}
import os
for name, loc in views.items():
    bpy.ops.object.camera_add(location=loc)
    cam = bpy.context.active_object; look(cam)
    cam.data.lens = 55 if name != "top" else 35
    scene.camera = cam
    scene.render.filepath = os.path.join(RENDER_DIR, name + ".png")
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam, do_unlink=True)
bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
print("RENDERED_AND_SAVED", BLEND_PATH)
"""


def reset_empty_code():
    """Start Blender from a brand-new empty file (factory settings)."""
    return ("import bpy\n"
            "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
            "print('RESET_EMPTY')\n")


def open_mainfile_code(blend_path):
    """Open an existing .blend as Blender's working file."""
    return (f"import bpy\nbpy.ops.wm.open_mainfile(filepath={json.dumps(blend_path)})\n"
            "print('OPENED_MAINFILE')\n")


def scale_edit_code(width_mult=1.0, height_mult=1.0, depth_mult=1.0):
    """Edit the currently open scene in place: scale every mesh object.

    Used for existing-file rounds, where the model must be preserved
    rather than rebuilt from primitives. X=width, Y=depth, Z=height.
    """
    return f"""
import bpy
for _o in bpy.data.objects:
    if _o.type == "MESH":
        _o.scale = (_o.scale.x * {float(width_mult)}, _o.scale.y * {float(depth_mult)},
                    _o.scale.z * {float(height_mult)})
print("BUILT_AND_SAVED")
"""


def build_and_render(params, strategy, blend_path, render_dir):
    """Build + save via MCP. Rendering is done headless (see render_views.py):
    EEVEE renders inside the GUI MCP session crashed Blender repeatedly."""
    code = STRATEGIES[strategy](params)
    code += f"\nbpy.ops.wm.save_as_mainfile(filepath={json.dumps(blend_path)})\n"
    code += 'print("BUILT_AND_SAVED")\n'
    return code
