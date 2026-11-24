# Notable mission events published by the referee on /sparkx/mission/events.

string MISSION_STARTED="MISSION_STARTED"
string MISSION_PAUSED="MISSION_PAUSED"
string MISSION_RESUMED="MISSION_RESUMED"
string MISSION_FINISHED="MISSION_FINISHED"
string RESCUE_CONFIRMED="RESCUE_CONFIRMED"
string RESCUE_REJECTED="RESCUE_REJECTED"
string LATE_REPORT="LATE_REPORT"        # at a survivor for longer than the report window without a confirmed rescue
string IDLE="IDLE"                      # rover did not move for longer than the idle limit
string HINT_RELEASED="HINT_RELEASED"
string COLLISION="COLLISION"
string SURVIVOR_CONTACT="SURVIVOR_CONTACT"
string FIRE_DAMAGE="FIRE_DAMAGE"
string AFTERSHOCK="AFTERSHOCK"          # structural change: some routes may now be blocked
string ROBOT_FLIPPED="ROBOT_FLIPPED"
string ROBOT_DISABLED="ROBOT_DISABLED"
string INTERVENTION="INTERVENTION"      # manual intervention recorded by organizers
string TIME_WARNING="TIME_WARNING"
string MAP_SUBMITTED="MAP_SUBMITTED"
string RULE_VIOLATION="RULE_VIOLATION"    # forbidden access (e.g. /sparkx/referee_private/*); may end the run as DISQUALIFIED
string STACK_INTEGRITY="STACK_INTEGRITY"  # result of the locked-files check made when the referee starts

std_msgs/Header header
string type
string description
int32 score_delta
string ref_id              # related survivor/hint id, if any
