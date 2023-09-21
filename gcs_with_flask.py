"""
Author: Alireza Ghaderi
Email: p30planets@gmail.com
GitHub: alireza787b
Repository: github.com/alireza787b/mavsdk_drone_show
Date: August 2023
---------------------------------------------------------------------------

Ground Control Station (GCS) Script for Drone Telemetry and Command Control + flask web socket
---------------------------------------------------------------------------

This script is designed to function as a Ground Control Station (GCS) in a drone network, providing functionality for receiving telemetry data from drones and
sending commands to them. The script communicates with the drones over User Datagram Protocol (UDP), and it can be easily configured and expanded to 
handle multiple drones simultaneously.

Setup and Configuration:
------------------------
Flask server runs automatically with this file, sending telemetry data in JSON format to: 
http://localhost:5000/telemetry

For the React Ground Control Station (GCS) Interface:
- Run the 'start_dashboard.sh' script located in the 'apps' folder for linux based. 
  Alternatively, use the terminal to navigate to 'apps/dashboard/drone-dashboard' and execute 'npm start'.
- Once started, the GCS interface will be available at http://localhost:3000

Prerequisites:
- Ensure Flask, Node.js, and Python are installed on your system.

Additional Information:
- Detailed documentation is available in the 'docs' folder.
- For more insights and code details, refer to the GitHub repository: https://github.com/alireza787b/mavsdk_drone_show
- Video tutorials and demonstrations are available on the associated YouTube channel.



The script is set up to read its configuration from a .csv file named 'config.csv' which should be located in the same directory as the script. The columns
in 'config.csv' should be as follows: hw_id, pos_id, x, y, ip, mavlink_port, debug_port, gcs_ip.

Each row in 'config.csv' corresponds to a drone. The 'hw_id' column indicates the hardware ID of the drone, the 'pos_id' gives its position ID, 'x' and 'y'
provide coordinates, 'ip' specifies the drone's IP address, 'mavlink_port' and 'debug_port' provide the ports for MAVLink communication and debug information,
and 'gcs_ip' specifies the IP address of the GCS.

The script supports both single-drone and multiple-drone modes. The mode is determined by the 'single_drone' variable in the script. 
If 'single_drone' is True, the script will function in single-drone mode, where it communicates with a single drone specified by the hardware ID in a file 
named 'i.hwID', where 'i' is the hardware ID of the drone. This file should be located in the same directory as the script.
If 'single_drone' is False, the script operates in multiple-drone mode, communicating with all drones specified in the 'config.csv' file.

Sim Mode:
---------
The script includes a 'sim_mode' boolean variable that allows the user to switch between simulation mode and real-world mode. When 'sim_mode' is set to True,
the script is in simulation mode, and the IP address of the coordinator (essentially the drone control node) is manually defined in the code. 
If 'sim_mode' is False, the script uses the IP address from 'config.csv' for the drones.

Communication Protocol:
-----------------------
The script communicates with the drones over UDP using binary packets. For telemetry data, these packets have the following structure:

- Header (1 byte): A constant value of 77. 
- HW_ID (1 byte): The hardware ID of the drone.
- Pos_ID (1 byte): The position ID of the drone.
- State (1 byte): The current state of the drone.
- Trigger Time (4 bytes): The Unix timestamp when the data was sent.
- Terminator (1 byte): A constant value of 88.

For commands, the packets have a similar structure, but the header value is 55 and the terminator value is 66.

Each part of the packet is packed into a binary format using the struct.pack method from Python's 'struct' library.
The '=' character ensures that the bytes are packed in standard size, 'B' specifies an unsigned char (1 byte), and 'I' specifies an unsigned int (4 bytes).

Example:
--------
For example, a command packet could look like this in binary:

Header = 55 (in binary: 00110111)
HW_ID = 3 (in binary: 00000011)
Pos_ID = 3 (in binary: 

00000011)
State = 1 (in binary: 00000001)
Trigger Time = 1687840743 (in binary: 11001010001100001101101100111111)
Terminator = 66 (in binary: 01000010)

The whole packet in binary would look like this:
00110111 00000011 00000011 00000001 11001010001100001101101100111111 01000010

Please note that the actual binary representation would be a sequence of 8-bit binary numbers.
The above representation is simplified to demonstrate the concept.

Running the script:
-------------------
To run the script, simply execute it in a Python environment. You will be prompted to enter commands for the drone.
You can enter 't' to send a command to the drone or 'q' to quit the script. If you choose to send a command,
you will be asked to enter the number of seconds for the trigger time. During this time, telemetry data will not be printed. 
You can enter '0' to cancel the command and resume printing of telemetry data.

License:
--------
This script is open-source and available to use and modify as per the terms of the license agreement.

Disclaimer:
-----------
The script is provided as-is, and the authors and contributors are not responsible for any damage or loss resulting from its use.
Always ensure that you comply with all local laws and regulations when operating drones.

"""


