# p2p_gui_app.py
# A GUI-based P2P application for chat and file sharing using tkinter.
# This version uses the sv-ttk library for a modern look and feel.
# To install the theme library, run: pip install sv-ttk

import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import socket
import threading
import sys
import os
import queue

# --- Constants ---
HOST = '0.0.0.0'
PORT = 65432
BUFFER_SIZE = 4096
DOWNLOADS_DIR = "downloads"

# --- Backend P2P Logic ---
# (Slightly modified to communicate with the GUI via queues)
class P2PNode:
    def __init__(self, gui_queue):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.clients = []
        self.connection = None
        self.gui_queue = gui_queue
        self.is_running = True
        self.download_root = None

    def _post_gui_update(self, msg_type, data):
        """Safely posts messages to the GUI's queue."""
        self.gui_queue.put({"type": msg_type, "data": data})

    def _broadcast(self, message, sender_conn):
        for client_conn, _, _ in list(self.clients):
            if client_conn != sender_conn:
                try:
                    client_conn.sendall(message)
                except socket.error:
                    client_to_remove = next((c for c in self.clients if c[0] == client_conn), None)
                    if client_to_remove:
                        self._remove_client(*client_to_remove)

    def _remove_client(self, conn, addr, username):
        client_tuple = (conn, addr, username)
        if client_tuple in self.clients:
            self.clients.remove(client_tuple)
            disconnect_msg = f"--- {username} has left the chat ---\n"
            self._post_gui_update("log", disconnect_msg.strip())
            self._broadcast(disconnect_msg.encode('utf-8'), conn)
            conn.close()

    def _client_handler(self, conn, addr, username):
        welcome_msg = f"--- {username} has joined the chat ---\n".encode('utf-8')
        self._broadcast(welcome_msg, conn)

        buffer = b""
        while self.is_running:
            try:
                data = conn.recv(BUFFER_SIZE)
                if not data: break
                buffer += data
                
                while b'\n' in buffer:
                    message_line, _, buffer = buffer.partition(b'\n')
                    try:
                        decoded_line = message_line.decode('utf-8')
                        if decoded_line.startswith('FILE_HEADER::'):
                            _, rel_path, f_size_str = decoded_line.split('::')
                            f_size = int(f_size_str)
                            
                            while len(buffer) < f_size:
                                chunk = conn.recv(BUFFER_SIZE)
                                if not chunk: break
                                buffer += chunk
                            
                            file_data = buffer[:f_size]
                            buffer = buffer[f_size:]
                            
                            relay_header = f"FILE_HEADER::{username}::{rel_path}::{f_size}\n".encode('utf-8')
                            self._post_gui_update("log", f"Relaying file '{rel_path}' from {username}.")
                            self._broadcast(relay_header, conn)
                            self._broadcast(file_data, conn)

                        elif decoded_line.startswith(('FOLDER_HEADER::', 'FOLDER_END::')):
                            msg_type, name = decoded_line.split('::')
                            relay_msg = f"{msg_type}::{username}::{name}\n".encode('utf-8')
                            self._post_gui_update("log", f"Relaying folder '{name}' from {username}.")
                            self._broadcast(relay_msg, conn)
                        else:
                            self._post_gui_update("chat", f"[{username}]: {decoded_line}")
                            self._broadcast(f"[{username}]: {decoded_line}\n".encode('utf-8'), conn)
                    except UnicodeDecodeError:
                        continue
            except (ConnectionResetError, ConnectionAbortedError):
                break
        self._remove_client(conn, addr, username)

    def _accept_connections_handler(self):
        while self.is_running:
            try:
                conn, addr = self.socket.accept()
                self._post_gui_update("connection_request", (conn, addr))
            except OSError:
                break

    def start_host(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((HOST, PORT))
        self.socket.listen()
        self.is_running = True
        accept_thread = threading.Thread(target=self._accept_connections_handler, daemon=True)
        accept_thread.start()
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except socket.gaierror:
            ip = "127.0.0.1" # Fallback
        self._post_gui_update("log", f"Host is listening on {ip}:{PORT}...")
        self._post_gui_update("host_started", ip)

    def connect_to_host(self, host_ip, username):
        try:
            self.socket.connect((host_ip, PORT))
            self.connection = self.socket
            self.connection.sendall(username.encode('utf-8'))
            response = self.connection.recv(BUFFER_SIZE)
            if response == b'CONNECT_ACCEPT':
                self.is_running = True
                self._post_gui_update("connected", "Connected to host!")
                receiver = threading.Thread(target=self._receive_handler, daemon=True)
                receiver.start()
            else:
                self._post_gui_update("error", "Connection denied by host.")
                self.stop()
        except Exception as e:
            self._post_gui_update("error", f"Connection failed: {e}")
            self.stop()

    def _receive_handler(self):
        buffer = b""
        receiving_file_info = None
        while self.is_running:
            try:
                data = self.connection.recv(BUFFER_SIZE)
                if not data:
                    self._post_gui_update("log", "Connection to host lost.")
                    break
                buffer += data
                
                while True:
                    if receiving_file_info:
                        filesize, save_path = receiving_file_info
                        if len(buffer) < filesize: break
                        
                        with open(save_path, 'wb') as f:
                            f.write(buffer[:filesize])
                        buffer = buffer[filesize:]
                        self._post_gui_update("log", f"Successfully downloaded '{os.path.basename(save_path)}'.")
                        receiving_file_info = None
                        continue

                    if b'\n' not in buffer: break
                    
                    message, _, buffer = buffer.partition(b'\n')
                    try:
                        decoded = message.decode('utf-8')
                        if decoded.startswith('FOLDER_HEADER::'):
                            _, sender, name = decoded.split('::')
                            self._post_gui_update("log", f"Receiving folder '{name}' from {sender}.")
                            self.download_root = os.path.join(DOWNLOADS_DIR, os.path.basename(name))
                            os.makedirs(self.download_root, exist_ok=True)
                        elif decoded.startswith('FOLDER_END::'):
                            _, sender, name = decoded.split('::')
                            self._post_gui_update("log", f"Successfully downloaded folder '{name}' from {sender}.")
                            self.download_root = None
                        elif decoded.startswith('FILE_HEADER::'):
                            _, sender, rel_path, size_str = decoded.split('::')
                            filesize = int(size_str)
                            self._post_gui_update("log", f"Receiving file '{rel_path}' from {sender}.")
                            
                            save_dir = self.download_root or DOWNLOADS_DIR
                            os.makedirs(save_dir, exist_ok=True)
                            save_path = os.path.join(save_dir, os.path.basename(rel_path))
                            receiving_file_info = (filesize, save_path)
                        else:
                            self._post_gui_update("chat", decoded)
                    except UnicodeDecodeError:
                        continue
            except (ConnectionResetError, ConnectionAbortedError):
                self._post_gui_update("log", "Connection to host was closed.")
                break
        self.stop()
    
    def send_message(self, message):
        if self.connection: # Client
            self.connection.sendall(f"{message}\n".encode('utf-8'))
        else: # Host
            self._post_gui_update("chat", f"[HOST]: {message}")
            self._broadcast(f"[HOST]: {message}\n".encode('utf-8'), None)

    def send_file_or_folder(self, path):
        # This is a simplified send function. Progress bar needs more work in GUI.
        is_host = not self.connection
        
        if is_host and not self.clients:
            self._post_gui_update("error", "No clients connected to send files to.")
            return

        if os.path.isdir(path):
            folder_name = os.path.basename(path)
            self._post_gui_update("log", f"Sending folder '{folder_name}'...")
            header = f"FOLDER_HEADER::{folder_name}\n".encode('utf-8')
            if is_host: self._broadcast(f"FOLDER_HEADER::HOST::{folder_name}\n".encode('utf-8'), None)
            else: self.connection.sendall(header)
            
            for root, _, files in os.walk(path):
                for filename in files:
                    full_path = os.path.join(root, filename)
                    relative_path = os.path.relpath(full_path, path)
                    try:
                        with open(full_path, 'rb') as f:
                            content = f.read()
                        f_header = f"FILE_HEADER::{relative_path}::{len(content)}\n".encode('utf-8')
                        
                        if is_host:
                            host_f_header = f"FILE_HEADER::HOST::{relative_path}::{len(content)}\n".encode('utf-8')
                            self._broadcast(host_f_header, None)
                            self._broadcast(content, None)
                        else:
                            self.connection.sendall(f_header)
                            self.connection.sendall(content)
                    except Exception as e:
                        self._post_gui_update("error", f"Skipping {relative_path}: {e}")
            
            end_header = f"FOLDER_END::{folder_name}\n".encode('utf-8')
            if is_host: self._broadcast(f"FOLDER_END::HOST::{folder_name}\n".encode('utf-8'), None)
            else: self.connection.sendall(end_header)
            self._post_gui_update("log", f"Finished sending folder '{folder_name}'.")

        elif os.path.isfile(path):
            self._post_gui_update("log", f"Sending file '{os.path.basename(path)}'...")
            try:
                with open(path, 'rb') as f:
                    content = f.read()
                filename = os.path.basename(path)
                header = f"FILE_HEADER::{filename}::{len(content)}\n".encode('utf-8')

                if is_host:
                    host_header = f"FILE_HEADER::HOST::{filename}::{len(content)}\n".encode('utf-8')
                    self._broadcast(host_header, None)
                    self._broadcast(content, None)
                else:
                    self.connection.sendall(header)
                    self.connection.sendall(content)
                self._post_gui_update("log", f"Finished sending file '{filename}'.")
            except Exception as e:
                self._post_gui_update("error", f"Could not send file: {e}")
        else:
            self._post_gui_update("error", "Path not found.")
            
    def stop(self):
        self.is_running = False
        if self.connection:
            try: self.connection.close()
            except: pass
        for conn, _, _ in self.clients:
            try: conn.close()
            except: pass
        try: self.socket.close()
        except: pass
        self._post_gui_update("log", "Connections closed.")

# --- GUI Application ---
class P2PApp(tk.Tk):
    def __init__(self):
        super().__init__()
        
        # --- Theme and Styling ---
        try:
            import sv_ttk
            sv_ttk.set_theme("dark")
        except ImportError:
            print("sv-ttk library not found. Falling back to default theme.")
            print("Install it with: pip install sv-ttk")
        
        self.title("P2P Sharer")
        self.geometry("550x650")

        self.gui_queue = queue.Queue()
        self.p2p_node = P2PNode(self.gui_queue)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.current_frame = None
        self.show_start_frame()
        self.check_queue()

    def show_frame(self, frame_class, *args, **kwargs):
        if self.current_frame:
            self.current_frame.destroy()
        self.current_frame = frame_class(self, *args, **kwargs)
        self.current_frame.pack(fill="both", expand=True, padx=10, pady=10)

    def show_start_frame(self):
        self.show_frame(StartFrame)

    def show_chat_frame(self, mode):
        self.show_frame(ChatFrame, mode=mode)

    def check_queue(self):
        try:
            message = self.gui_queue.get_nowait()
            msg_type = message["type"]
            data = message["data"]

            if msg_type == "host_started":
                self.show_chat_frame("host")
                self.current_frame.log_message(f"Your IP Address: {data}")
            elif msg_type == "connected":
                self.show_chat_frame("client")
                self.current_frame.log_message(data)
            elif msg_type == "connection_request":
                conn, addr = data
                username = conn.recv(1024).decode('utf-8')
                if messagebox.askyesno("Connection Request", f"Accept connection from {username} ({addr[0]})?"):
                    conn.sendall(b'CONNECT_ACCEPT')
                    self.current_frame.log_message(f"Accepted connection from {username}.")
                    client_data = (conn, addr, username)
                    self.p2p_node.clients.append(client_data)
                    thread = threading.Thread(target=self.p2p_node._client_handler, args=client_data, daemon=True)
                    thread.start()
                else:
                    conn.sendall(b'CONNECT_DENY')
                    conn.close()
            elif hasattr(self, 'current_frame') and isinstance(self.current_frame, ChatFrame):
                if msg_type == "chat":
                    self.current_frame.add_chat_message(data)
                elif msg_type == "log":
                    self.current_frame.log_message(data)
                elif msg_type == "error":
                    messagebox.showerror("Error", data)
        except queue.Empty:
            pass
        self.after(100, self.check_queue)

    def on_closing(self):
        if messagebox.askokcancel("Quit", "Do you want to quit?"):
            self.p2p_node.stop()
            self.destroy()

class StartFrame(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        
        ttk.Label(self, text="P2P Sharer", font=("Segoe UI", 24, "bold")).pack(pady=(20, 10))
        ttk.Label(self, text="Create or join a secure session", font=("Segoe UI", 11)).pack(pady=(0, 20))
        
        # --- Host Section ---
        host_frame = ttk.LabelFrame(self, text="Become a Host", padding=(20, 10))
        host_frame.pack(pady=10, padx=20, fill="x")
        ttk.Button(host_frame, text="▶ Start Host Session", command=self.start_host, style="Accent.TButton").pack(pady=10, fill="x")
        
        # --- Client Section ---
        client_frame = ttk.LabelFrame(self, text="Connect to a Host", padding=(20, 10))
        client_frame.pack(pady=10, padx=20, fill="x")

        ttk.Label(client_frame, text="Host IP Address:").pack(anchor="w")
        self.ip_entry = ttk.Entry(client_frame, font=("Segoe UI", 10))
        self.ip_entry.pack(fill="x", pady=(5, 10))
        
        ttk.Label(client_frame, text="Your Username:").pack(anchor="w")
        self.user_entry = ttk.Entry(client_frame, font=("Segoe UI", 10))
        self.user_entry.pack(fill="x", pady=5)
        
        ttk.Button(client_frame, text="🔗 Connect", command=self.connect_to_host).pack(pady=(15, 10), fill="x")

    def start_host(self):
        threading.Thread(target=self.parent.p2p_node.start_host, daemon=True).start()

    def connect_to_host(self):
        ip = self.ip_entry.get()
        user = self.user_entry.get()
        if ip and user:
            threading.Thread(target=self.parent.p2p_node.connect_to_host, args=(ip, user), daemon=True).start()
        else:
            messagebox.showwarning("Input Error", "Please provide both the Host IP and your Username.")

class ChatFrame(tk.Frame):
    def __init__(self, parent, mode):
        super().__init__(parent)
        self.parent = parent
        self.mode = mode

        # --- Chat Display ---
        self.chat_display = scrolledtext.ScrolledText(self, state='disabled', wrap=tk.WORD, font=("Segoe UI", 10), relief="flat", borderwidth=2)
        self.chat_display.pack(padx=0, pady=(0, 10), fill="both", expand=True)
        # Tag for styling different message types
        self.chat_display.tag_config('log', foreground='gray')
        self.chat_display.tag_config('you', foreground='#409FFF')


        # --- Message Input ---
        input_frame = ttk.Frame(self)
        input_frame.pack(padx=0, pady=0, fill="x")

        self.msg_entry = ttk.Entry(input_frame, font=("Segoe UI", 11))
        self.msg_entry.pack(side="left", fill="x", expand=True, ipady=5)
        self.msg_entry.bind("<Return>", self.send_message)
        
        file_button = ttk.Button(input_frame, text="📎", command=self.send_file, width=4)
        file_button.pack(side="left", padx=(5, 0))
        
        send_button = ttk.Button(input_frame, text="➤", command=self.send_message, width=4, style="Accent.TButton")
        send_button.pack(side="right")

    def send_message(self, event=None):
        msg = self.msg_entry.get()
        if msg:
            self.parent.p2p_node.send_message(msg)
            if self.mode == "client":
                self.add_chat_message(f"[You]: {msg}", 'you')
            self.msg_entry.delete(0, 'end')

    def send_file(self):
        # askopenfilename allows selecting one file, askdirectory allows one folder
        # We can open one dialog and let user pick, or offer two buttons.
        # For simplicity, we'll try to get either.
        path = filedialog.askopenfilename()
        if not path: # If user cancelled file dialog, try directory dialog
             path = filedialog.askdirectory()

        if path:
            threading.Thread(target=self.parent.p2p_node.send_file_or_folder, args=(path,), daemon=True).start()

    def _insert_text(self, text, tags=None):
        self.chat_display.configure(state='normal')
        self.chat_display.insert('end', text + '\n', tags)
        self.chat_display.configure(state='disabled')
        self.chat_display.see('end')

    def add_chat_message(self, message, tag=None):
        self._insert_text(message, tag)

    def log_message(self, message):
        self._insert_text(f"--- {message} ---", 'log')

if __name__ == "__main__":
    app = P2PApp()
    app.mainloop()
