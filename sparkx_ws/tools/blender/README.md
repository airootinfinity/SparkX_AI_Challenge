# Blender asset scripts

Everything modelled for SparkX is produced by these scripts, so any part can be changed and
rebuilt instead of being edited by hand. They need Blender 4.2 LTS (no add-ons) and run headless.

```bash
BLENDER=~/tools/blender/blender-4.2.9-linux-x64/blender      # wherever Blender 4.2 is unpacked

# the rover (writes src/sparkx_description/meshes/rover_base.glb and rover_wheel.glb)
$BLENDER -b --python build_rover.py -- --render /tmp/rover_preview

# the world kit (writes src/sparkx_worlds/models/sparkx_kit/*.obj and kit.yaml)
$BLENDER -b --python build_kit.py                            # everything
$BLENDER -b --python build_kit.py -- --only tent,container --render /tmp/kit_preview

# bomb-damage decals and the war sky, rendered with Cycles and imported as textures
$BLENDER -b --python render_decals.py                        # ~1 minute on 20 threads
ros2 run sparkx_worlds make_textures                         # finishes the sky (smoke) and the generated decals

# turn a recorded run into H.264 (plays everywhere)
$BLENDER -b --python encode_video.py -- run.mp4 run_h264.mp4
```

`--render DIR` also writes preview images (Cycles, CPU).

After rebuilding, regenerate the worlds so they pick up the new parts:

```bash
cd ../../ && colcon build --packages-select sparkx_description sparkx_worlds
ros2 run sparkx_worlds make_practice_worlds
```

## Files

| File | Purpose |
|---|---|
| `sparkx_bpy.py` | Shared helpers: materials, primitives, lathe / tube / text, UV projection, export, preview render |
| `build_rover.py` | Husky-class rover in the Airoot livery. Geometry constants at the top must match the URDF |
| `build_kit.py` | World kit: landmarks, rubble, window / door sets, furniture, street furniture, base-camp gear |
| `render_decals.py` | Blender-rendered artwork: debris fields, shell craters, facade shell-holes (cut-out decals) and the war-sky panorama |
| `encode_video.py` | Re-encodes a `record_mission` video to H.264 with Blender's built-in ffmpeg |

## Rules the models follow

- Metres, +X forward, +Y left, +Z up. Rover parts are modelled in `base_link` coordinates.
- Rover: nothing may rise into the LiDAR's view (a 22.5 degree cone below the sensor at z = 0.78 m),
  and the body must stay inside the collision boxes declared in the URDF.
- Kit parts have no collision of their own. The generator gives each one a simple collision box,
  and a part must stay inside that box or above 1.2 m. Otherwise the robot's LiDAR would see an
  obstacle it can drive through, or hit one it cannot see.
- Kit parts are split into material roles (`body`, `frame`, `glass`, ...) rather than textured.
  The generator maps roles to its scanned materials (`sparkx_worlds/kit.py`, `ROLE_MATERIAL`) and
  re-projects UVs at real-world scale, which is how one container model comes in seven colours.

## Textures

Surface textures are not made in Blender. `ros2 run sparkx_worlds make_textures` builds them from
Poly Haven CC0 scans (`sparkx_worlds/pbr.py`) and draws the signs and the partner posters
(`sparkx_worlds/branding.py`). Brand source artwork is in `models/sparkx_media/brand/`.
