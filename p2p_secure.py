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
    QStackedWidget, QGroupBox, QMessageBox, QInputDialog, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QTextCursor

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
    chat_signal = pyqtSignal(str, str)
    conn_request_signal = pyqtSignal(object, tuple, str)
    bot_challenge_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.socket = None
        self.clients = []
        self.connection = None
        self.is_running = True
        self.download_root = None
        self.ssl_context = None

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
                            parts = decoded.split('::')
                            if len(parts) == 5:
                                _, sender, r_path, sz, hsh = parts
                                save_dir = self.download_root or DOWNLOADS_DIR
                                receiving_file = (int(sz), os.path.join(save_dir, r_path), hsh)
                                self.log_signal.emit(f"Downloading {r_path} from {sender}...")
                        elif decoded.startswith('FOLDER_HEADER::'):
                            _, sender, name = decoded.split('::')
                            self.download_root = os.path.join(DOWNLOADS_DIR, name)
                            os.makedirs(self.download_root, exist_ok=True)
                        elif decoded.startswith('FOLDER_END::'):
                            self.download_root = None
                        else:
                            self.chat_signal.emit("PEER", decoded)
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
                                chunk = conn.recv(BUFFER_SIZE)
                                if not chunk: break 
                                buffer += chunk
                            
                            if len(buffer) >= int(sz):
                                f_data = buffer[:int(sz)]
                                buffer = buffer[int(sz):]
                                header = f"FILE_HEADER::{user}::{r_path}::{sz}::{hsh}\n".encode('utf-8')
                                self._broadcast(header + f_data, conn)
                                
                                save_dir = self.download_root or DOWNLOADS_DIR
                                full_save_path = os.path.join(save_dir, r_path)
                                os.makedirs(os.path.dirname(full_save_path), exist_ok=True)
                                with open(full_save_path, 'wb') as f:
                                    f.write(f_data)
                                
                                self.log_signal.emit(f"Relayed and saved {r_path} from {user}")
                    elif decoded.startswith(('FOLDER_HEADER::', 'FOLDER_END::')):
                        m_type, name = decoded.split('::')
                        if m_type == 'FOLDER_HEADER':
                            self.download_root = os.path.join(DOWNLOADS_DIR, name)
                        elif m_type == 'FOLDER_END':
                            self.download_root = None
                        self._broadcast(f"{m_type}::{user}::{name}\n".encode('utf-8'), conn)
                    else:
                        formatted = f"[{user}]: {decoded}"
                        self.chat_signal.emit(user, formatted)
                        self._broadcast(f"{formatted}\n".encode('utf-8'), conn)
            except: break
        self.clients = [c for c in self.clients if c[0] != conn]
        self._broadcast(f"--- {user} has left ---\n".encode('utf-8'))

    def send_message(self, message):
        if self.connection:
            try:
                self.connection.sendall(f"{message}\n".encode('utf-8'))
            except:
                self.log_signal.emit("Failed to send message to host.")
        else:
            formatted = f"[HOST]: {message}"
            self.chat_signal.emit("YOU", formatted)
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

    def stop(self):
        self.is_running = False
        try:
            if self.socket:
                self.socket.close()
            if self.connection:
                self.connection.close()
            for c, _, _ in self.clients:
                c.close()
        except:
            pass

# --- Modern GUI Theme ---

