# Status of one received hint inside the team's mission memory.

string PENDING="PENDING"                     # received, not processed yet
string LANDMARK_UNKNOWN="LANDMARK_UNKNOWN"   # landmark not observed yet, keep exploring
string LANDMARK_AMBIGUOUS="LANDMARK_AMBIGUOUS"
string SEARCHING="SEARCHING"                 # landmark matched, searching the indicated area
string RESOLVED="RESOLVED"                   # led to a confirmed rescue
string FAILED="FAILED"                       # searched without success / unreachable

string hint_id
string status
string matched_object_id          # SemanticObject.id of the matched landmark
geometry_msgs/Point search_center # map frame
float32 search_radius_m
string note
