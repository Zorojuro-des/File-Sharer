# p2p_gui_app.py
# A modern P2P application for secure chat and file sharing using PyQt6.
# Features: TLS/SSL Encryption, SHA-256 Integrity, and Anti-Bot Math Challenges.

import sys
import os
import socket
import threading
import ssl
import hashlib
import random
import time
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextBrowser, QFileDialog,
    QStackedWidget, QGroupBox, QMessageBox, QProgressBar, QInputDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QSize
from PyQt6.QtGui import QFont, QTextCursor

# --- Constants ---
PORT = 65432
BUFFER_SIZE = 4096
DOWNLOADS_DIR = "downloads"
CERT_FILE = "server.crt"
KEY_FILE = "server.key"

# --- Security Helpers ---

def generate_self_signed_cert():
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        return True
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, u"p2p-secure-node"),
        ])
        cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(
            key.public_key()
        ).serial_number(x509.random_serial_number()).not_valid_before(
            datetime.utcnow()
        ).not_valid_after(
            datetime.utcnow() + datetime.timedelta(days=365)
        ).sign(key, hashes.SHA256())

        with open(KEY_FILE, "wb") as f:
            f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
        with open(CERT_FILE, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        return True
    except Exception: return False

def get_file_hash(filepath):
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

# --- Network Worker ---

class P2PWorker(QObject):
    log_signal = pyqtSignal(str)
    chat_signal = pyqtSignal(str, str) # sender, message
    conn_request_signal = pyqtSignal(object, tuple, str) # conn, addr, user
    bot_challenge_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str) # 'host_started', 'connected', 'error'
    
    def __init__(self):
        super().__init__()
        self.socket = None
        self.clients = [] # list of (conn, addr, user)
        self.connection = None
        self.is_running = True
        self.download_root = None

    def start_host(self):
        if not generate_self_signed_cert():
            self.status_signal.emit("error|Security libs (cryptography) missing.")
            return

        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind(('0.0.0.0', PORT))
            self.socket.listen()
            
            self.ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            self.ssl_context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)
            
            ip = socket.gethostbyname(socket.gethostname())
            self.status_signal.emit(f"host_started|{ip}")
            self.log_signal.emit(f"Secure Server started at {ip}")
            
            threading.Thread(target=self._accept_loop, daemon=True).start()
        except Exception as e:
            self.status_signal.emit(f"error|{str(e)}")

    def _accept_loop(self):
        while self.is_running:
            try:
                plain_conn, addr = self.socket.accept()
                threading.Thread(target=self._handle_new_connection, args=(plain_conn, addr), daemon=True).start()
            except: break

    def _handle_new_connection(self, plain_conn, addr):
        try:
            conn = self.ssl_context.wrap_socket(plain_conn, server_side=True)
            # Anti-Bot
            n1, n2 = random.randint(1,10), random.randint(1,10)
            conn.sendall(f"BOT_CHALLENGE::{n1}+{n2}\n".encode('utf-8'))
            ans = conn.recv(1024).decode('utf-8').strip()
            
            if ans == str(n1 + n2):
                conn.sendall(b"BOT_SUCCESS\n")
                username = conn.recv(1024).decode('utf-8').strip()
                self.conn_request_signal.emit(conn, addr, username)
            else:
                conn.sendall(b"BOT_FAIL\n")
                conn.close()
        except: plain_conn.close()

    def connect_to_host(self, ip, username):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((ip, PORT))
            
            context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            
            self.connection = context.wrap_socket(self.socket, server_hostname=ip)
            
            # Solve Bot Challenge
            challenge_data = self.connection.recv(1024).decode('utf-8')
            if challenge_data.startswith("BOT_CHALLENGE::"):
                self.bot_challenge_signal.emit(challenge_data.split("::")[1].strip())
        except Exception as e:
            self.status_signal.emit(f"error|{str(e)}")

    def submit_bot_response(self, ans, username):
        try:
            self.connection.sendall(f"{ans}\n".encode('utf-8'))
            status = self.connection.recv(1024).decode('utf-8').strip()
            if status == "BOT_SUCCESS":
                self.connection.sendall(username.encode('utf-8'))
                approval = self.connection.recv(1024)
                if approval == b"CONNECT_ACCEPT":
                    self.status_signal.emit("connected|Session secure.")
                    threading.Thread(target=self._receiver_loop, daemon=True).start()
                else:
                    self.status_signal.emit("error|Host denied connection.")
            else:
                self.status_signal.emit("error|Bot check failed.")
        except Exception as e:
            self.status_signal.emit(f"error|{str(e)}")

    def _broadcast(self, msg_bytes, exclude_conn=None):
        for c, _, _ in list(self.clients):
            if c != exclude_conn:
                try: c.sendall(msg_bytes)
                except: self.clients = [item for item in self.clients if item[0] != c]

    def _receiver_loop(self):
        buffer = b""
        receiving_file = None
        while self.is_running:
            try:
                data = self.connection.recv(BUFFER_SIZE)
                if not data: break
                buffer += data
                
                while True:
                    if receiving_file:
                        size, path, expected_hash = receiving_file
                        if len(buffer) < size: break
                        file_bytes = buffer[:size]
                        buffer = buffer[size:]
                        os.makedirs(os.path.dirname(path), exist_ok=True)
                        with open(path, 'wb') as f: f.write(file_bytes)
                        
                        if get_file_hash(path) == expected_hash:
                            self.log_signal.emit(f"File verified: {os.path.basename(path)}")
                        else:
                            self.log_signal.emit(f"Security Alert: Hash mismatch for {os.path.basename(path)}")
                        receiving_file = None
                        continue

                    if b'\n' not in buffer: break
                    line, _, buffer = buffer.partition(b'\n')
                    try:
                        decoded = line.decode('utf-8')
                        if decoded.startswith('FILE_HEADER::'):
                            _, sender, r_path, sz, hsh = decoded.split('::')
                            save_dir = self.download_root or DOWNLOADS_DIR
                            receiving_file = (int(sz), os.path.join(save_dir, r_path), hsh)
                            self.log_signal.emit(f"Downloading {r_path}...")
                        elif decoded.startswith('FOLDER_HEADER::'):
                            _, sender, name = decoded.split('::')
                            self.download_root = os.path.join(DOWNLOADS_DIR, name)
                            os.makedirs(self.download_root, exist_ok=True)
                        elif decoded.startswith('FOLDER_END::'):
                            self.download_root = None
                        else:
                            self.chat_signal.emit("", decoded)
                    except: continue
            except: break

    def host_relay_loop(self, conn, addr, user):
        buffer = b""
        self._broadcast(f"--- {user} has joined ---\n".encode('utf-8'), conn)
        while self.is_running:
            try:
                data = conn.recv(BUFFER_SIZE)
                if not data: break
                buffer += data
                while b'\n' in buffer:
                    line, _, buffer = buffer.partition(b'\n')
                    decoded = line.decode('utf-8')
                    if decoded.startswith('FILE_HEADER::'):
                        parts = decoded.split('::')
                        if len(parts) == 4:
                            _, r_path, sz, hsh = parts
                            while len(buffer) < int(sz):
                                buffer += conn.recv(BUFFER_SIZE)
                            f_data = buffer[:int(sz)]
                            buffer = buffer[int(sz):]
                            header = f"FILE_HEADER::{user}::{r_path}::{sz}::{hsh}\n".encode('utf-8')
                            self._broadcast(header + f_data, conn)
                            self.log_signal.emit(f"Relayed {r_path} from {user}")
                    elif decoded.startswith(('FOLDER_HEADER::', 'FOLDER_END::')):
                        m_type, name = decoded.split('::')
                        self._broadcast(f"{m_type}::{user}::{name}\n".encode('utf-8'), conn)
                    else:
                        formatted = f"[{user}]: {decoded}"
                        self.chat_signal.emit("", formatted)
                        self._broadcast(f"{formatted}\n".encode('utf-8'), conn)
            except: break
        self.clients = [c for c in self.clients if c[0] != conn]
        self._broadcast(f"--- {user} has left ---\n".encode('utf-8'))

    def send_message(self, message):
        if self.connection: # Client mode
            try:
                self.connection.sendall(f"{message}\n".encode('utf-8'))
            except:
                self.log_signal.emit("Failed to send message to host.")
        else: # Host mode
            formatted = f"[HOST]: {message}"
            self.chat_signal.emit("HOST", formatted)
            self._broadcast(f"{formatted}\n".encode('utf-8'))

    def send_file_or_folder(self, path):
        is_host = (self.connection is None)
        if is_host and not self.clients:
            self.log_signal.emit("No clients connected to receive files.")
            return

        if os.path.isdir(path):
            folder_name = os.path.basename(os.path.normpath(path))
            self.log_signal.emit(f"Sending folder: {folder_name}")
            
            header_str = f"FOLDER_HEADER::{folder_name}\n" if not is_host else f"FOLDER_HEADER::HOST::{folder_name}\n"
            header = header_str.encode('utf-8')
            
            if is_host: self._broadcast(header)
            else: self.connection.sendall(header)

            for root, _, files in os.walk(path):
                for filename in files:
                    full_p = os.path.join(root, filename)
                    rel_p = os.path.relpath(full_p, path)
                    self._send_single_file(full_p, rel_p, is_host)
            
            end_str = f"FOLDER_END::{folder_name}\n" if not is_host else f"FOLDER_END::HOST::{folder_name}\n"
            end = end_str.encode('utf-8')
            if is_host: self._broadcast(end)
            else: self.connection.sendall(end)
            self.log_signal.emit(f"Folder {folder_name} sent.")
        else:
            self._send_single_file(path, os.path.basename(path), is_host)

    def _send_single_file(self, full_path, rel_path, is_host):
        try:
            f_hash = get_file_hash(full_path)
            f_size = os.path.getsize(full_path)
            
            if not is_host:
                header = f"FILE_HEADER::{rel_path}::{f_size}::{f_hash}\n".encode('utf-8')
            else:
                header = f"FILE_HEADER::HOST::{rel_path}::{f_size}::{f_hash}\n".encode('utf-8')
            
            with open(full_path, 'rb') as f:
                content = f.read()
            
            if is_host:
                self._broadcast(header + content)
            else:
                self.connection.sendall(header + content)
            self.log_signal.emit(f"Sent: {rel_path}")
        except Exception as e:
            self.log_signal.emit(f"Error sending {rel_path}: {str(e)}")

