# p2p_host_client_app.py
# A threaded P2P application supporting a central host and multiple clients with usernames.

import socket
import threading
import argparse
import sys
import os
import queue
import time

# --- Constants ---
HOST = '0.0.0.0'  # Listen on all available interfaces
PORT = 65432      # The port for our application
BUFFER_SIZE = 4096 # Use a larger buffer for file transfers
DOWNLOADS_DIR = "downloads" # Directory to save received files

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
        # For the Client: Tracks the root directory for an incoming folder download
        self.download_root = None

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
        It handles receiving messages, files, and broadcasting them.
        """
        # Announce the new user to the chat
        welcome_msg = f"--- {username} has joined the chat ---".encode('utf-8')
        self._broadcast(welcome_msg, conn)

        while True:
            try:
                data = conn.recv(BUFFER_SIZE)
                if not data:
                    break # Connection closed by client
                
                # Check for file header first, as it has a data payload to relay
                if data.startswith(b'FILE_HEADER::'):
                    header_parts = data.decode('utf-8').split('::')
                    _, relative_path, filesize_str = header_parts
                    filesize = int(filesize_str)

                    # Relay the header with the sender's username
                    relay_header = f"FILE_HEADER::{username}::{relative_path}::{filesize}".encode('utf-8')
                    print(f"\r[*] Relaying file '{relative_path}' from {username}.\nHost> ", end="")
                    self._broadcast(relay_header, conn)
                    
                    # Now, relay the file data
                    bytes_to_relay = filesize
                    while bytes_to_relay > 0:
                        chunk = conn.recv(min(BUFFER_SIZE, bytes_to_relay))
                        if not chunk:
                            break
                        self._broadcast(chunk, conn)
                        bytes_to_relay -= len(chunk)
                    print(f"\r[*] Finished relaying '{relative_path}' from {username}.\nHost> ", end="")

                elif data.startswith(b'FOLDER_HEADER::') or data.startswith(b'FOLDER_END::'):
                    # These are simple single-line messages to be relayed
                    decoded_data = data.decode('utf-8').split('::')
                    msg_type, name = decoded_data
                    relay_msg = f"{msg_type}::{username}::{name}".encode('utf-8')
                    
                    if msg_type == 'FOLDER_HEADER':
                        print(f"\r[*] Relaying folder '{name}' from {username}.\nHost> ", end="")
                    else:
                        print(f"\r[*] Finished relaying folder '{name}' from {username}.\nHost> ", end="")

                    self._broadcast(relay_msg, conn)
                
                else: # It's a chat message
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
        """Handles receiving messages and files from the host."""
        while True:
            try:
                data = self.connection.recv(BUFFER_SIZE)
                if not data:
                    print("\n[!] Connection to host lost.")
                    break
                
                # Check for folder/file headers first
                if data.startswith(b'FOLDER_HEADER::'):
                    header_parts = data.decode('utf-8').split('::')
                    _, sender_username, folder_name = header_parts
                    print(f"\r[*] Receiving folder '{folder_name}' from {sender_username}.\nYou> ", end="")
                    self.download_root = os.path.join(DOWNLOADS_DIR, os.path.basename(folder_name))
                    os.makedirs(self.download_root, exist_ok=True)
                
                elif data.startswith(b'FOLDER_END::'):
                    header_parts = data.decode('utf-8').split('::')
                    _, sender_username, folder_name = header_parts
                    print(f"\r[*] Successfully downloaded folder '{folder_name}' from {sender_username}.\nYou> ", end="")
                    self.download_root = None # Reset after folder transfer is complete

                elif data.startswith(b'FILE_HEADER::'):
                    header_parts = data.decode('utf-8').split('::')
                    _, sender_username, relative_path, filesize_str = header_parts
                    filesize = int(filesize_str)

                    print(f"\r[*] Receiving file '{relative_path}' from {sender_username} ({filesize} bytes).\nYou> ", end="")
                    
                    # Determine where to save the file
                    if self.download_root:
                        save_path = os.path.join(self.download_root, relative_path)
                    else:
                        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
                        save_path = os.path.join(DOWNLOADS_DIR, os.path.basename(relative_path))
                    
                    # Ensure the subdirectory for the file exists
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)

                    with open(save_path, 'wb') as f:
                        bytes_received = 0
                        while bytes_received < filesize:
                            chunk = self.connection.recv(min(BUFFER_SIZE, filesize - bytes_received))
                            if not chunk:
                                break
                            f.write(chunk)
                            bytes_received += len(chunk)
                    
                    print(f"\r[*] Successfully downloaded '{relative_path}'.\nYou> ", end="")

                else: # It's a chat message
                    print(f"\r{data.decode('utf-8')}\nYou> ", end="")

            except (ConnectionResetError, ConnectionAbortedError):
                print("\n[!] Connection to host was closed.")
                break
            except Exception as e:
                print(f"\n[!] An error occurred during receive: {e}")
                break
        
        self.connection.close()
        os._exit(0)

    def _send_handler(self):
        """Handles sending messages and files from user input to the host."""
        print("--- Connected to Host ---")
        print("Type 'exit' to disconnect.")
        print("To send a file or folder, type 'send <path>'")
        while True:
            message = input("You> ")
            if message.lower() == 'exit':
                break

            if message.lower().startswith('send '):
                path_to_send = message[5:].strip().strip("'\"")

                if os.path.isdir(path_to_send):
                    # --- FOLDER SENDING LOGIC ---
                    folder_name = os.path.basename(os.path.normpath(path_to_send))
                    print(f"[*] Starting to send folder '{folder_name}'...")
                    self.connection.sendall(f"FOLDER_HEADER::{folder_name}".encode('utf-8'))
                    time.sleep(0.1)

                    for root, _, files in os.walk(path_to_send):
                        for filename in files:
                            full_path = os.path.join(root, filename)
                            relative_path = os.path.relpath(full_path, path_to_send)
                            filesize = os.path.getsize(full_path)
                            
                            print(f"  Sending: {relative_path}")
                            self.connection.sendall(f"FILE_HEADER::{relative_path}::{filesize}".encode('utf-8'))
                            time.sleep(0.1)

                            with open(full_path, 'rb') as f:
                                while (chunk := f.read(BUFFER_SIZE)):
                                    self.connection.sendall(chunk)
                            time.sleep(0.1)

                    self.connection.sendall(f"FOLDER_END::{folder_name}".encode('utf-8'))
                    print(f"[*] Finished sending folder '{folder_name}'.")

                elif os.path.isfile(path_to_send):
                    # --- SINGLE FILE SENDING LOGIC ---
                    filesize = os.path.getsize(path_to_send)
                    filename = os.path.basename(path_to_send)
                    header = f"FILE_HEADER::{filename}::{filesize}".encode('utf-8')
                    
                    self.connection.sendall(header)
                    time.sleep(0.1)

                    with open(path_to_send, 'rb') as f:
                        while (chunk := f.read(BUFFER_SIZE)):
                            self.connection.sendall(chunk)
                    print(f"[*] Finished sending '{filename}'.")
                else:
                    print(f"[!] Path not found: {path_to_send}")
            else:
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