import csv
import logging
import shutil
import socket
import struct
import subprocess
from flask import Flask, jsonify, make_response, send_from_directory
from flask import request, send_file

from threading import Thread, Lock
import time
import pandas as pd
import os
import math
from enum import Enum
from flask_cors import CORS
import zipfile
from werkzeug.utils import secure_filename
import shutil


FORWARDING_IPS = ['172.27.18.28']  # Add IPs here as strings e.g. ['192.168.1.2', '192.168.1.3']


# Imports
telemetry_data_all_drones = {}
telemetry_lock = Lock()

class State(Enum):
    IDLE = 0
    ARMED = 1
    TRIGGERED = 2

class Mission(Enum):
    NONE = 0
    DRONE_SHOW_FROM_CSV = 1
    SMART_SWARM = 2
    TAKE_OFF = 10
    LAND = 101
    HOLD = 102
    TEST = 100



flask_telem_socket_port = 5000

# Sim Mode
sim_mode = False  # Set this variable to True for simulation mode (the ip of all drones will be the same)

telem_struct_fmt = '=BHHBBIddddddddBIB'
command_struct_fmt = '=B B B B B I B'

telem_packet_size = struct.calcsize(telem_struct_fmt)
command_packet_size = struct.calcsize(command_struct_fmt)

# Setup logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Single Drone
single_drone = False  # Set this to True for single drone connection

# Read the config file
config_df = pd.read_csv('config.csv')

# Drones list
drones = []

if single_drone:
    # Read the hardware ID from the '.hwID' file
    hw_id_file = [file for file in os.listdir() if file.endswith('.hwID')][0]  # Assuming there's only one such file
    hw_id = int(hw_id_file.split('.')[0])  # Extract the hw_id

    # Find the configuration for the drone in the 'config.csv' file
    drone_config = config_df.loc[config_df['hw_id'] == hw_id].iloc[0]
    drones = [drone_config]
else:
    # Add all drones from config file to drones list
    drones = [drone for _, drone in config_df.iterrows()]

# Function to send commands
def send_command(trigger_time, sock, coordinator_ip, debug_port, hw_id, pos_id, mission, state):
    try:
        # Debug: Log before sending command
        logger.debug(f"Preparing to send command to HW_ID={hw_id}, POS_ID={pos_id}")

        # Prepare the command data
        header = 55  # Constant
        terminator = 66  # Constant

        # Encode the data
        data = struct.pack(command_struct_fmt, header, hw_id, pos_id, mission, state, trigger_time, terminator)

        print(f"Sending command with mission code: {mission}")  # Add this line


        # Send the command data
        sock.sendto(data, (coordinator_ip, debug_port))
        logger.info(f"Sent {len(data)} byte command: Header={header}, HW_ID={hw_id}, Pos_ID={pos_id}, Mission={mission}, State={state}, Trigger Time={trigger_time}, Terminator={terminator}")

    except (OSError, struct.error) as e:
        # If there is an OSError or an error in packing the data, log the error
        logger.error(f"An error occurred: {e}")



def retry_pending_commands():
    while True:
        time.sleep(1)  # Sleep for 1 second between each iteration
        current_time = int(time.time())
        with telemetry_lock:  # Lock to ensure thread safety
            for hw_id, command_data in list(pending_commands.items()):  # Make a copy of items to safely modify the dictionary
                if current_time - command_data['timestamp'] > 5:  # If more than 5 seconds have passed
                    if command_data['retries'] < 5:  # Maximum of 5 retries
                        # Resend the command (You'll need to adjust this part to fit your actual send_command function)
                        send_command(command_data['trigger_time'], sock, coordinator_ip, debug_port, hw_id, pos_id, command_data['mission'], command_data['state'])
                        # Update the number of retries and timestamp
                        command_data['retries'] += 1
                        command_data['timestamp'] = current_time
                    else:
                        # Remove this command from pending_commands if max retries reached
                        del pending_commands[hw_id]

