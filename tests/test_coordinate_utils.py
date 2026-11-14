# tests/test_coordinate_utils.py
"""
Coordinate Utilities Tests
==========================
Tests for coordinate transformation functions in src/coordinate_utils.py.
"""

import pytest
import os
import tempfile


class TestLatlonToNe:
    """Test latlon_to_ne function"""

    def test_origin_returns_zero(self):
        """Test that origin point returns (0, 0)"""
        from src.coordinate_utils import latlon_to_ne

        origin_lat, origin_lon = 37.7749, -122.4194
        north, east = latlon_to_ne(origin_lat, origin_lon, origin_lat, origin_lon)

        assert abs(north) < 0.01  # Should be essentially 0
        assert abs(east) < 0.01

    def test_north_of_origin(self):
        """Test point north of origin has positive north"""
        from src.coordinate_utils import latlon_to_ne

        origin_lat, origin_lon = 37.7749, -122.4194
        # Point 0.001 degrees north (roughly 111 meters)
        point_lat = origin_lat + 0.001
        point_lon = origin_lon

        north, east = latlon_to_ne(point_lat, point_lon, origin_lat, origin_lon)

        assert north > 100  # Should be roughly 111 meters north
        assert north < 120
        assert abs(east) < 1  # East should be near 0

    def test_east_of_origin(self):
        """Test point east of origin has positive east"""
        from src.coordinate_utils import latlon_to_ne

        origin_lat, origin_lon = 37.7749, -122.4194
        # Point 0.001 degrees east (roughly 87 meters at this latitude)
        point_lat = origin_lat
        point_lon = origin_lon + 0.001

        north, east = latlon_to_ne(point_lat, point_lon, origin_lat, origin_lon)

        assert abs(north) < 1  # North should be near 0
        assert east > 80  # Should be roughly 87 meters east
        assert east < 95

    def test_south_of_origin(self):
        """Test point south of origin has negative north"""
        from src.coordinate_utils import latlon_to_ne

        origin_lat, origin_lon = 37.7749, -122.4194
        point_lat = origin_lat - 0.001
        point_lon = origin_lon

        north, east = latlon_to_ne(point_lat, point_lon, origin_lat, origin_lon)

        assert north < -100  # Should be roughly -111 meters
        assert north > -120

    def test_west_of_origin(self):
        """Test point west of origin has negative east"""
        from src.coordinate_utils import latlon_to_ne

        origin_lat, origin_lon = 37.7749, -122.4194
        point_lat = origin_lat
        point_lon = origin_lon - 0.001

        north, east = latlon_to_ne(point_lat, point_lon, origin_lat, origin_lon)

        assert east < -80  # Should be roughly -87 meters west
        assert east > -95


