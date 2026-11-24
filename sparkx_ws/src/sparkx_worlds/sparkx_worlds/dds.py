"""Minimal writer for uncompressed DDS cubemaps (the format Gazebo's ogre2 sky accepts)."""
import struct

import numpy as np


def write_cubemap(path, faces):
    """faces: six HxWx3 uint8 RGB arrays in the order +X, -X, +Y, -Y, +Z, -Z (square, same size)."""
    h, w = faces[0].shape[:2]
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x8            # CAPS | HEIGHT | WIDTH | PIXELFORMAT | PITCH
    pf = struct.pack('<8I', 32, 0x41, 0, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)   # BGRA8
    hdr = struct.pack('<7I', 124, flags, h, w, w * 4, 0, 1) + b'\0' * 44 + pf + struct.pack('<5I', 0x1008, 0xFE00, 0, 0, 0)
    with open(path, 'wb') as f:
        f.write(b'DDS ' + hdr)
        for a in faces:
            a = np.asarray(a, np.uint8)
            bgra = np.dstack([a[..., 2], a[..., 1], a[..., 0], np.full(a.shape[:2], 255, np.uint8)])
            f.write(bgra.tobytes())
