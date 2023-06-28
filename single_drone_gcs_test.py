"""
Author: Alireza Ghaderi
Email: p30planets@gmail.com
GitHub: alireza787b
Repository: github.com/alireza787b/mavsdk_drone_show
Date: June 2023
---------------------------------------------------------------------------

Ground Control Station (GCS) Script for Drone Telemetry and Command Control
---------------------------------------------------------------------------

This script is designed to function as a Ground Control Station (GCS) in a drone network, providing functionality for receiving telemetry data from drones and
sending commands to them. The script communicates with the drones over User Datagram Protocol (UDP), and it can be easily configured and expanded to 
handle multiple drones simultaneously.

Setup and Configuration:
------------------------
The script is set up to read its configuration from a .csv file named 'config.csv' which should be located in the same directory as the script. The columns
in 'config.csv' should be as follows: hw_id, pos_id, x, y, ip, mavlink_port, debug_port, gcs_ip.

Each row in 'config.csv' corresponds to a drone. The 'hw_id' column indicates the hardware ID of the drone, the 'pos_id' gives its position ID, 'x' and 'y'
provide coordinates, 'ip' specifies the drone's IP address, 'mavlink_port' and 'debug_port' provide the ports for MAVLink communication and debug information,
and 'gcs_ip' specifies the IP address of the GCS.

The script is designed to work with a specific drone determined by the hardware ID specified in a file named 'i.hwID', where 'i' is the hardware ID of the drone.
This file should also be located in the same directory as the script.

Sim Mode:
---------
The script includes a 'sim_mode' boolean variable that allows the user to switch between simulation mode and real-world mode. When 'sim_mode' is set to True,
the script is in simulation mode, and the IP address of the coordinator (essentially the drone control node) should be manually defined in the code. 
If 'sim_mode' is False, the script uses the IP address from 'config.csv' for the drone with the hardware ID matching that in 'i.hwID'.

Communication Protocol:
-----------------------
The script communicates with the drone over UDP using binary packets. For telemetry data, these packets have the following structure:

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
Pos_ID = 3 (in binary: 00000011)
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
you will be asked to enter the number of seconds for the trigger time. You can enter '0' to cancel the command.

License:
--------
This script is open-source and available to use and modify as per the terms of the license agreement.

Disclaimer:
-----------
The script is provided as-is, and the authors and contributors are not responsible for any damage or loss resulting from its use.
Always ensure that you comply with all local laws and regulations when operating drones.

"""