class TestGetExpectedPositionFromTrajectory:
    """Test get_expected_position_from_trajectory function"""

    def test_reads_first_waypoint(self, tmp_path):
        """Test reading first waypoint from CSV"""
        from src.coordinate_utils import get_expected_position_from_trajectory

        # Create a mock trajectory directory structure
        trajectory_dir = tmp_path / "shapes" / "swarm" / "processed"
        trajectory_dir.mkdir(parents=True)

        # Create a mock trajectory CSV
        csv_file = trajectory_dir / "Drone 1.csv"
        csv_file.write_text("t,px,py,pz,vx,vy,vz\n0.0,10.5,20.3,5.0,0,0,0\n1.0,11.0,21.0,5.0,0.5,0.7,0\n")

        north, east = get_expected_position_from_trajectory(1, sim_mode=False, base_dir=str(tmp_path))

        assert north == 10.5
        assert east == 20.3

    def test_sim_mode_uses_shapes_sitl(self, tmp_path):
        """Test that sim_mode uses shapes_sitl directory"""
        from src.coordinate_utils import get_expected_position_from_trajectory

        # Create a mock trajectory directory for SITL
        trajectory_dir = tmp_path / "shapes_sitl" / "swarm" / "processed"
        trajectory_dir.mkdir(parents=True)

        # Create a mock trajectory CSV
        csv_file = trajectory_dir / "Drone 1.csv"
        csv_file.write_text("t,px,py,pz,vx,vy,vz\n0.0,100.0,200.0,10.0,0,0,0\n")

        north, east = get_expected_position_from_trajectory(1, sim_mode=True, base_dir=str(tmp_path))

        assert north == 100.0
        assert east == 200.0

    def test_missing_file_returns_none(self, tmp_path):
        """Test that missing file returns (None, None)"""
        from src.coordinate_utils import get_expected_position_from_trajectory

        north, east = get_expected_position_from_trajectory(999, sim_mode=False, base_dir=str(tmp_path))

        assert north is None
        assert east is None

    def test_empty_file_returns_none(self, tmp_path):
        """Test that empty file returns (None, None)"""
        from src.coordinate_utils import get_expected_position_from_trajectory

        # Create directory structure
        trajectory_dir = tmp_path / "shapes" / "swarm" / "processed"
        trajectory_dir.mkdir(parents=True)

        # Create empty CSV (just header)
        csv_file = trajectory_dir / "Drone 1.csv"
        csv_file.write_text("t,px,py,pz,vx,vy,vz\n")

        north, east = get_expected_position_from_trajectory(1, sim_mode=False, base_dir=str(tmp_path))

        assert north is None
        assert east is None

    def test_default_base_dir_is_cwd(self, tmp_path, monkeypatch):
        """Test that None base_dir uses current working directory"""
        from src.coordinate_utils import get_expected_position_from_trajectory

        # Create directory structure in tmp_path
        trajectory_dir = tmp_path / "shapes" / "swarm" / "processed"
        trajectory_dir.mkdir(parents=True)

        # Create trajectory CSV
        csv_file = trajectory_dir / "Drone 1.csv"
        csv_file.write_text("t,px,py,pz,vx,vy,vz\n0.0,5.0,6.0,7.0,0,0,0\n")

        # Change to tmp_path
        monkeypatch.chdir(tmp_path)

        north, east = get_expected_position_from_trajectory(1, sim_mode=False, base_dir=None)

        assert north == 5.0
        assert east == 6.0

    def test_env_base_dir_fallback_is_used_when_cwd_differs(self, tmp_path, monkeypatch):
        """Test that MDS_BASE_DIR is honored when the process cwd is elsewhere."""
        from src.coordinate_utils import get_expected_position_from_trajectory

        trajectory_dir = tmp_path / "shapes_sitl" / "swarm" / "processed"
        trajectory_dir.mkdir(parents=True)
        csv_file = trajectory_dir / "Drone 7.csv"
        csv_file.write_text("t,px,py,pz,vx,vy,vz\n0.0,12.0,-3.5,0.0,0,0,0\n")

        other_dir = tmp_path / "unrelated"
        other_dir.mkdir()

        monkeypatch.chdir(other_dir)
        monkeypatch.setenv("MDS_BASE_DIR", str(tmp_path))

        north, east = get_expected_position_from_trajectory(7, sim_mode=True, base_dir=None)

        assert north == 12.0
        assert east == -3.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

def test_get_expected_position_rejects_nonfinite_first_waypoint(tmp_path):
    """Fail closed when trajectory first px/py is nan/inf."""
    import math
    from src.coordinate_utils import get_expected_position_from_trajectory

    traj_dir = tmp_path / "shapes" / "swarm" / "processed"
    traj_dir.mkdir(parents=True)
    csv_path = traj_dir / "Drone 1.csv"
    csv_path.write_text("t,px,py,pz\n0,nan,1.0,0\n", encoding="utf-8")
    north, east = get_expected_position_from_trajectory(1, base_dir=str(tmp_path))
    assert north is None and east is None

    csv_path.write_text("t,px,py,pz\n0,inf,2.0,0\n", encoding="utf-8")
    north, east = get_expected_position_from_trajectory(1, base_dir=str(tmp_path))
    assert north is None and east is None

    csv_path.write_text("t,px,py,pz\n0,1.5,2.5,0\n", encoding="utf-8")
    north, east = get_expected_position_from_trajectory(1, base_dir=str(tmp_path))
    assert north == 1.5 and east == 2.5
    assert math.isfinite(north) and math.isfinite(east)