STYLE_SHEET = """
* { margin: 0; padding: 0; }

QMainWindow {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0f172a, stop:1 #1a1f35);
}

QWidget {
    color: #e8eef5;
    font-family: 'Segoe UI', 'Helvetica Neue', sans-serif;
}

QLabel#MainTitle {
    font-size: 42px;
    font-weight: 800;
    color: #60a5fa;
    letter-spacing: -0.5px;
    margin-bottom: 8px;
}

QLabel#Subtitle {
    color: #9ca3af;
    font-size: 16px;
    font-weight: 500;
    margin-bottom: 40px;
    letter-spacing: 0.3px;
}

QGroupBox {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1e293b, stop:1 #0f172a);
    border: 1px solid #334155;
    border-radius: 16px;
    padding: 32px 28px;
    margin-top: 24px;
    color: #e8eef5;
    font-weight: 600;
    font-size: 13px;
    letter-spacing: 1.2px;
    text-transform: uppercase;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 20px;
    padding: 0 8px;
    color: #60a5fa;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.5px;
}

QLineEdit {
    background-color: #1a1f35;
    border: 1.5px solid #334155;
    border-radius: 10px;
    padding: 14px 16px;
    color: #e8eef5;
    font-size: 14px;
    font-weight: 500;
    margin: 8px 0;
}

QLineEdit:focus {
    border: 1.5px solid #60a5fa;
    background-color: #1e2a3f;
}

QLineEdit::placeholder { color: #64748b; }

QPushButton {
    background-color: #475569;
    border: none;
    border-radius: 10px;
    padding: 14px 24px;
    font-weight: 700;
    font-size: 14px;
    color: #f1f5f9;
    letter-spacing: 0.5px;
    margin: 8px 0;
}

QPushButton:hover { background-color: #64748b; }
QPushButton:pressed { background-color: #334155; }

QPushButton#PrimaryBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3b82f6, stop:1 #2563eb);
    font-weight: 800;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    min-height: 48px;
}

QPushButton#PrimaryBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #60a5fa, stop:1 #3b82f6);
}

QPushButton#SecondaryBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #10b981, stop:1 #059669);
}

QPushButton#SecondaryBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #34d399, stop:1 #10b981);
}

QPushButton#ExitBtn {
    background-color: #7f1d1d;
    color: #fee2e2;
    padding: 10px 16px;
    min-width: 0;
    font-size: 12px;
    font-weight: 700;
}

QPushButton#ExitBtn:hover { background-color: #991b1b; }

QPushButton#IconBtn {
    background-color: #334155;
    min-width: 48px;
    min-height: 48px;
    padding: 0;
    border-radius: 10px;
    font-size: 20px;
}

QPushButton#IconBtn:hover { background-color: #475569; }

QTextBrowser {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a1f35, stop:1 #151b28);
    border: 1.5px solid #334155;
    border-radius: 12px;
    padding: 16px;
    color: #e8eef5;
    font-size: 14px;
    line-height: 1.6;
    font-weight: 500;
}

#LogView {
    background: #0f172a;
    border: 1px solid #1e293b;
    color: #64748b;
    font-family: 'Courier New', monospace;
    font-size: 12px;
    font-weight: 400;
    max-height: 140px;
}

#StatusHeader {
    border-bottom: 2px solid #3b82f6;
    padding: 16px;
    border-radius: 8px;
    margin-bottom: 20px;
}

#StatusIcon {
    font-size: 22px;
    margin-right: 12px;
}

#StatusText {
    color: #60a5fa;
    font-weight: 800;
    letter-spacing: 1.2px;
    font-size: 13px;
}
"""

