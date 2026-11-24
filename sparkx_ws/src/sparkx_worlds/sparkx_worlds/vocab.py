"""Published SparkX vocabulary (public information shared with teams).

Everything in this module is part of the public competition specification: it is exposed
through /sparkx/mission/get_info and documented in docs/INTERFACES.md and docs/RULES.md.
"""

RULES_VERSION = '1.1'   # 1.1: numbered location markers; clues carry a marker reference

LANDMARK_CLASSES = [
    'water_tank',   # cylindrical tank on legs, painted in one colour
    'container',    # 6 m shipping container, corrugated, one colour
    'bus',          # grey coach
    'fire_truck',   # red ladder truck
    'ambulance',    # white ambulance with red stripe
    'car',          # hatchback / SUV / pickup, colour attribute
    'dumpster',     # green waste container
    'sign',         # shop sign on a building facade; use LandmarkRef.label (e.g. PHARMACY)
    'fountain',     # dry stone fountain in a plaza
    'tent',         # relief tent, colour attribute
    'crater',       # blast crater (scorched ground + rubble rim)
    'marker',       # numbered location marker (ArUco tag beacon); LandmarkRef.label is its number
]

COLORS = ['red', 'blue', 'green', 'yellow', 'orange', 'white', 'gray', 'black']

SIGN_LABELS = ['PHARMACY', 'SCHOOL', 'HOTEL', 'BANK', 'POLICE', 'CAFE', 'HOSPITAL', 'MARKET']

RELATIONS = ['near', 'beside', 'inside', 'behind', 'opposite', 'north_of', 'south_of', 'east_of', 'west_of']

AREA_TYPES = ['room', 'building', 'street', 'rubble', 'open_area']

# Semantic label ids used by the (dataset-only) ground-truth bounding-box camera.
LABEL_IDS = {
    'survivor': 1, 'water_tank': 2, 'container': 3, 'bus': 4, 'fire_truck': 5, 'ambulance': 6,
    'car': 7, 'dumpster': 8, 'sign': 9, 'fountain': 10, 'tent': 11, 'mannequin': 12, 'fire': 13,
    'burnt_car': 14, 'barrier': 15, 'rock': 16,
}
LABEL_NAMES = {v: k for k, v in LABEL_IDS.items()}

# Relation semantics (used by the generator and documented for hint resolvers):
RELATION_RADIUS = {
    'beside': 4.0,     # target area within 4 m of the landmark surface
    'near': 8.0,       # target within 8 m of the landmark centre
    'behind': 7.0,     # within 7 m, on the side of the landmark facing away from the nearest street
    'opposite': 16.0,  # across the street, within 16 m
}

CARDINALS = {'east_of': 0.0, 'north_of': 1.5707963, 'west_of': 3.1415927, 'south_of': -1.5707963}
