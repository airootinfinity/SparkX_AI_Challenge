# Current high-level behaviour of the team's decision-making system.
# Teams publish this on /team/behavior_state whenever it changes (and >= 1 Hz).
std_msgs/Header header
string state                    # e.g. EXPLORE, APPROACH_SURVIVOR, CONFIRM_RESCUE, FOLLOW_CLUE, RETURN_TO_BASE
string detail                   # free text
geometry_msgs/Point target      # current navigation target (map frame), if any
