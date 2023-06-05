import random  as rnd
import pandas as pd
import numpy as np
import csv
from typing import Any, Dict
import numpy as np
import itertools


from scipy.spatial.transform import Rotation as R

def compute_initial_climb(drone_id, drone_show_params):
    # Get the initial position and altitude
    initial_pos = drone_show_params['home_position'] + np.array([drone_id, 0, 0])
    initial_alt = drone_show_params['initial_altitude']
    
    # Compute the total climb time
    climb_time = initial_alt / drone_show_params['travel_speed']
    
    # Compute the number of steps during the climb
    num_steps = int(climb_time / drone_show_params['step_time'])
    
    # Initialize lists to store the position, velocity, and acceleration at each step
    positions = []
    velocities = []
    accelerations = []
    
    # Compute the position, velocity, and acceleration at each step
    for i in range(num_steps):
        t = i * drone_show_params['step_time']
        
        # Compute the current position, velocity, and acceleration
        pos = initial_pos + np.array([0, 0, t * drone_show_params['travel_speed']])
        vel = np.array([0, 0, drone_show_params['travel_speed']])
        acc = np.array([0, 0, 0])
        
        # Append to the lists
        positions.append(pos)
        velocities.append(vel)
        accelerations.append(acc)
    
    # Return the lists of positions, velocities, and accelerations
    return positions, velocities, accelerations



def read_drone_positions(file_path: str) -> pd.DataFrame:
    """
    Reads the 'drone_positions.csv' file and stores the data in a pandas DataFrame.

    Args:
        file_path (str): The path to the 'drone_positions.csv' file.

    Returns:
        pd.DataFrame: A pandas DataFrame containing the drone positions.
    """
    drone_positions = pd.read_csv(file_path)
    return drone_positions


def detect_conflicts(drone_paths: Dict[int, Dict[str, Dict[str, np.array]]], safety_threshold: float):
    conflicts = []
    
    # Loop over all pairs of drones
    for (drone_id_1, path_dict_1), (drone_id_2, path_dict_2) in itertools.combinations(drone_paths.items(), 2):
        # For each system, check the conflicts
        for system in ['drone_system', 'viewer_system', 'home_system']:
            path_1 = path_dict_1[system]
            path_2 = path_dict_2[system]
            # Make sure the paths have the same length
            if len(path_1['positions']) != len(path_2['positions']):
                print(f"Warning: Paths for drones {drone_id_1} and {drone_id_2} have different lengths in {system}!")
            
            # Loop over each time step
            for i in range(min(len(path_1['positions']), len(path_2['positions']))):
                # Compute the distance between the two drones at this time step
                distance = np.linalg.norm(path_1['positions'][i] - path_2['positions'][i])
                
                # If the distance is less than the safety threshold, record this as a conflict
                if distance < safety_threshold:
                    conflicts.append((drone_id_1, drone_id_2, i, distance, system))
    
    return conflicts




def calculate_drone_path(drone_id: int, initial_pos: np.array, final_pos: np.array, max_speed: float, safety_threshold: float, drone_show_params: Dict[str, Any]) -> np.array:
    """
    Calculates the path for a drone from its initial position to its final position.

    Args:
        drone_id (int): The ID of the drone.
        initial_pos (np.array): The initial position of the drone.
        final_pos (np.array): The final position of the drone.
        max_speed (float): The maximum speed the drone can achieve.
        safety_threshold (float): The safety threshold distance.

    Returns:
        np.array: An array containing the path of the drone.
    """
    # The drone will start and stop at rest, so the initial and final velocities and accelerations are zero
    initial_vel = final_vel = initial_acc = final_acc = np.array([0, 0, 0])
    
    # Compute the time required to reach the final position at maximum speed
    distance = np.linalg.norm(final_pos - initial_pos)
    travel_time = distance / max_speed

    # Compute the coefficients of the quintic polynomial
    a_0 = initial_pos
    a_1 = initial_vel
    a_2 = 0.5 * initial_acc
    a_3 = 10.0 * (final_pos - initial_pos) - (4.0 * final_vel + 6.0 * initial_vel) * travel_time - (3.0 * initial_acc - final_acc) * travel_time**2
    a_3 /= travel_time**3
    a_4 = (15.0 * (initial_pos - final_pos) + (7.0 * final_vel + 8.0 * initial_vel) * travel_time + (3.0 * initial_acc - 2.0 * final_acc) * travel_time**2) / travel_time**4
    a_5 = (6.0 * (final_pos - initial_pos) - 3.0 * (final_vel + initial_vel) * travel_time - (2.0 * initial_acc - final_acc) * travel_time**2) / travel_time**5
    
    # Compute the number of steps
    num_steps = int(travel_time / drone_show_params['step_time'])
    
    # Initialize lists to store the position, velocity, and acceleration at each step
    positions = []
    velocities = []
    accelerations = []
    
    # Compute the position, velocity, and acceleration at each step
    for i in range(num_steps):
        t = i * drone_show_params['step_time']
        
        # Compute the current position, velocity, and acceleration
        pos = a_0 + a_1*t + a_2*t**2 + a_3*t**3 + a_4*t**4 + a_5*t**5
        vel = a_1 + 2*a_2*t + 3*a_3*t**2 + 4*a_4*t**3 + 5*a_5*t**4
        acc = 2*a_2 + 6*a_3*t + 12*a_4*t**2 + 20*a_5*t**3
        
        # Append to the lists
        positions.append(pos)
        velocities.append(vel)
        accelerations.append(acc)
    
    # Return the lists of positions, velocities, and accelerations
    return positions, velocities, accelerations