class ModernButton(QPushButton):
    def __init__(self, text, style_name="", parent=None):
        super().__init__(text, parent)
        if style_name:
            self.setObjectName(style_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Secure P2P Sharer")
        self.setMinimumSize(900, 800)
        self.setStyleSheet(STYLE_SHEET)
        self.mode = None
        self.temp_username = ""
        
        self.worker = None
        self.init_worker()
        self.init_ui()
        
        self.closeEvent = self.on_closing

    def init_worker(self):
        if self.worker:
            self.worker.stop()
        self.worker = P2PWorker()
        self.worker.log_signal.connect(self.add_log)
        self.worker.chat_signal.connect(self.add_chat)
        self.worker.status_signal.connect(self.handle_status)
        self.worker.conn_request_signal.connect(self.handle_conn_request)
        self.worker.bot_challenge_signal.connect(self.handle_bot_challenge)

    def init_ui(self):
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        
        start_widget = QWidget()
        start_layout = QVBoxLayout(start_widget)
        start_layout.setContentsMargins(60, 50, 60, 50)
        start_layout.setSpacing(0)
        
        title_label = QLabel("Secure P2P Sharer")
        title_label.setObjectName("MainTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        start_layout.addWidget(title_label)
        
        subtitle = QLabel("Encrypted file sharing & decentralized messaging")
        subtitle.setObjectName("Subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        start_layout.addWidget(subtitle)
        
        host_box = QGroupBox("CREATE ENCRYPTED SESSION")
        host_layout = QVBoxLayout(host_box)
        host_layout.setContentsMargins(20, 25, 20, 20)
        
        host_desc = QLabel("Start hosting secure sessions for peer connections")
        host_desc.setStyleSheet("color: #b0b7bf; font-size: 13px; font-weight: 500; margin-bottom: 16px;")
        
        btn_host = ModernButton("🛡️  START SECURE HOST", "PrimaryBtn")
        btn_host.setMinimumHeight(48)
        btn_host.clicked.connect(lambda: self.worker.start_host())
        
        host_layout.addWidget(host_desc)
        host_layout.addWidget(btn_host)
        start_layout.addWidget(host_box)
        
        join_box = QGroupBox("JOIN EXISTING SESSION")
        join_layout = QVBoxLayout(join_box)
        join_layout.setContentsMargins(20, 25, 20, 20)
        join_layout.setSpacing(12)
        
        join_desc = QLabel("Connect to an existing secure session")
        join_desc.setStyleSheet("color: #b0b7bf; font-size: 13px; font-weight: 500; margin-bottom: 8px;")
        
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("Enter Host IP Address")
        self.ip_input.setMinimumHeight(44)
        
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Choose Your Username")
        self.user_input.setMinimumHeight(44)
        
        btn_join = ModernButton("🔗  CONNECT SECURELY", "SecondaryBtn")
        btn_join.setMinimumHeight(48)
        btn_join.clicked.connect(self.on_join_clicked)
        
        join_layout.addWidget(join_desc)
        join_layout.addWidget(self.ip_input)
        join_layout.addWidget(self.user_input)
        join_layout.addWidget(btn_join)
        start_layout.addWidget(join_box)
        
        start_layout.addStretch()
        self.stack.addWidget(start_widget)
        
        self.chat_widget = QWidget()
        chat_layout = QVBoxLayout(self.chat_widget)
        chat_layout.setContentsMargins(24, 20, 24, 20)
        chat_layout.setSpacing(16)
        
        status_header = QFrame()
        status_header.setObjectName("StatusHeader")
        status_h_layout = QHBoxLayout(status_header)
        status_h_layout.setContentsMargins(16, 12, 16, 12)
        
        self.status_icon = QLabel("🔒")
        self.status_icon.setObjectName("StatusIcon")
        
        self.status_text = QLabel("SECURE SESSION ACTIVE")
        self.status_text.setObjectName("StatusText")
        
        btn_exit = ModernButton("LEAVE SESSION", "ExitBtn")
        btn_exit.clicked.connect(self.leave_session)
        
        status_h_layout.addWidget(self.status_icon)
        status_h_layout.addWidget(self.status_text)
        status_h_layout.addStretch()
        status_h_layout.addWidget(btn_exit)
        chat_layout.addWidget(status_header)
        
        self.chat_view = QTextBrowser()
        self.chat_view.setOpenExternalLinks(True)
        self.chat_view.setMinimumHeight(300)
        chat_layout.addWidget(self.chat_view, 1)
        
        log_label = QLabel("📋 Activity Log")
        log_label.setStyleSheet("color: #94a3b8; font-weight: 700; font-size: 12px; letter-spacing: 0.5px;")
        chat_layout.addWidget(log_label)
        
        self.log_view = QTextBrowser()
        self.log_view.setObjectName("LogView")
        self.log_view.setMaximumHeight(100)
        chat_layout.addWidget(self.log_view)
        
        input_label = QLabel("✉️ Send Message")
        input_label.setStyleSheet("color: #94a3b8; font-weight: 700; font-size: 12px; letter-spacing: 0.5px;")
        chat_layout.addWidget(input_label)
        
        input_container = QHBoxLayout()
        input_container.setSpacing(12)
        
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("Type your secure message here...")
        self.msg_input.setMinimumHeight(44)
        self.msg_input.returnPressed.connect(self.send_msg)
        
        btn_file = ModernButton("📎", "IconBtn")
        btn_file.setToolTip("Send File or Folder")
        btn_file.setFixedSize(48, 48)
        btn_file.clicked.connect(self.send_file_dialog)
        
        btn_send = ModernButton("SEND", "PrimaryBtn")
        btn_send.setFixedWidth(120)
        btn_send.setMinimumHeight(44)
        btn_send.clicked.connect(self.send_msg)
        
        input_container.addWidget(self.msg_input)
        input_container.addWidget(btn_file)
        input_container.addWidget(btn_send)
        chat_layout.addLayout(input_container)
        
        self.stack.addWidget(self.chat_widget)

    def on_join_clicked(self):
        ip, user = self.ip_input.text().strip(), self.user_input.text().strip()
        if ip and user:
            self.temp_username = user
            threading.Thread(target=self.worker.connect_to_host, args=(ip, user), daemon=True).start()
        else:
            QMessageBox.warning(self, "⚠️ Incomplete Fields", 
                              "Please provide both the Host IP and your Username to proceed.")

    def handle_status(self, data):
        code, val = data.split('|')
        if code == "host_started":
            self.mode = "host"
            self.stack.setCurrentIndex(1)
            self.add_log(f"✓ Secure session started on IP: {val}")
        elif code == "connected":
            self.mode = "client"
            self.stack.setCurrentIndex(1)
            self.add_log("✓ Connected to host. Session is encrypted and secure.")
        elif code == "error":
            QMessageBox.critical(self, "❌ Connection Error", val)

    def handle_conn_request(self, conn, addr, user):
        msg = f"<b>{user}</b> at <code>{addr[0]}</code> wants to join.<br><br>Accept connection?"
        reply = QMessageBox.question(self, "🔐 Verify Identity", msg, 
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            conn.sendall(b"CONNECT_ACCEPT")
            self.worker.clients.append((conn, addr, user))
            threading.Thread(target=self.worker.host_relay_loop, args=(conn, addr, user), daemon=True).start()
            self.add_log(f"✓ Access granted to {user}")
        else:
            conn.sendall(b"CONNECT_DENY")
            conn.close()
            self.add_log(f"✗ Connection from {user} denied")

    def handle_bot_challenge(self, question):
        ans, ok = QInputDialog.getText(self, "🤖 Security Verification", 
                                     f"Solve to establish encrypted link:<br><br><b style='font-size: 16px;'>{question}</b>")
        if ok and ans:
            self.worker.submit_bot_response(ans, self.temp_username)
        else:
            if self.worker.socket:
                self.worker.socket.close()

    def add_chat(self, sender_type, msg):
        time_str = datetime.now().strftime('%H:%M')
        
        if sender_type == "YOU":
            html = f"""
            <div style='margin-bottom: 12px; text-align: right;'>
                <div style='display: inline-block; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3b82f6, stop:1 #2563eb); 
                            padding: 12px 16px; border-radius: 16px 16px 4px 16px; color: #f1f5f9; 
                            max-width: 75%;'>
                    <div style='font-weight: 600; font-size: 11px; margin-bottom: 4px; color: #dbeafe; letter-spacing: 0.3px;'>
                        YOU • {time_str}
                    </div>
                    <div style='font-size: 14px; line-height: 1.4;'>{msg.replace("[You]: ", "")}</div>
                </div>
            </div>
            """
        elif sender_type == "HOST" or sender_type == "PEER":
            name = "HOST" if sender_type == "HOST" else msg.split("]:")[0].replace("[", "")
            content = msg.split("]:")[1] if "]:" in msg else msg
            
            html = f"""
            <div style='margin-bottom: 12px; text-align: left;'>
                <div style='display: inline-block; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #374151, stop:1 #1f2937); 
                            padding: 12px 16px; border-radius: 16px 16px 16px 4px; color: #f1f5f9; 
                            max-width: 75%;'>
                    <div style='font-weight: 600; font-size: 11px; margin-bottom: 4px; color: #d1d5db; letter-spacing: 0.3px;'>
                        {name} • {time_str}
                    </div>
                    <div style='font-size: 14px; line-height: 1.4;'>{content}</div>
                </div>
            </div>
            """
        else:
            html = f"<div style='text-align: center; color: #6b7280; font-size: 12px; margin: 16px 0; font-weight: 500;'>→ {msg}</div>"
            
        self.chat_view.append(html)
        self.chat_view.moveCursor(QTextCursor.MoveOperation.End)

    def add_log(self, msg):
        timestamp = datetime.now().strftime('%H:%M:%S')
        html = f"<span style='color: #475569;'>[{timestamp}]</span> <span style='color: #d1d5db;'>{msg}</span>"
        self.log_view.append(html)
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)

    def send_msg(self):
        txt = self.msg_input.text().strip()
        if txt:
            self.worker.send_message(txt)
            if self.mode == "client": 
                self.add_chat("YOU", f"[You]: {txt}")
            self.msg_input.clear()

    def send_file_dialog(self):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("📤 Share Asset")
        dialog.setText("What would you like to broadcast?")
        f_btn = dialog.addButton("📄 Send File", QMessageBox.ButtonRole.ActionRole)
        d_btn = dialog.addButton("📁 Send Folder", QMessageBox.ButtonRole.ActionRole)
        dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        
        path = ""
        if dialog.clickedButton() == f_btn:
            path, _ = QFileDialog.getOpenFileName(self, "Select File to Send")
        elif dialog.clickedButton() == d_btn:
            path = QFileDialog.getExistingDirectory(self, "Select Folder to Send")
            
        if path:
            threading.Thread(target=self.worker.send_file_or_folder, args=(path,), daemon=True).start()

    def leave_session(self):
        if QMessageBox.question(self, "Leave Session", "Are you sure you want to disconnect?",
                               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.init_worker()
            self.chat_view.clear()
            self.log_view.clear()
            self.msg_input.clear()
            self.ip_input.clear()
            self.user_input.clear()
            self.stack.setCurrentIndex(0)

    def on_closing(self, event):
        if self.worker:
            self.worker.stop()
        self.destroy()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())