# One entry of a team's semantic memory (survivor or landmark), in the team "map" frame.

string STATUS_TENTATIVE="TENTATIVE"     # seen, not yet confirmed by repeated observations
string STATUS_CONFIRMED="CONFIRMED"     # confirmed landmark / survivor candidate
string STATUS_RESCUED="RESCUED"         # survivor rescue confirmed by the referee
string STATUS_REJECTED="REJECTED"       # rejected as false positive
string STATUS_UNREACHABLE="UNREACHABLE" # known but could not be reached

string id                        # team-assigned unique id
string object_class              # "survivor" or a landmark class from the vocabulary
string color                     # vocabulary colour (may be empty)
string label                     # optional text label (signs)
geometry_msgs/Point position     # map frame (origin = robot start pose)
float32 position_std_m
float32 confidence               # 0..1
uint32 num_observations
string status
string survivor_id               # referee survivor id (after confirmation), else empty
