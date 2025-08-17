import socket
import threading
import argparse
import sys
HOST = '0.0.0.0'  # Listen on all available interfaces
PORT = 65432      # The port for our application
BUFFER_SIZE = 1024 # Size of the data buffer for receiving messages

class Peer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connection = None # Will hold the connection socket to the other peer

    def _receive_handler(self):
        while True:
            try:
                data = self.connection.recv(BUFFER_SIZE)
                if not data:
                    print("\n[!] Connection lost with the other peer.")
                    break
                message = data.decode('utf-8')
                print(f"\r[Peer] says: {message}\nYou> ", end="")

            except (ConnectionResetError, ConnectionAbortedError):
                print("\n[!] Connection was closed by the other peer.")
                break
            except Exception as e:
                print(f"\n[!] An error occurred in receiver thread: {e}")
                break
        print("[!] Closing connection.")
        self.connection.close()
        sys.exit(0)


    def _send_handler(self):
        try:
            print("--- Session Active ---")
            print("Type your messages and press Enter to send.")
            print("Type 'exit' to close the session.")
            
            while True:
                message = input("You> ")
                if message.lower() == 'exit':
                    break
                self.connection.sendall(message.encode('utf-8'))
        finally:
            print("[!] Closing your connection.")
            self.connection.close()

    def start_session(self):
        receiver = threading.Thread(target=self._receive_handler, daemon=True)
        receiver.start()
        self._send_handler()

    def listen(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        print(f"[*] Listening for connections on {self.host}:{self.port}...")
        print(f"Your IP Address: {socket.gethostbyname(socket.gethostname())}")
        self.socket.bind((self.host, self.port))
        self.socket.listen(1) 

        conn, addr = self.socket.accept()
        print(f"\n[*] Received connection from {addr[0]}:{addr[1]}")

        try:
            request = conn.recv(BUFFER_SIZE).decode('utf-8')
            if request == "CONNECT_REQUEST":
                consent = input(f"\r[*] Peer {addr[0]} wants to connect. Accept? (y/n): ")
                
                if consent.lower().strip() == 'y':
                    print("[*] You accepted the connection. Sending approval.")
                    conn.sendall(b'CONNECT_ACCEPT')
                    self.connection = conn
                    self.start_session()
                else:
                    print("[*] You denied the connection. Sending denial.")
                    conn.sendall(b'CONNECT_DENY')
                    conn.close()
            else:
                print(f"[!] Invalid connection request from {addr[0]}. Denying.")
                conn.sendall(b'CONNECT_DENY')
                conn.close()
        except Exception as e:
            print(f"[!] Handshake failed: {e}")
            conn.close()

    def connect(self, peer_host, peer_port):
        try:
            print(f"[*] Attempting to connect to {peer_host}:{peer_port}...")
            self.socket.connect((peer_host, peer_port))
            self.connection = self.socket # Use the main socket for the connection
            
            print("[*] Sending connection request...")
            self.connection.sendall(b'CONNECT_REQUEST')
            
            response = self.connection.recv(BUFFER_SIZE).decode('utf-8')
            if response == "CONNECT_ACCEPT":
                print("[*] Connection accepted by peer!")
                self.start_session()
            else:
                print("[!] Connection denied by peer.")
                self.connection.close()

        except ConnectionRefusedError:
            print(f"[!] Connection failed. Is the other peer listening?")
        except Exception as e:
            print(f"[!] An error occurred: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="P2P Session-Based Chat Application")
    
    parser.add_argument("-l", "--listen", action="store_true", help="Run in listening mode")
    
    parser.add_argument("-c", "--connect", type=str, help="IP address of the peer to connect to")
    
    args = parser.parse_args()

    peer = Peer(HOST, PORT)

    if args.listen:
        peer.listen()
    elif args.connect:
        peer.connect(args.connect, PORT)
    else:
        parser.print_help()
