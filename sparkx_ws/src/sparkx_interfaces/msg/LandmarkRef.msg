# Reference to a landmark using the published hint vocabulary
# (see GetMissionInfo.landmark_classes / colors). Never contains coordinates.

string landmark_class   # e.g. "water_tank", "container", "bus", "sign"; "marker" = a numbered location marker (label = its number)
string color            # e.g. "red"; empty when the class has no colour attribute
string label            # optional printed text (e.g. "PHARMACY" for class "sign"); usually empty
