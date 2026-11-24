"""Re-encode a recorded run to H.264 so it plays everywhere (browsers, phones, slides).

  blender -b --python encode_video.py -- <in.mp4> <out.mp4>

`ros2 run sparkx_sim record_mission` writes MPEG-4 Part 2 video (the codec OpenCV ships with);
this uses the ffmpeg built into Blender to turn it into H.264 without installing anything else."""
import sys

import bpy

src, dst = sys.argv[sys.argv.index('--') + 1:][:2]
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
se = sc.sequence_editor_create()
strip = se.sequences.new_movie('run', src, channel=1, frame_start=1)
sc.frame_start, sc.frame_end = 1, strip.frame_final_duration
sc.render.resolution_x, sc.render.resolution_y = strip.elements[0].orig_width, strip.elements[0].orig_height
sc.render.resolution_percentage = 100
sc.render.fps = max(1, int(round(strip.fps)))
sc.render.image_settings.file_format = 'FFMPEG'
sc.render.ffmpeg.format = 'MPEG4'
sc.render.ffmpeg.codec = 'H264'
sc.render.ffmpeg.constant_rate_factor = 'MEDIUM'
sc.render.ffmpeg.ffmpeg_preset = 'GOOD'
sc.render.ffmpeg.gopsize = 40
sc.view_settings.view_transform = 'Standard'
sc.render.filepath = dst
bpy.ops.render.render(animation=True)
print(f'[encode] {dst}: {sc.frame_end} frames at {sc.render.fps} fps')