def get_optional_altitude(mission):
    if 10 <= mission < 60:  # Range for takeoff commands with altitude
        return f" (Altitude: {mission % 10}m)"
    return ""


def handle_telemetry(keep_running, print_telemetry, sock):
    """
    This function continuously receives and handles telemetry data.
    It updates the global telemetry data and checks for any pending commands
    that have been successfully executed.

    :param keep_running: A control flag for the while loop. 
                         When it's False, the function stops receiving data.
    :param print_telemetry: A flag to control if the telemetry data should be printed.
    :param sock: The socket from which data will be received.
    """
    global telemetry_data_all_drones  # Declare it as global so that we can modify it
    global pending_commands  # Declare it as global so that we can modify it

    while keep_running[0]:
        try:
            # Debug: Log at the beginning of receiving telemetry
            logger.debug("Waiting to receive telemetry data...")
            # Receive telemetry data
            data, addr = sock.recvfrom(1024)

            # If received data is not of correct size, log the error and continue
            if len(data) != telem_packet_size:
                logger.error(f"Received packet of incorrect size. Expected {telem_packet_size}, got {len(data)}.")
                continue

            # Decode the data
            telemetry_data = struct.unpack(telem_struct_fmt, data)
            header, terminator = telemetry_data[0], telemetry_data[-1]
            hw_id, pos_id, state, mission, trigger_time, position_lat, position_long, position_alt, velocity_north, velocity_east, velocity_down, yaw, battery_voltage, follow_mode, telemetry_update_time = telemetry_data[1:-1]
                        # Inside your existing code
            if 10 <= mission < 60:
                optional_altitude = get_optional_altitude(mission)
                mission = 10  # Resetting mission to the default takeoff code
                logger.debug(f"Unpacked Telemetry: HW_ID={hw_id}, Pos_ID={pos_id}, State={State(state).name}, Mission={Mission(mission).name}{optional_altitude}, Trigger Time={trigger_time}")
            else:
                logger.debug(f"Unpacked Telemetry: HW_ID={hw_id}, Pos_ID={pos_id}, State={State(state).name}, Mission={Mission(mission).name}, Trigger Time={trigger_time}")
            # If header or terminator are not as expected, log the error and continue
            if header != 77 or terminator != 88:
                logger.error("Invalid header or terminator received in telemetry data.")
                continue

            # Forwarding the received telemetry data to the specified IPs
            for ip in FORWARDING_IPS:
                try:
                    sock.sendto(data, (ip, sock.getsockname()[1]))  # Using the same port as the receiving port
                except Exception as e:
                    logger.error(f"Error forwarding telemetry to IP {ip}: {e}")

            # Update global telemetry data for all drones
            with telemetry_lock:
                telemetry_data_all_drones[hw_id] = {
                    'Pos_ID': pos_id,
                    'State': State(state).name,
                    'Mission': Mission(mission).name,
                    'Position_Lat': position_lat,
                    'Position_Long': position_long,
                    'Position_Alt': position_alt,
                    'Velocity_North': velocity_north,
                    'Velocity_East': velocity_east,
                    'Velocity_Down': velocity_down,
                    'Yaw': yaw,
                    'Battery_Voltage': battery_voltage,
                    'Follow_Mode': follow_mode,
                    'Update_Time': telemetry_update_time
                }
            
            # Check for pending commands
            with telemetry_lock:
                if hw_id in pending_commands:
                    logger.debug(f"Found pending command for HW_ID={hw_id}. Checking...")

                    pending_command = pending_commands[hw_id]
                    if pending_command['mission'] == Mission(mission).name and pending_command['state'] == State(state).name and pending_command['trigger_time'] == trigger_time:
                        # Remove this command from the pending commands as it has been successfully executed
                        del pending_commands[hw_id]
            
            # If the print_telemetry flag is True, print the decoded data
            if print_telemetry[0]:
                # Debug log with all details
                logger.debug(f"Received telemetry at {telemetry_update_time}: Header={header}, HW_ID={hw_id}, Pos_ID={pos_id}, State={State(state).name}, Mission={Mission(mission).name}, Trigger Time={trigger_time}, Position Lat={position_lat}, Position Long={position_long}, Position Alt={position_alt:.1f}, Velocity North={velocity_north:.1f}, Velocity East={velocity_east:.1f}, Velocity Down={velocity_down:.1f}, Yaw={yaw:.1f}, Battery Voltage={battery_voltage:.1f}, Follow Mode={follow_mode}, Terminator={terminator}")
                
        except (OSError, struct.error) as e:
            # If there is an OSError or an error in unpacking the data, log the error and break the loop
            logger.error(f"An error occurred: {e}")
            break

