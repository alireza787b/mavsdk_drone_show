import socket
import threading

def forward_data(recv_sock, send_sock, dest_ip, dest_port):
    while True:
        try:
            # Receive data from source
            data, addr = recv_sock.recvfrom(4096)
            
            # Forward the received message to the destination
            send_sock.sendto(data, (dest_ip, dest_port))
        except Exception as e:
            print(f"An error occurred in forward_data: {e}")

def main(src_ip, src_port, dest_ip, dest_port):
    # Create a UDP socket for receiving messages from drone to GCS
    recv_sock1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock1.bind((src_ip, src_port))
    
    # Create a UDP socket for receiving messages from GCS to drone
    recv_sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock2.bind(('0.0.0.0', dest_port))  # Bind to all available network interfaces
    
    # Create UDP sockets for sending messages
    send_sock1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    send_sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(f"Forwarding from {src_ip}:{src_port} to {dest_ip}:{dest_port} and vice versa.")

    # Create threads for bidirectional forwarding
    thread1 = threading.Thread(target=forward_data, args=(recv_sock1, send_sock1, dest_ip, dest_port))
    thread2 = threading.Thread(target=forward_data, args=(recv_sock2, send_sock2, src_ip, src_port))

    # Start the threads
    thread1.start()
    thread2.start()

    # Wait for both threads to finish
    thread1.join()
    thread2.join()

if __name__ == "__main__":
    # Replace these variables with the actual IPs and ports you want to use
    SRC_IP = "100.102.184.87"  # Make sure this IP is configured on your machine
    SRC_PORT = 14550
    DEST_IP = "100.100.184.90"
    DEST_PORT = 14550

    main(SRC_IP, SRC_PORT, DEST_IP, DEST_PORT)
