"""Headless 4-view renderer. Run inside Blender:
blender -b model.blend --python-exit-code 1 -P src/render_views.py -- <outdir>
Cameras: front -Y, side +X, back +Y, top +Z. White background, Cycles CPU.
"""
import os
import sys

import bpy
from mathutils import Vector

outdir = sys.argv[sys.argv.index("--") + 1]
os.makedirs(outdir, exist_ok=True)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 32
scene.cycles.device = "CPU"
scene.render.resolution_x = 320
scene.render.resolution_y = 320
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"
if not scene.world:
    scene.world = bpy.data.worlds.new("W")
scene.world.use_nodes = True
bg = scene.world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (1, 1, 1, 1)
bg.inputs[1].default_value = 1.0

sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
sun.data.energy = 1.4
sun.rotation_euler = (0.8, 0.2, 0.5)
scene.collection.objects.link(sun)
area_data = bpy.data.lights.new("Key", "AREA")
area_data.energy = 120
area = bpy.data.objects.new("Key", area_data)
area.location = (0, -3, 2.5)
scene.collection.objects.link(area)

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
corners = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
lo = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
hi = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
center, size = (lo + hi) / 2, hi - lo
dist = max(size.x, size.y, size.z) * 2.0 + 1.0
views = {"front": center + Vector((0, -dist, 0)), "side": center + Vector((dist, 0, 0)),
         "back": center + Vector((0, dist, 0)), "top": center + Vector((0, 0, dist))}
for name, loc in views.items():
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    cam.location = loc
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = 55 if name != "top" else 35
    scene.collection.objects.link(cam)
    scene.camera = cam
    scene.render.filepath = os.path.join(outdir, name + ".png")
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam, do_unlink=True)
print("VIEWS_RENDERED", outdir)
