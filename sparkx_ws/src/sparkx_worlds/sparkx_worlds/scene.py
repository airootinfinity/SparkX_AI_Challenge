"""Scene accumulator shared by the SparkX world-generation modules."""
import math

import numpy as np

from .placer import Placer
from .sdfgen import StaticGroup


def yaw_rot(yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([[c, -s], [s, c]])


def catalog_box(entry, pose, shrink=None):
    """Collision box row [cx cy cz sx sy sz r p y] of a catalog model placed at pose (x y z r p y).
    Must match assets.build_model_sdf (box centred on the mesh extents, shrunk in x/y)."""
    mn, mx = np.array(entry['min']), np.array(entry['max'])
    size = np.maximum(mx - mn, 0.05)
    center = (mx + mn) / 2
    if shrink is None:
        shrink = 0.9 if entry['kind'] == 'vehicle' else 0.8
    size = size * np.array([shrink, shrink, 1.0])
    x, y, z, r, p, yw = pose
    from .geometry import rpy_matrix
    R = rpy_matrix(r, p, yw)
    c = R @ center + np.array([x, y, z])
    return [float(c[0]), float(c[1]), float(c[2]), float(size[0]), float(size[1]), float(size[2]),
            float(r), float(p), float(yw)]


class Scene:
    def __init__(self, name, xmin, ymin, xmax, ymax, rng):
        self.name = name
        self.bounds = (xmin, ymin, xmax, ymax)
        self.rng = rng
        self.groups = {}
        self.models = []          # SDF strings of standalone models
        self.lights = []          # SDF strings
        self.extra_boxes = []     # (row, tag) collisions of standalone models
        self.landmarks = []       # landmark records (public vocabulary objects)
        self.buildings = []       # Building objects
        self.fires = []           # dict(id, x, y, radius, temperature)
        self.survivor_slots = []  # candidate survivor locations
        self.survivors = []
        self.decoys = []
        self.street_segments = [] # dict(id, rect, axis, blocked)
        self.blockages = []       # static blockages
        self.aftershocks = []     # candidate dynamic blockages
        self.placer = Placer(xmin - 2, ymin - 2, xmax + 2, ymax + 2, 0.2)
        self.epicenter = ((xmin + xmax) / 2, (ymin + ymax) / 2, 0.0)
        self.blocks = []
        self._counter = {}

    def uid(self, prefix):
        k = self._counter.get(prefix, 0)
        self._counter[prefix] = k + 1
        return f'{prefix}_{k}'

    def group(self, name):
        if name not in self.groups:
            self.groups[name] = StaticGroup(name)
        return self.groups[name]

    def add_model(self, sdf, boxes=(), tag='solid', mark=True):
        self.models.append(sdf)
        for row in boxes:
            self.extra_boxes.append((list(row), tag))
            if mark:
                self.placer.mark_box(row)

    def all_boxes(self):
        rows, tags = [], []
        for g in self.groups.values():
            rows.extend(g.collisions)
            tags.extend(g.col_tags)
        for row, tag in self.extra_boxes:
            rows.append(row)
            tags.append(tag)
        return np.array(rows, float).reshape(-1, 9), tags

    def add_landmark(self, cls, color, x, y, z, yaw, size, label='', **extra):
        lm = dict(id=self.uid('lm'), cls=cls, color=color, label=label, x=float(x), y=float(y), z=float(z),
                  yaw=float(yaw), size=[float(s) for s in size])
        lm.update(extra)
        self.landmarks.append(lm)
        return lm
