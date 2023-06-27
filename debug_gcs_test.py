"""
Author: Alireza Ghaderi
Email: p30planets@gmail.com
GitHub: alireza787b
Repository: mavsdk_drone_show
Date: June 2023

This script is a command-line application used for Ground Control Station (GCS) to interact with drones in the MAVSDK drone show system.
It receives telemetry data from the drone and decodes it, then prints the decoded data to the console. 
The user can input commands to set the state of the drone and set the trigger time for the drone mission. 

The telemetry data received from the drone is encoded in a specific format and sent over a UDP connection. 
The command data sent to the drone is also encoded in the same format and sent over the same UDP connection. 

Telemetry Protocol:
The telemetry data is structured as follows:
- Header: This is always set to 77. It's used to identify the start of a telemetry data packet.
- HW_ID: This is the hardware ID of the drone.
- Pos_ID: This is the position ID of the drone.
- State: This is the current state of the drone.
- Trigger Time: This is the Unix timestamp when the drone mission should be triggered.
- Terminator: This is always set to 88. It's used to identify the end of a telemetry data packet.

Command Protocol:
The command data is structured as follows:
- Header: This is always set to 55. It's used to identify the start of a command data packet.
- HW_ID: This is the hardware ID of the drone.
- Pos_ID: This is the position ID of the drone.
- State: This is the state to be set on the drone.
- Trigger Time: This is the Unix timestamp when the drone mission should be triggered.
- Terminator: This is always set to 66. It's used to identify the end of a command data packet.

Example:
If we want to send a command to drone 1 at position 1 to set its state to 1 and trigger its mission at Unix timestamp 1673025600, 
the command data packet will be structured as [55, 1, 1, 1, 1673025600, 66].
"""

# Imports
import socket
import struct
import time
import threading

# Variables
gcs_ip = '172.22.128.1'  # IP of the GCS
coordinator_ip = '172.22.141.34'  # IP of the coordinator
debug_port = 13541  # Port of the GCS
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((gcs_ip, debug_port))

# This flag controls whether telemetry is printed to the screen
print_telemetry = True

# Function to handle telemetry
def handle_telemetry():
    global print_telemetry
    while True:
        # Receive telemetry data
        data, addr = sock.recvfrom(1024)
        
        # Ensure we received a correctly sized packet
        if len(data) == 9:
            # Decode the data
            header, hw_id, pos_id, state, trigger_time, terminator = struct.unpack('=BBBBIB', data)
            
            # Check if header and terminator are as expected
            if header == 77 and terminator == 88:
                # Print the received and decoded data if the flag is set
                if print_telemetry:
                    print(f"Received telemetry: Header={header}, HW_ID={hw_id}, Pos_ID={pos_id}, State={state}, Trigger Time={trigger_time}, Terminator={terminator}")
            else:
                print("Invalid header or terminator received in telemetry data.")
        else:
            print(f"Received packet of incorrect size. Expected 9, got {len(data)}.")

# Function to send commands
def send_command(n):
    # Prepare the command data
    header = 55
    hw_id = 1
    pos_id = 1
    state = 1
    trigger_time = int(time.time()) + n
    terminator = 66

    # Encode the data
    data = struct.pack('=B B B B I B', header, hw_id, pos_id, state, trigger_time, terminator)

    # Send the command data
    sock.sendto(data, (coordinator_ip, debug_port))
    print(f"Sent command: Header={header}, HW_ID={hw_id}, Pos_ID={pos_id}, State={state}, Trigger Time={trigger_time}, Terminator={terminator}")

# Start the telemetry thread
telemetry_thread = threading.Thread(target=handle_telemetry)
telemetry_thread.start()

# Main loop for command input
while True:
    try:
        command = input("Enter 't' to send a command, 'q' to quit: ")
        if command.lower() == 'q':
            break
        elif command.lower() == 't':
            print_telemetry = False
            n = input("Enter the number of seconds for the trigger time (or '0' to cancel): ")
            if int(n) == 0:
                print_telemetry = True
                continue
            send_command(int(n))
            print_telemetry = True
    except ValueError:
        print("Invalid input. Please enter a valid command.")

# Stop the telemetry thread before exiting
telemetry_thread.join()
print("Exiting the application...")