def create_drone_csv(drone_id: int, drone_path: np.array, initial_altitude: float, hold_time: float, file_path: str) -> None:
    """
    Creates a CSV file containing the trajectory information for a drone.

    Args:
        drone_id (int): The ID of the drone.
        drone_path (np.array): An array containing the path of the drone.
        initial_altitude (float): The initial altitude of the drone.
        hold_time (float): The hold time.
        file_path (str): The path to the csv file to be created.
    """
    # Create a DataFrame from the drone_path
    df = pd.DataFrame(drone_path, columns=['x', 'y', 'z', 'vx', 'vy', 'vz', 'ax', 'ay', 'az'])

    # Add the initial altitude and hold time as new columns to the DataFrame
    df['initial_altitude'] = initial_altitude
    df['hold_time'] = hold_time

    # Write the DataFrame to a CSV file
    df.to_csv(file_path, index=False)


def create_drone_csv(drone_id: int, drone_path: np.array, initial_altitude: float, hold_time: float, file_path: str) -> None:
    """
    Creates a CSV file containing the trajectory information for a drone.

    Args:
        drone_id (int): The ID of the drone.
        drone_path (np.array): An array containing the path of the drone.
        initial_altitude (float): The initial altitude of the drone.
        hold_time (float): The hold time.
        file_path (str): The path to the csv file to be created.
    """
    # TODO: Implement the CSV file creation here
    pass


def resolve_conflicts(drone_paths: Dict[int, np.array], safety_threshold: float) -> Dict[int, np.array]:
    """
    Resolves any safety threshold violations.

    Args:
        drone_paths (Dict[int, np.array]): A dictionary containing the paths of all drones.
        safety_threshold (float): The safety threshold distance.

    Returns:
        Dict[int, np.array]: A dictionary containing the resolved paths of all drones.
    """
    # TODO: Implement the conflict resolution algorithm here
    pass

def generate_trajectories(drone_positions: pd.DataFrame, drone_show_params: Dict[str, Any]):
    drone_paths = {}

    # Loop over each row in the DataFrame
    for index, row in drone_positions.iterrows():
        # Compute the initial position of the drone in three different systems
        # Drone system:
        initial_pos_drone_system = np.array([0, 0, 0])

        # Viewer system:
        initial_pos_viewer_system = drone_show_params['home_position'] + np.array([index, 0, 0])
        # initial_pos_viewer_system[2] = drone_show_params['initial_altitude']  # Setting the z-coordinate to the initial altitude

        # Home position system:
        initial_pos_home_system = np.array([index, 0, 0])
        # initial_pos_home_system[2] = drone_show_params['initial_altitude']  # Setting the z-coordinate to the initial altitude

        # Compute the final position of the drone
        final_pos = np.array([row['px'], row['py'], row['pz']])

        # Calculate the drone path in each system
        drone_path_drone_system = calculate_drone_path(index, initial_pos_drone_system, final_pos, drone_show_params['travel_speed'], drone_show_params['safety_threshold'], drone_show_params)
        drone_path_viewer_system = calculate_drone_path(index, initial_pos_viewer_system, final_pos, drone_show_params['travel_speed'], drone_show_params['safety_threshold'], drone_show_params)
        drone_path_home_system = calculate_drone_path(index, initial_pos_home_system, final_pos, drone_show_params['travel_speed'], drone_show_params['safety_threshold'], drone_show_params)

        # Store the drone path in the dictionary for each system
        for drone_path, system in zip([drone_path_drone_system, drone_path_viewer_system, drone_path_home_system], ['drone_system', 'viewer_system', 'home_system']):
            positions, velocities, accelerations = drone_path
            if index not in drone_paths:
                drone_paths[index] = {}
            drone_paths[index][system] = {
                'positions': np.array(positions),
                'velocities': np.array(velocities),
                'accelerations': np.array(accelerations),
            }

    


        # Resolve any conflicts in the drone paths
        resolved_drone_paths = resolve_conflicts(drone_paths, drone_show_params['safety_threshold'])

        # Create CSV files for the drones' trajectories
        for drone_id, drone_path in resolved_drone_paths.items():
            create_drone_csv(drone_id, drone_path, drone_show_params['initial_altitude'], drone_show_params['hold_time'], f"trajectories/drone{drone_id}.csv")
    return drone_paths

    # Resolve any conflicts in the drone paths
def resolve_conflicts(drone_paths: Dict[int, np.array], safety_threshold: float) -> Dict[int, np.array]:
    conflicts = detect_conflicts(drone_paths, safety_threshold)
    
    # This function currently does not resolve conflicts, only prints them
    for conflict in conflicts:
        drone_id_1, drone_id_2, i, distance, system = conflict
        print(f"Conflict between drones {drone_id_1} and {drone_id_2} at time step {i} in {system}. Distance: {distance}")

    return drone_paths



def main():
    # Load the CSV file with the drone positions
    drone_positions = read_drone_positions('shapes/static_shapes/active/drone_positions.csv')

    # Define the parameters for the drone show
    drone_show_params = {
        'home_position': np.array([0, 0, 0]),
        'initial_altitude': 10,
        'travel_speed': 10,
        'safety_threshold': 2,
        'step_time': 0.1,
        'hold_time': 2,
        'return_to_launch': True,
    }

    # Generate the trajectories for each drone
    generate_trajectories(drone_positions, drone_show_params)

if __name__ == "__main__":
    main()
