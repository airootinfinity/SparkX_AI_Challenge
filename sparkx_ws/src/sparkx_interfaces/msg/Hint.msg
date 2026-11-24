# A clue released by the referee when a survivor rescue is confirmed.
# Hints describe WHERE other people may be relative to a landmark.
# They never expose coordinates or map data. A hint is a search lead only:
# the target must still be detected by perception and confirmed via ReportSurvivor.

# Spatial relations (published vocabulary)
string NEAR="near"            # within ~approx_distance_m (default ~6 m) of the landmark
string BESIDE="beside"        # directly next to the landmark (~3 m), same side of any wall
string INSIDE="inside"        # inside the structure/room that the landmark is located in or attached to
string BEHIND="behind"        # on the far side of the landmark as seen from the nearest street
string OPPOSITE="opposite"    # across the street from the landmark
string NORTH_OF="north_of"    # cardinal relations use world ENU (+Y north). Convert with
string SOUTH_OF="south_of"    #   GetMissionInfo.start_heading_enu_rad (robot yaw in ENU at start).
string EAST_OF="east_of"
string WEST_OF="west_of"

# Area types
string AREA_ROOM="room"
string AREA_BUILDING="building"
string AREA_STREET="street"
string AREA_RUBBLE="rubble"
string AREA_OPEN="open_area"

string hint_id
string source_survivor_id     # survivor whose rescue released this hint
builtin_interfaces/Time stamp # sim time of release

uint8 people_count            # number of people mentioned (>= 1)
string relation               # one of the relation constants above
LandmarkRef landmark          # reference landmark
string area_type              # one of the AREA_* constants (may be empty)
float32 approx_distance_m     # coarse distance from the landmark; 0 = unspecified
string text                   # human-readable sentence, e.g. "Someone is beside the red water tank, about 9 m north-east of marker 12."

# Position relative to a numbered location marker (the ArUco tag beacons at street junctions and
# beside landmarks, dictionary DICT_4X4_100). Present on every clue when the world has markers.
# The marker's own position is NOT given: the robot has to have seen marker `marker_id` to use this.
int32 marker_id               # tag number; -1 = this clue has no marker reference
float32 marker_bearing_deg    # compass bearing from the marker to the person: 0 = north (+Y of world ENU),
                              #   90 = east (+X); rounded to 5 degrees. Convert to the map frame with
                              #   GetMissionInfo.start_heading_enu_rad.
float32 marker_distance_m     # distance from the marker to the person, rounded to 1 m
