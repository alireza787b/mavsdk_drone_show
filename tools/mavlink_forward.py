import socket

def forward_mavlink(src_ip, src_port, dest_ip, dest_port):
    # Create a UDP socket for receiving messages
    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock.bind((src_ip, src_port))
    
    # Create another UDP socket for sending messages
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(f"Listening for incoming MAVLink messages on {src_ip}:{src_port}")
    print(f"Forwarding MAVLink messages to {dest_ip}:{dest_port}")

    try:
        while True:
            # Receive MAVLink message from source
            data, addr = recv_sock.recvfrom(4096)
            
            # Forward the received message to the destination
            send_sock.sendto(data, (dest_ip, dest_port))
    except KeyboardInterrupt:
        print("Received Ctrl+C. Terminating.")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        recv_sock.close()
        send_sock.close()
        print("Sockets closed.")

if __name__ == "__main__":
    # Replace these variables with the actual IPs and ports you want to use
    SRC_IP = "0.0.0.0"
    SRC_PORT = 14550
    DEST_IP = "100.100.184.90"
    DEST_PORT = 14550

    forward_mavlink(SRC_IP, SRC_PORT, DEST_IP, DEST_PORT)