# Drones threads
drones_threads = []

# This flag indicates if the telemetry threads should keep running.
# We use a list so the changes in the main thread can be seen by the telemetry threads.
keep_running = [True]

# Dictionary to hold pending commands for each drone
pending_commands = {}  # Key: hw_id, Value: {'mission': mission, 'state': state, 'trigger_time': trigger_time, 'retries': 0, 'timestamp': timestamp}






app = Flask(__name__)
CORS(app)  # Enable CORS

@app.route('/telemetry', methods=['GET'])
def get_telemetry():
    with telemetry_lock:
        return jsonify(telemetry_data_all_drones)

@app.route('/send_command', defaults={'drone_ids': 'all'}, methods=['POST'])
@app.route('/send_command/<drone_ids>', methods=['POST'])
def send_command_to_drones(drone_ids):
    try:
        command_data = request.get_json()
        print(request.json)  # Debug line

        mission_type = command_data['missionType']
        trigger_time = int(command_data['triggerTime'])
        
        # Here you can process altitude from the mission code if it's a TAKEOFF command
        if mission_type == 10:  # Assuming 10 is the code for TAKEOFF
            altitude = command_data.get('altitude', 10)
            if altitude > 50:
                altitude = 50
            mission_type += altitude  # Add the altitude to the mission_type
        
        mission, state = convert_mission_type(mission_type)

        if drone_ids == 'all':
            target_drones = [hw_id for _, _, _, _, hw_id, _ in drones_threads]
        else:
            target_drones = list(map(int, drone_ids.split(',')))

        for sock, _, coordinator_ip, debug_port, hw_id, pos_id in drones_threads:
            if hw_id in target_drones:
                send_command(trigger_time, sock, coordinator_ip, debug_port, hw_id, pos_id, mission, state)

        return jsonify({'status': 'success', 'message': f'Command sent to drones {target_drones}'})

    except Exception as e:
        print(f"An error occurred while sending command: {e}")
        return jsonify({'status': 'error', 'message': str(e)})


    
    
@app.route('/save-swarm-data', methods=['POST'])
def save_swarm_data():
    try:
        data = request.json
        # Convert the JSON data to CSV format
        csv_data = "hw_id,follow,offset_n,offset_e,offset_alt\n"
        for drone in data:
            csv_data += f"{drone['hw_id']},{drone['follow']},{drone['offset_n']},{drone['offset_e']},{drone['offset_alt']}\n"
        
        # Save to swarm.csv
        with open('swarm.csv', 'w') as file:
            file.write(csv_data)
        
        return {"message": "Data saved successfully"}, 200
    except Exception as e:
        return {"message": f"Error: {str(e)}"}, 500
    
    
