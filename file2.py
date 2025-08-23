# p2p_host_client_app.py
# A threaded P2P application supporting a central host and multiple clients.

import socket
import threading
import argparse
import sys
import os

# --- Constants ---
HOST = '0.0.0.0'  # Listen on all available interfaces
PORT = 65432      # The port for our application
BUFFER_SIZE = 1024 # Size of the data buffer

class P2PNode:
    """Represents a node in the P2P network, can act as a Host or a Client."""

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # For the Host: a list to keep track of all client connections and their addresses
        self.clients = []
        # For the Client: the connection to the host
        self.connection = None

    # --- HOST FUNCTIONALITY ---

    def _broadcast(self, message, sender_conn):
        """Sends a message to all connected clients except the sender."""
        # Use a copy of the list for safe iteration while potentially modifying the original
        for client_conn, client_addr in list(self.clients):
            if client_conn != sender_conn:
                try:
                    client_conn.sendall(message)
                except socket.error:
                    # If sending fails, assume the client is disconnected
                    self._remove_client(client_conn, client_addr)

    def _remove_client(self, conn, addr):
        """Removes a client from the list of connections."""
        if (conn, addr) in self.clients:
            self.clients.remove((conn, addr))
            print(f"[*] Client {addr[0]}:{addr[1]} has disconnected.")
            disconnect_msg = f"--- User {addr[0]} has left the chat ---".encode('utf-8')
            self._broadcast(disconnect_msg, conn)
            conn.close()

    def _client_handler(self, conn, addr):
        """
        Each client gets a dedicated thread running this function.
        It handles receiving messages and broadcasting them.
        """
        print(f"[*] New connection from {addr[0]}:{addr[1]}. Session active.")
        welcome_msg = f"--- User {addr[0]} has joined the chat ---".encode('utf-8')
        self._broadcast(welcome_msg, conn)

        while True:
            try:
                data = conn.recv(BUFFER_SIZE)
                if not data:
                    break # Connection closed by client
                
                # Prepend the sender's address to the message for identification
                message_to_broadcast = f"[{addr[0]}] says: ".encode('utf-8') + data
                print(f"Received from {addr[0]}: {data.decode('utf-8')}")
                self._broadcast(message_to_broadcast, conn)

            except (ConnectionResetError, ConnectionAbortedError):
                break # Client disconnected abruptly
        
        self._remove_client(conn, addr)

    def _accept_connections_handler(self):
        """Runs in a separate thread to continuously accept new client connections."""
        while True:
            try:
                conn, addr = self.socket.accept()
                self.clients.append((conn, addr))
                thread = threading.Thread(target=self._client_handler, args=(conn, addr))
                thread.daemon = True
                thread.start()
            except OSError: # Socket has been closed, so we can exit the loop
                break
            except Exception as e:
                print(f"[!] Error accepting connections: {e}")
                break

    def _host_send_handler(self):
        """Handles user input for the host to send messages."""
        print("--- Host is running. Type messages to broadcast. Type 'exit' to shut down. ---")
        while True:
            message = input("Host> ")
            if message.lower() == 'exit':
                break
            
            # Format the host's message
            formatted_message = f"[HOST] says: {message}".encode('utf-8')
            # Broadcast it to all clients. Pass `None` for sender_conn so it goes to everyone.
            self._broadcast(formatted_message, None)

    def start_host(self):
        """Starts the node in Host mode."""
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))
        self.socket.listen()
        print(f"[*] Host is listening on {self.host}:{self.port}...")
        print(f"Your IP Address: {socket.gethostbyname(socket.gethostname())}")

        # Start a thread to handle accepting new connections
        accept_thread = threading.Thread(target=self._accept_connections_handler)
        accept_thread.daemon = True
        accept_thread.start()

        # Use the main thread to handle the host's input and sending messages
        self._host_send_handler()

        # After the send handler loop breaks (host typed 'exit'), shut down.
        print("\n[*] Shutting down the host.")
        for conn, addr in self.clients:
            conn.close()
        self.socket.close()

    # --- CLIENT FUNCTIONALITY ---

    def _receive_handler(self):
        """Handles receiving messages from the host."""
        while True:
            try:
                data = self.connection.recv(BUFFER_SIZE)
                if not data:
                    print("\n[!] Connection to host lost.")
                    break
                print(f"\r{data.decode('utf-8')}\nYou> ", end="")
            except (ConnectionResetError, ConnectionAbortedError):
                print("\n[!] Connection to host was closed.")
                break
            except Exception as e:
                print(f"\n[!] An error occurred: {e}")
                break
        
        self.connection.close()
        os._exit(0)

    def _send_handler(self):
        """Handles sending messages from user input to the host."""
        print("--- Connected to Host ---")
        print("Type 'exit' to disconnect.")
        while True:
            message = input("You> ")
            if message.lower() == 'exit':
                break
            self.connection.sendall(message.encode('utf-8'))
        
        self.connection.close()

    def connect_to_host(self, host_ip, host_port):
        """Starts the node in Client mode and connects to a host."""
        try:
            print(f"[*] Connecting to host {host_ip}:{host_port}...")
            self.socket.connect((host_ip, host_port))
            self.connection = self.socket
            
            # Start a thread for receiving messages from the host
            receiver = threading.Thread(target=self._receive_handler, daemon=True)
            receiver.start()
            
            # Use the main thread for sending messages
            self._send_handler()

        except ConnectionRefusedError:
            print("[!] Connection failed. Is the host running?")
        except Exception as e:
            print(f"[!] An error occurred: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="P2P Host-Client Chat Application")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--host", action="store_true", help="Run as the central host")
    group.add_argument("-c", "--connect", type=str, help="IP address of the host to connect to")
    
    args = parser.parse_args()

    node = P2PNode(HOST, PORT)

    if args.host:
        node.start_host()
    elif args.connect:
        node.connect_to_host(args.connect, PORT)
