# Periodic mission status published by the referee on /sparkx/mission/status (2 Hz).

uint8 WAITING=0      # robot spawned, cmd_vel gated (robot cannot move)
uint8 RUNNING=1      # mission clock running, cmd_vel forwarded to the robot
uint8 PAUSED=2       # organizer pause (clock stopped, cmd_vel gated)
uint8 FINISHED=3     # mission over (EndMission called, time limit, robot disabled, or aborted)

std_msgs/Header header
uint8 state
string state_text
string team_name
string world_name

float32 elapsed_s          # mission time (sim seconds while RUNNING)
float32 time_limit_s
float32 remaining_s

int32 score                # current automatic score (see RULES.md)
uint16 survivors_rescued
uint16 survivors_total     # 0 when the organizer hides the number of survivors
uint16 hints_released
uint16 collisions
uint16 false_reports
uint16 late_reports       # survivors at which the report window ran out
uint16 idle_penalties     # times the idle limit was exceeded
float32 robot_health       # 100 = intact; fire exposure reduces it; 0 = robot disabled
bool cmd_vel_enabled       # true when team commands are forwarded to the robot
string finish_reason       # set when state == FINISHED