@app.route('/save-config-data', methods=['POST'])
def save_config_data():
    data = request.json
    try:
        # Ensure that all drones have essential properties before writing to CSV
        if not all('hw_id' in drone for drone in data):
            return jsonify({"message": "Incomplete data received. Every drone must have an 'hw_id'."}), 400

        # Specify column order
        column_order = ["hw_id", "pos_id", "x", "y", "ip", "mavlink_port", "debug_port", "gcs_ip"]

        with open('config.csv', 'w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=column_order)
            writer.writeheader()
            for drone in data:
                writer.writerow({col: str(drone.get(col, "")).strip() for col in column_order})


        return jsonify({"message": "Configuration saved successfully!"}), 200
    except Exception as e:
        return jsonify({"message": "Error saving configuration!", "error": str(e)}), 500

    
    
@app.route('/get-swarm-data', methods=['GET'])
def get_swarm_data():
    with open('swarm.csv', 'r') as f:
        reader = csv.DictReader(f)
        data = [row for row in reader]
    return jsonify(data)

@app.route('/get-config-data', methods=['GET'])
def get_config_data():
    with open('config.csv', 'r') as f:
        reader = csv.DictReader(f)
        data = [row for row in reader]
    return jsonify(data)



ALLOWED_EXTENSIONS = {'zip'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
           
# Function to clear show directories
def clear_show_directories():
    directories = [
        'shapes/swarm/skybrush',
        'shapes/swarm/processed',
        'shapes/swarm/plots'
    ]
    for directory in directories:
        print(f"Clearing directory: {directory}")  # Debugging line
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print(f'Failed to delete {file_path}. Reason: {e}')  # Debugging line


# Updated route in Flask
@app.route('/import-show', methods=['POST'])
def import_show():
    uploaded_file = request.files.get('file')
    
    if uploaded_file and allowed_file(uploaded_file.filename):
        clear_show_directories()  # Clear existing files

        # Store the uploaded ZIP file temporarily
        zip_path = os.path.join('temp', 'uploaded.zip')
        uploaded_file.save(zip_path)

        # Unzip the file
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall('shapes/swarm/skybrush')

        # Remove the temporary ZIP file
        os.remove(zip_path)

        # Run the processformation.py script
        try:
            completed_process = subprocess.run(["python3", "process_formation.py"], capture_output=True, text=True, check=True)
            print("Have {} bytes in stdout:\n{}".format(len(completed_process.stdout), completed_process.stdout))
        except subprocess.CalledProcessError as e:
            print(str(e))
            return jsonify({'success': False, 'error': 'Error in running processformation.py', 'details': str(e)})
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Invalid file type. Please upload a ZIP file.'})




@app.route('/get-show-plots/<filename>')
def send_image(filename):
    print("Trying to serve:", filename)
    print("From directory:", os.path.abspath('shapes/swarm/plots'))
    return send_from_directory('shapes/swarm/plots', filename)

@app.route('/get-show-plots', methods=['GET'])
def get_show_plots():
    plots_directory = 'shapes/swarm/plots'
    filenames = [f for f in os.listdir(plots_directory) if f.endswith('.png')]
    
    # Check if 'all_drones.png' is in filenames
    if 'all_drones.png' in filenames:
        upload_time = time.ctime(os.path.getctime(os.path.join(plots_directory, 'all_drones.png')))
    else:
        upload_time = "unknown"
    
    return jsonify({'filenames': filenames, 'uploadTime': upload_time})



@app.route('/get-first-last-row/<string:hw_id>', methods=['GET'])
def get_first_last_row(hw_id):
    try:
        # Construct the full path to the drone's CSV file
        csv_path = os.path.join("shapes", "swarm", "skybrush", f"Drone {hw_id}.csv")

        # Read the CSV file into a DataFrame
        df = pd.read_csv(csv_path)

        # Get the first and last row
        first_row = df.iloc[0]
        last_row = df.iloc[-1]

        # Extract the x, y coordinates
        first_x = first_row['x [m]']
        first_y = first_row['y [m]']
        last_x = last_row['x [m]']
        last_y = last_row['y [m]']

        return jsonify({
            "success": True,
            "firstRow": {"x": first_x, "y": first_y},
            "lastRow": {"x": last_x, "y": last_y}
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})



# Function to convert mission type to mission and state values
def convert_mission_type(mission_type):
    if isinstance(mission_type, str):
        if mission_type == 's':
            return 2, 1  # Smart Swarm
        elif mission_type == 'd':
            return 1, 1  # Drone Show
        elif mission_type == 'n':
            return 0, 0  # Cancel Mission/Disarm
        else:
            return 0, 0  # Invalid command
    elif isinstance(mission_type, int):
        if 10 <= mission_type <= 60:  # Takeoff to specific altitude
            return mission_type, 1
        elif mission_type == 101:  # Land
            return mission_type, 1
        elif mission_type == 102:  # Hold Position
            return mission_type, 1
        elif mission_type == 100:  # Test
            return mission_type, 1
        else:
            return 0, 0  # Invalid command
    else:
        return 0, 0  # Invalid command




def run_flask():
    # Start the retry thread
    retry_thread = Thread(target=retry_pending_commands)
    retry_thread.start()
    app.run(host='0.0.0.0', port=flask_telem_socket_port)

flask_thread = Thread(target=run_flask)
flask_thread.daemon = True
flask_thread.start()

try:
    for drone_config in drones:
        # Extract variables
        if sim_mode:
            coordinator_ip = '172.22.141.34'  # WSL IP
        else:
            coordinator_ip = drone_config['ip']
        debug_port = int(drone_config['debug_port'])  # Debug port
        gcs_ip = drone_config['gcs_ip']  # GCS IP
        hw_id = drone_config['hw_id']  # Hardware ID
        pos_id = drone_config['pos_id']  # Position ID

        # Log information
        logger.info(f"Drone {hw_id} is listening and sending on IP {coordinator_ip} and port {debug_port}")

        # Socket for communication
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('0.0.0.0', debug_port))

        # This flag controls whether telemetry is printed to the screen. 
        # We use a list so the changes in the main thread can be seen by the telemetry threads.
        print_telemetry = [True]

        # Start the telemetry thread
        telemetry_thread = Thread(target=handle_telemetry, args=(keep_running, print_telemetry, sock))
        telemetry_thread.daemon = True  # Set the thread as a daemon thread
        telemetry_thread.start()


        # Add to the drones_threads
        drones_threads.append((sock, telemetry_thread, coordinator_ip, debug_port, hw_id, pos_id))
    # Main loop for command input

# Removed the command line since it is not needed anymore since we have GUI. if you want to reactivate it remmeber in SSH when mulitple termials open there might be some problem


    mission = 0
    state = 0
    n = 0
    
    #Removed the commandline input becuase it is no longer needed since we have a GUI. if you need that make sure you take care of auto linux startup since it might have problem when multiple terminal opens in one termina in one SSH. you might need to pass 'g' to startup 
    while True:
        pass
    
    # while True:
    #     command = input("\n Enter 's' for swarm, 'c' for csv_droneshow, 'n' for none, 'q' to quit: \n")
    #     if command.lower() == 'q':
    #         break
    #     elif command.lower() == 's':
    #         mission = 2  # Setting mission to smart_swarm
    #         n = input("\n Enter the number of seconds for the trigger time (or '0' to cancel): \n")
    #         if int(n) == 0:
    #             continue
    #         state = 1
    #     elif command.lower() == 'c':
    #         mission = 1  # Setting mission to csv_droneshow
    #         n = input("\n Enter the number of seconds for the trigger time (or '0' to cancel): \n")
    #         if int(n) == 0:
    #             continue
    #         state = 1
    #     elif command.lower() == 'n':
    #         mission = 0  # Unsetting the mission
    #         state = 0
    #         n = 0  # Unsetting the trigger time
    #     else:
    #         logger.warning("Invalid command.")
    #         continue

    #     # Turn off telemetry printing while sending commands
    #     for _, _, _, _, _, _ in drones_threads:
    #         print_telemetry[0] = False
    #     # Send command to each drone
    #     for sock, _, coordinator_ip, debug_port, hw_id, pos_id in drones_threads:
    #         trigger_time = int(time.time()) + int(n)  # Now + n seconds
    #         send_command(trigger_time, sock, coordinator_ip, debug_port, hw_id, pos_id, mission, state)
    #     # Turn on telemetry printing after sending commands
    #     for _, _, _, _, _, _ in drones_threads:
    #         print_telemetry[0] = True
except (ValueError, OSError, KeyboardInterrupt) as e:
    # Catch any exceptions that occur during the execution
    logger.error(f"An error occurred: {e}")
finally:
    # When KeyboardInterrupt happens or an error occurs, stop the telemetry threads
    # keep_running[0] = False

    # for sock, telemetry_thread, _, _, _, _ in drones_threads:
    #     # Close the socket
    #     sock.close()
    #     # Join the thread
    #     telemetry_thread.join()

    # # Join the Flask thread
    # flask_thread.join()
    pass

logger.info("Exiting the application...")
