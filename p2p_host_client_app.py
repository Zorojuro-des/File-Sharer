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
            disconnect_msg = f"--- {username} has left the chat ---\n".encode('utf-8')
            self._broadcast(disconnect_msg, conn)
            conn.close()

    def _client_handler(self, conn, addr, username):
        """
        Each client gets a dedicated thread running this function.
        It handles receiving messages, files, and broadcasting them using a robust buffer.
        """
        welcome_msg = f"--- {username} has joined the chat ---\n".encode('utf-8')
        self._broadcast(welcome_msg, conn)

        buffer = b""
        while True:
            try:
                # This inner loop processes the buffer until it needs more data
                while True:
                    if b'\n' not in buffer:
                        break # Incomplete message, need to receive more data

                    message_line, _, buffer = buffer.partition(b'\n')
                    
                    try:
                        decoded_line = message_line.decode('utf-8')
                    except UnicodeDecodeError:
                        print(f"\r[!] Received corrupted message from {username}. Ignoring.\nHost> ", end="")
                        continue

                    if decoded_line.startswith('FILE_HEADER::'):
                        _, relative_path, filesize_str = decoded_line.split('::')
                        filesize = int(filesize_str)

                        if len(buffer) < filesize: # Check if the full file data is in the buffer
                            buffer = message_line + b'\n' + buffer # Prepend header back
                            break # Need more data for the file

                        file_data = buffer[:filesize]
                        buffer = buffer[filesize:]

                        relay_header = f"FILE_HEADER::{username}::{relative_path}::{filesize}\n".encode('utf-8')
                        # print(f"\r[*] Relaying file '{relative_path}' from {username}.\nHost> ", end="")
                        self._broadcast(relay_header, conn)
                        self._broadcast(file_data, conn)
                        # print(f"\r[*] Finished relaying '{relative_path}' from {username}.\nHost> ", end="")
                        continue

                    elif decoded_line.startswith('FOLDER_HEADER::') or decoded_line.startswith('FOLDER_END::'):
                        msg_type, name = decoded_line.split('::')
                        relay_msg = f"{msg_type}::{username}::{name}\n".encode('utf-8')
                        
                        # if msg_type == 'FOLDER_HEADER':
                        #     print(f"\r[*] Relaying folder '{name}' from {username}.\nHost> ", end="")

                        # else:
                        #     print(f"\r[*] Finished relaying folder '{name}' from {username}.\nHost> ", end="")
                        self._broadcast(relay_msg, conn)
                        continue

                    else: # It's a chat message
                        message_to_broadcast = f"[{username}] says: {decoded_line}\n".encode('utf-8')
                        print(f"\r[{username}] says: {decoded_line}\nHost> ", end="")
                        self._broadcast(message_to_broadcast, conn)
                        continue
                
                # If the inner loop broke, we need more data
                data = conn.recv(BUFFER_SIZE)
                if not data:
                    break # Connection closed by client
                buffer += data

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
                formatted_message = f"[HOST] says: {message}\n".encode('utf-8')
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

    def _print_progress_bar(self, iteration, total, prefix='', suffix='', decimals=1, length=50, fill='█'):
        """
        Call in a loop to create terminal progress bar.
        """
        percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total))) if total > 0 else "0.0"
        filled_length = int(length * iteration // total) if total > 0 else 0
        bar = fill * filled_length + '-' * (length - filled_length)
        sys.stdout.write(f'\r{prefix} |{bar}| {percent}% {suffix}')
        sys.stdout.flush()
        if iteration == total:
            sys.stdout.write('\n')
            sys.stdout.flush()

    def _receive_handler(self):
        """Handles receiving messages and files from the host using a stateful buffer."""
        buffer = b""
        receiving_file_info = None

        while True:
            try:
                # --- STATE 1: RECEIVING A FILE ---
                if receiving_file_info:
                    filesize, save_path = receiving_file_info
                    if len(buffer) < filesize:
                        # Need more data for the file, so we must receive.
                        data = self.connection.recv(BUFFER_SIZE)
                        if not data:
                            print("\n[!] Connection to host lost during file transfer.")
                            break
                        buffer += data
                        continue # Re-evaluate buffer

                    # We have enough data for the file now.
                    file_data = buffer[:filesize]
                    buffer = buffer[filesize:]
                    
                    with open(save_path, 'wb') as f:
                        f.write(file_data)
                    
                    print(f"\r[*] Successfully downloaded '{os.path.basename(save_path)}'.\nYou> ", end="")
                    receiving_file_info = None # Go back to message mode
                    # Continue to process any remaining data in the buffer
                
                # --- STATE 2: PROCESSING MESSAGES ---
                if b'\n' not in buffer:
                    # Incomplete message, get more data
                    data = self.connection.recv(BUFFER_SIZE)
                    if not data:
                        print("\n[!] Connection to host lost.")
                        break
                    buffer += data
                    continue # Re-evaluate buffer

                # We have at least one full message ending with '\n'
                message, _, buffer = buffer.partition(b'\n')
                
                try:
                    decoded_message = message.decode('utf-8')
                except UnicodeDecodeError:
                    print(f"\r[!] Received corrupted message. Ignoring.\nYou> ", end="")
                    continue
                
                if decoded_message.startswith('FOLDER_HEADER::'):
                    _, sender_username, folder_name = decoded_message.split('::')
                    print(f"\r[*] Receiving folder '{folder_name}' from {sender_username}.\nYou> ", end="")
                    self.download_root = os.path.join(DOWNLOADS_DIR, os.path.basename(folder_name))
                    os.makedirs(self.download_root, exist_ok=True)
                
                elif decoded_message.startswith('FOLDER_END::'):
                    _, sender_username, folder_name = decoded_message.split('::')
                    print(f"\r[*] Successfully downloaded folder '{folder_name}' from {sender_username}.\nYou> ", end="")
                    self.download_root = None

                elif decoded_message.startswith('FILE_HEADER::'):
                    _, sender_username, relative_path, filesize_str = decoded_message.split('::')
                    filesize = int(filesize_str)

                    print(f"\r[*] Receiving file '{relative_path}' from {sender_username} ({filesize} bytes).\nYou> ", end="")
                    
                    if self.download_root:
                        save_path = os.path.join(self.download_root, relative_path)
                    else:
                        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
                        save_path = os.path.join(DOWNLOADS_DIR, os.path.basename(relative_path))
                    
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    receiving_file_info = (filesize, save_path) # Enter file receiving mode
                
                else: # It's a chat message
                    print(f"\r{decoded_message}\nYou> ", end="")

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
                    folder_name = os.path.basename(os.path.normpath(path_to_send))

                    # --- Calculate total size and file count for progress bar ---
                    print("[*] Calculating folder size...")
                    total_files = 0
                    total_size = 0
                    for root, _, files in os.walk(path_to_send):
                        for filename in files:
                            try:
                                total_files += 1
                                total_size += os.path.getsize(os.path.join(root, filename))
                            except OSError:
                                continue # Skip files we can't access
                    print(f"[*] Total files: {total_files}, Total size: {total_size / (1024*1024):.2f} MB")

                    # --- Start sending ---
                    print(f"[*] Starting to send folder '{folder_name}'...")
                    self.connection.sendall(f"FOLDER_HEADER::{folder_name}\n".encode('utf-8'))

                    sent_files = 0
                    sent_size = 0
                    self._print_progress_bar(0, total_size, prefix='Progress:', suffix='Complete', length=50)

                    for root, _, files in os.walk(path_to_send):
                        for filename in files:
                            full_path = os.path.join(root, filename)
                            relative_path = os.path.relpath(full_path, path_to_send)
                            
                            try:
                                with open(full_path, 'rb') as f:
                                    file_content = f.read()
                                
                                filesize = len(file_content)
                                self.connection.sendall(f"FILE_HEADER::{relative_path}::{filesize}\n".encode('utf-8'))
                                self.connection.sendall(file_content)
                                
                                sent_files += 1
                                sent_size += filesize
                                self._print_progress_bar(sent_size, total_size, prefix='Progress:', suffix=f'{sent_files}/{total_files} files', length=50)

                            except Exception as e:
                                print(f"\n[!] Could not read file '{relative_path}': {e}. Skipping.")
                                continue
                    
                    self.connection.sendall(f"FOLDER_END::{folder_name}\n".encode('utf-8'))
                    print(f"[*] Finished sending folder '{folder_name}'.")

                elif os.path.isfile(path_to_send):
                    try:
                        filesize = os.path.getsize(path_to_send)
                        filename = os.path.basename(path_to_send)
                        header = f"FILE_HEADER::{filename}::{filesize}\n".encode('utf-8')
                        
                        self.connection.sendall(header)

                        sent_size = 0
                        self._print_progress_bar(sent_size, filesize, prefix='Progress:', suffix='Complete', length=50)
                        with open(path_to_send, 'rb') as f:
                            while True:
                                chunk = f.read(BUFFER_SIZE)
                                if not chunk:
                                    break
                                self.connection.sendall(chunk)
                                sent_size += len(chunk)
                                self._print_progress_bar(sent_size, filesize, prefix='Progress:', suffix='Complete', length=50)
                        
                        print(f"\n[*] Finished sending '{filename}'.")
                    except Exception as e:
                        print(f"\n[!] Could not read or send file: {e}")
                else:
                    print(f"[!] Path not found: {path_to_send}")
            else:
                self.connection.sendall(f"{message}\n".encode('utf-8'))
        
        self.connection.close()

    def connect_to_host(self, host_ip, host_port, username):
        """Starts the node in Client mode and connects to a host."""
        try:
            print(f"[*] Connecting to host {host_ip}:{host_port} as {username}...")
            self.socket.connect((host_ip, host_port))
            self.connection = self.socket

            self.connection.sendall(username.encode('utf-8'))

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
        client_username = input("Enter your username: ")
        if not client_username:
            print("Username cannot be empty.")
            sys.exit(1)
        node.connect_to_host(args.connect, PORT, client_username)

