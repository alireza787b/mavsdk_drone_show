import navpy
from mavsdk.offboard import PositionNedYaw

def global_to_local(global_position, home_position):
    # Convert latitude and longitude to the local coordinate system
    lla_ref = [home_position.latitude_deg, home_position.longitude_deg, home_position.absolute_altitude_m]
    lla = [global_position.latitude_deg, global_position.longitude_deg, global_position.absolute_altitude_m]

    ned = navpy.lla2ned(lla[0], lla[1], lla[2],
                        lla_ref[0], lla_ref[1], lla_ref[2])

    # Return the local position
    return PositionNedYaw(ned[0], ned[1], ned[2], 0.0)
