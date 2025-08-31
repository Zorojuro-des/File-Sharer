# p2p_host_client_app.py
# A threaded P2P application supporting a central host and multiple clients with usernames.

import socket
import threading
import argparse
import sys
import os
import queue

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
        # For the Host: a list to keep track of client data: (conn, addr, username)
        self.clients = []
        # A thread-safe queue for pending connection requests for the host
        self.pending_queue = queue.Queue()
        # For the Client: the connection to the host
        self.connection = None

    # --- HOST FUNCTIONALITY ---

    def _broadcast(self, message, sender_conn):
        """Sends a message to all connected clients except the sender."""
        # Use a copy of the list for safe iteration
        for client_conn, _, _ in list(self.clients):
            if client_conn != sender_conn:
                try:
                    client_conn.sendall(message)
                except socket.error:
                    # If sending fails, find the client and remove them
                    client_to_remove = next((c for c in self.clients if c[0] == client_conn), None)
                    if client_to_remove:
                        self._remove_client(*client_to_remove)

    def _remove_client(self, conn, addr, username):
        """Removes a client from the list of connections."""
        client_tuple = (conn, addr, username)
        if client_tuple in self.clients:
            self.clients.remove(client_tuple)
            # Use carriage return to not disrupt the host's input prompt
            print(f"\r[*] {username} ({addr[0]}) has disconnected.\nHost> ", end="")
            disconnect_msg = f"--- {username} has left the chat ---".encode('utf-8')
            self._broadcast(disconnect_msg, conn)
            conn.close()

    def _client_handler(self, conn, addr, username):
        """
        Each client gets a dedicated thread running this function.
        It handles receiving messages and broadcasting them.
        """
        # Announce the new user to the chat
        welcome_msg = f"--- {username} has joined the chat ---".encode('utf-8')
        self._broadcast(welcome_msg, conn)

        while True:
            try:
                data = conn.recv(BUFFER_SIZE)
                if not data:
                    break # Connection closed by client
                
                message_to_broadcast = f"[{username}] says: ".encode('utf-8') + data
                # Use carriage return to cleanly print message above the host's input prompt
                print(f"\r[{username}] says: {data.decode('utf-8')}\nHost> ", end="")
                self._broadcast(message_to_broadcast, conn)

            except (ConnectionResetError, ConnectionAbortedError):
                break # Client disconnected abruptly
        
        self._remove_client(conn, addr, username)

    def _accept_connections_handler(self):
        """Runs in a separate thread to continuously accept new client connections."""
        while True:
            try:
                conn, addr = self.socket.accept()
                self.pending_queue.put((conn, addr))
                print(f"\r[*] New connection request from {addr[0]}. Please respond below.\nHost> ", end="")
            except OSError:
                break
            except Exception as e:
                print(f"[!] Error accepting connections: {e}")
                break

    def _host_ui_handler(self):
        """
        Handles the host's main UI loop, processing pending connections
        and sending messages.
        """
        print("--- Host is running. Type messages to broadcast. Type 'exit' to shut down. ---")
        print(f"Your IP Address: {socket.gethostbyname(socket.gethostname())}")
        while True:
            # Handle pending connection requests first
            while not self.pending_queue.empty():
                conn, addr = self.pending_queue.get()
                
                try:
                    # The first message from a client should be their username
                    username = conn.recv(BUFFER_SIZE).decode('utf-8')
                    if not username:
                        print(f"[*] Client from {addr[0]} disconnected before sending name.")
                        conn.close()
                        continue

                    consent = input(f"Accept connection from {username} ({addr[0]})? (y/n): ")
                    if consent.lower().strip() == 'y':
                        conn.sendall(b'CONNECT_ACCEPT')
                        client_data = (conn, addr, username)
                        self.clients.append(client_data)
                        thread = threading.Thread(target=self._client_handler, args=client_data)
                        thread.daemon = True
                        thread.start()
                        print(f"[*] Connection from {username} accepted.")
                    else:
                        conn.sendall(b'CONNECT_DENY')
                        conn.close()
                        print(f"[*] Connection from {username} denied.")
                except Exception as e:
                    print(f"[!] Error during consent: {e}")
                    conn.close()

            message = input("Host> ")
            if message.lower() == 'exit':
                break
            
            if message:
                formatted_message = f"[HOST] says: {message}".encode('utf-8')
                self._broadcast(formatted_message, None)

    def start_host(self):
        """Starts the node in Host mode."""
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))
        self.socket.listen()
        print(f"[*] Host is listening on {self.host}:{self.port}...")

        accept_thread = threading.Thread(target=self._accept_connections_handler, daemon=True)
        accept_thread.start()

        self._host_ui_handler()

        print("\n[*] Shutting down the host.")
        for conn, _, _ in self.clients:
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

    def connect_to_host(self, host_ip, host_port, username):
        """Starts the node in Client mode and connects to a host."""
        try:
            print(f"[*] Connecting to host {host_ip}:{host_port} as {username}...")
            self.socket.connect((host_ip, host_port))
            self.connection = self.socket

            # Send username immediately after connecting
            self.connection.sendall(username.encode('utf-8'))

            # Wait for the host's approval
            response = self.connection.recv(BUFFER_SIZE)
            if response == b'CONNECT_ACCEPT':
                print("[*] Connection accepted by host!")
                receiver = threading.Thread(target=self._receive_handler, daemon=True)
                receiver.start()
                self._send_handler()
            else:
                print("[!] Connection denied by host.")

        except ConnectionRefusedError:
            print("[!] Connection failed. Is the host running?")
        except Exception as e:
            print(f"[!] An error occurred: {e}")
        finally:
            self.socket.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="P2P Host-Client Chat Application")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--host", action="store_true", help="Run as the central host")
    group.add_argument("-c", "--connect", type=str, metavar="HOST_IP", help="IP address of the host to connect to")
    
    args = parser.parse_args()

    node = P2PNode(HOST, PORT)

    if args.host:
        node.start_host()
    elif args.connect:
        # Prompt for username if running as a client
        client_username = input("Enter your username: ")
        if not client_username:
            print("Username cannot be empty.")
            sys.exit(1)
        node.connect_to_host(args.connect, PORT, client_username)