# --- GUI ---

STYLE_SHEET = """
QMainWindow { background-color: #1e1e1e; }
QWidget { color: #ffffff; font-family: 'Segoe UI'; }
QGroupBox { border: 2px solid #333; border-radius: 8px; margin-top: 10px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
QLineEdit { background-color: #2d2d2d; border: 1px solid #444; border-radius: 4px; padding: 5px; color: white; }
QPushButton { background-color: #3d3d3d; border-radius: 4px; padding: 8px 15px; font-weight: bold; min-width: 80px; }
QPushButton:hover { background-color: #4d4d4d; }
QPushButton#accent { background-color: #0078d4; }
QPushButton#accent:hover { background-color: #0086f0; }
QTextBrowser { background-color: #121212; border: 1px solid #333; border-radius: 4px; padding: 10px; }
"""

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Secure P2P Sharer")
        self.setMinimumSize(600, 700)
        self.setStyleSheet(STYLE_SHEET)
        
        self.worker = P2PWorker()
        self.worker.log_signal.connect(self.add_log)
        self.worker.chat_signal.connect(self.add_chat)
        self.worker.status_signal.connect(self.handle_status)
        self.worker.conn_request_signal.connect(self.handle_conn_request)
        self.worker.bot_challenge_signal.connect(self.handle_bot_challenge)
        
        self.init_ui()

    def init_ui(self):
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        
        # --- Start Screen ---
        start_widget = QWidget()
        start_layout = QVBoxLayout(start_widget)
        start_layout.setContentsMargins(50, 50, 50, 50)
        
        title = QLabel("Secure P2P Sharer")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        start_layout.addWidget(title)
        
        # Host Box
        h_box = QGroupBox("Host a Secure Session")
        h_lay = QVBoxLayout(h_box)
        btn_host = QPushButton("▶ Start Encrypted Host")
        btn_host.setObjectName("accent")
        btn_host.clicked.connect(self.worker.start_host)
        h_lay.addWidget(btn_host)
        start_layout.addWidget(h_box)
        
        # Client Box
        c_box = QGroupBox("Join a Session")
        c_lay = QVBoxLayout(c_box)
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("Host IP Address")
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Your Username")
        btn_join = QPushButton("🔗 Connect Securely")
        btn_join.clicked.connect(self.on_join_clicked)
        c_lay.addWidget(QLabel("Target IP:"))
        c_lay.addWidget(self.ip_input)
        c_lay.addWidget(QLabel("Username:"))
        c_lay.addWidget(self.user_input)
        c_lay.addWidget(btn_join)
        start_layout.addWidget(c_box)
        
        self.stack.addWidget(start_widget)
        
        # --- Chat Screen ---
        self.chat_widget = QWidget()
        chat_layout = QVBoxLayout(self.chat_widget)
        
        header = QHBoxLayout()
        self.status_label = QLabel("🔒 Encrypted Session")
        self.status_label.setStyleSheet("color: #00ff00; font-style: italic;")
        btn_exit = QPushButton("Exit")
        btn_exit.setFixedWidth(60)
        btn_exit.clicked.connect(self.close)
        header.addWidget(self.status_label)
        header.addStretch()
        header.addWidget(btn_exit)
        chat_layout.addLayout(header)
        
        self.chat_view = QTextBrowser()
        chat_layout.addWidget(self.chat_view)
        
        self.log_view = QTextBrowser()
        self.log_view.setMaximumHeight(100)
        self.log_view.setStyleSheet("background-color: #1a1a1a; font-size: 10px; color: #888;")
        chat_layout.addWidget(self.log_view)
        
        input_row = QHBoxLayout()
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("Type a message...")
        self.msg_input.returnPressed.connect(self.send_msg)
        btn_send = QPushButton("➤")
        btn_send.setObjectName("accent")
        btn_send.clicked.connect(self.send_msg)
        btn_file = QPushButton("📎")
        btn_file.setFixedWidth(40)
        btn_file.clicked.connect(self.send_file_dialog)
        
        input_row.addWidget(self.msg_input)
        input_row.addWidget(btn_file)
        input_row.addWidget(btn_send)
        chat_layout.addLayout(input_row)
        
        self.stack.addWidget(self.chat_widget)

    def on_join_clicked(self):
        ip, user = self.ip_input.text(), self.user_input.text()
        if ip and user:
            self.temp_username = user
            self.worker.connect_to_host(ip, user)
        else:
            QMessageBox.warning(self, "Error", "Fill in all fields.")

    def handle_status(self, data):
        code, val = data.split('|')
        if code == "host_started":
            self.mode = "host"
            self.stack.setCurrentIndex(1)
            self.add_log(f"Hosting on {val}")
        elif code == "connected":
            self.mode = "client"
            self.stack.setCurrentIndex(1)
        elif code == "error":
            QMessageBox.critical(self, "P2P Error", val)

    def handle_conn_request(self, conn, addr, user):
        if QMessageBox.question(self, "Request", f"Accept {user} ({addr[0]})?") == QMessageBox.StandardButton.Yes:
            conn.sendall(b"CONNECT_ACCEPT")
            self.worker.clients.append((conn, addr, user))
            threading.Thread(target=self.worker.host_relay_loop, args=(conn, addr, user), daemon=True).start()
            self.add_log(f"Authorized {user}")
        else:
            conn.sendall(b"CONNECT_DENY")
            conn.close()

    def handle_bot_challenge(self, question):
        ans, ok = QInputDialog.getText(self, "Bot Check", f"Security: Solve {question}")
        if ok and ans:
            self.worker.submit_bot_response(ans, self.temp_username)
        else:
            self.worker.socket.close()

    def add_chat(self, sender, msg):
        self.chat_view.append(f"{msg}")

    def add_log(self, msg):
        self.log_view.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def send_msg(self):
        txt = self.msg_input.text()
        if txt:
            self.worker.send_message(txt)
            if self.mode == "client": self.add_chat("You", f"[You]: {txt}")
            self.msg_input.clear()

    def send_file_dialog(self):
        # Offer choice
        msg_box = QMessageBox(self)
        msg_box.setText("What would you like to send?")
        f_btn = msg_box.addButton("File", QMessageBox.ButtonRole.ActionRole)
        d_btn = msg_box.addButton("Folder", QMessageBox.ButtonRole.ActionRole)
        msg_box.exec()
        
        path = ""
        if msg_box.clickedButton() == f_btn:
            path, _ = QFileDialog.getOpenFileName(self, "Select File")
        else:
            path = QFileDialog.getExistingDirectory(self, "Select Folder")
            
        if path:
            threading.Thread(target=self.worker.send_file_or_folder, args=(path,), daemon=True).start()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())