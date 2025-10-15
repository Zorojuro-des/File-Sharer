import sys
import os
import threading
import queue

# Ensure we can import the local backend copy
sys.path.append(os.path.dirname(__file__))

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QListWidget, QTextEdit,
    QFileDialog, QMessageBox, QSplitter
)

# Allow importing sibling 'p2p_backend.py' (copied from your original file)
try:
    from p2p_backend import P2PNode
except Exception as e:
    print("Failed to import backend P2PNode:", e)
    raise

# --- Theme (bright, cohesive palette) ---
APP_STYLES = """
/* Palette:
   - Primary: #00C2FF (bright cyan)
   - Accent:  #FF7A59 (coral)
   - BG:      #0E1226 (deep navy)
   - Surface: #11162E (navy-ink)
   - Text:    #F4F6FF (off-white)
*/
QWidget {
  background-color: #0E1226;
  color: #F4F6FF;
  font-family: "Segoe UI", Arial, sans-serif;
  font-size: 14px;
}
QGroupBox {
  border: 2px solid #00C2FF;
  border-radius: 12px;
  margin-top: 12px;
  padding: 12px;
}
QGroupBox::title {
  subcontrol-origin: margin;
  left: 10px;
  padding: 0 6px;
  color: #00E1FF;
  font-weight: 800;
  letter-spacing: 0.2px;
}
QPushButton {
  background-color: #00C2FF;
  color: #0E1226;
  border: none;
  padding: 10px 14px;
  border-radius: 10px;
  font-weight: 800;
}
QPushButton:hover {
  background-color: #31D2FF;
}
QPushButton#accent {
  background-color: #FF7A59;
  color: #0E1226;
}
QPushButton#accent:hover {
  background-color: #FF906F;
}
QPushButton#danger {
  background-color: #FF7A59;
  color: #ffffff;
}
QPushButton#danger:hover {
  background-color: #FF9477;
}
QLineEdit {
  background: #11162E;
  border: 1px solid #2C3B73;
  border-radius: 8px;
  padding: 10px 12px;
  color: #F4F6FF;
}
QTextEdit, QListWidget {
  background: #11162E;
  border: 1px solid #2C3B73;
  border-radius: 10px;
  padding: 10px;
}
QLabel#title {
  font-size: 22px;
  font-weight: 900;
}
"""

# --- Reusable chat view widget ---
class ChatView(QWidget):
    def __init__(self, parent, mode: str):
        super().__init__(parent)
        self.parent = parent  # MainWindow
        self.mode = mode  # "host" or "client"

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Header with session label + Stop/Disconnect
        header = QHBoxLayout()
        title = QLabel("Host Session" if mode == "host" else "Connected to Host")
        title.setObjectName("title")
        header.addWidget(title)

        header.addStretch(1)
        self.stop_btn = QPushButton("Stop Host" if mode == "host" else "Disconnect")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.clicked.connect(self.on_stop_clicked)
        header.addWidget(self.stop_btn)
        root.addLayout(header)

        # Chat area
        self.chat_box = QTextEdit()
        self.chat_box.setReadOnly(True)
        self.chat_box.setMinimumHeight(320)
        root.addWidget(self.chat_box, 1)

        # Input row
        input_row = QHBoxLayout()
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("Type a message and press Enter…")
        self.msg_input.returnPressed.connect(self.send_message)
        input_row.addWidget(self.msg_input, 1)

        self.file_btn = QPushButton("Send File")
        self.file_btn.setObjectName("accent")
        self.file_btn.clicked.connect(self.send_file)
        input_row.addWidget(self.file_btn)

        self.folder_btn = QPushButton("Send Folder")
        self.folder_btn.setObjectName("accent")
        self.folder_btn.clicked.connect(self.send_folder)
        input_row.addWidget(self.folder_btn)

        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.send_message)
        input_row.addWidget(self.send_btn)
        root.addLayout(input_row)

    def _append_html(self, html: str):
        self.chat_box.append(html)

    def append_log(self, text: str):
        self._append_html(f'<span style="color: rgba(160,166,200,0.35); font-style: italic;">--- {text} ---</span>')

    def append_chat(self, raw: str):
        text = raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if self.mode == "client" and text.startswith("[You]:"):
            msg = text[len("[You]:"):].strip()
            self._append_html(f'<span style="color:#00E1FF; font-weight:800;">[You]: {msg}</span>')
        elif self.mode == "host" and text.startswith("[HOST]:"):
            msg = text[len("[HOST]:"):].strip()
            self._append_html(f'<span style="color:#00E1FF; font-weight:800;">[HOST]: {msg}</span>')
        else:
            self._append_html(f'<span style="color:#F4F6FF;">{text}</span>')

    def send_message(self):
        msg = self.msg_input.text().strip()
        if not msg:
            return
        self.parent.p2p_node.send_message(msg)
        if self.mode == "client":
            self.append_chat(f"[You]: {msg}")
        self.msg_input.clear()

    def send_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select a file to send")
        if path:
            threading.Thread(
                target=self.parent.p2p_node.send_file_or_folder, args=(path,), daemon=True
            ).start()

    def send_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select a folder to send")
        if path:
            threading.Thread(
                target=self.parent.p2p_node.send_file_or_folder, args=(path,), daemon=True
            ).start()

    def on_stop_clicked(self):
        self.parent.stop_session()

# --- Start view widget: split Host/Connector panels ---
class StartView(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent  # MainWindow

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QLabel("P2P Sharer")
        header.setObjectName("title")
        header.setAlignment(Qt.AlignCenter)
        sub = QLabel("Host a session or connect to one.")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet("color:#A0A6C8;")
        root.addWidget(header)
        root.addWidget(sub)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)

        # Host panel (left)
        self.host_box = QGroupBox("Become a Host")
        left_col = QVBoxLayout(self.host_box)
        left_col.setSpacing(10)

        self.host_btn = QPushButton("Start Hosting")
        self.host_btn.clicked.connect(self.parent.start_host)
        left_col.addWidget(self.host_btn)

        self.ip_label = QLabel("IP: —")
        left_col.addWidget(self.ip_label)

        self.clients_list = QListWidget()
        self.clients_list.setMinimumHeight(140)
        self.clients_list.setToolTip("Connected clients (host view)")
        left_col.addWidget(self.clients_list, 1)

        # Connector panel (right)
        self.conn_box = QGroupBox("Connect to a Host")
        right_col = QVBoxLayout(self.conn_box)
        right_col.setSpacing(10)

        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("Host IP address")
        right_col.addWidget(self.ip_input)

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Your username")
        right_col.addWidget(self.user_input)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("accent")
        self.connect_btn.clicked.connect(self.parent.connect_to_host)
        right_col.addWidget(self.connect_btn)

        # Add to splitter
        splitter.addWidget(self.host_box)
        splitter.addWidget(self.conn_box)
        splitter.setSizes([1, 1])
        root.addWidget(splitter, 1)

        foot = QLabel("Once hosting or approved, the chat view appears with a Disconnect button.")
        foot.setStyleSheet("color:#A0A6C8;")
        foot.setWordWrap(True)
        root.addWidget(foot)

    # helpers for MainWindow to update host status
    def set_host_ip(self, ip: str):
        self.ip_label.setText(f"IP: {ip}")

    def add_client(self, name: str):
        self.clients_list.addItem(name)

# --- Main Window managing views & backend queue ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("P2P Sharer (PyQt)")
        self.resize(900, 680)

        self.gui_queue = queue.Queue()
        self.p2p_node = P2PNode(self.gui_queue)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_queue)
        self.timer.start(100)

        self.start_view = StartView(self)
        self.chat_view = None  # created on demand

        self.setCentralWidget(self.start_view)
        self.setStyleSheet(APP_STYLES)

    def switch_to_chat(self, mode: str):
        self.chat_view = ChatView(self, mode)
        self.setCentralWidget(self.chat_view)

    def switch_to_start(self):
        self.chat_view = None
        self.start_view = StartView(self)
        self.setCentralWidget(self.start_view)

    # --- Host/Client actions ---
    def start_host(self):
        threading.Thread(target=self.p2p_node.start_host, daemon=True).start()

    def connect_to_host(self):
        ip = self.start_view.ip_input.text().strip()
        user = self.start_view.user_input.text().strip()
        if not ip or not user:
            QMessageBox.warning(self, "Input Error", "Please provide both Host IP and Username.")
            return
        threading.Thread(target=self.p2p_node.connect_to_host, args=(ip, user), daemon=True).start()

    def stop_session(self):
        # Stop everything and reset back to the split view
        try:
            self.p2p_node.stop()
        except Exception:
            pass
        self.gui_queue = queue.Queue()
        self.p2p_node = P2PNode(self.gui_queue)
        self.switch_to_start()

    # --- Queue processing from backend ---
    def check_queue(self):
        try:
            message = self.gui_queue.get_nowait()
        except queue.Empty:
            return

        msg_type = message.get("type")
        data = message.get("data")

        if msg_type == "host_started":
            # Switch to host chat view; show IP
            self.switch_to_chat("host")
            if self.chat_view:
                self.chat_view.append_log(f"Your IP Address: {data}")
        elif msg_type == "connected":
            # Switch to client chat
            self.switch_to_chat("client")
            if self.chat_view:
                self.chat_view.append_log(str(data))
        elif msg_type == "connection_request":
            # Host only: approve/deny connector
            conn, addr = data
            try:
                username = conn.recv(1024).decode("utf-8")
            except Exception:
                username = "Unknown"

            accept = QMessageBox.question(
                self,
                "Connection Request",
                f"Accept connection from {username} ({addr[0]})?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            ) == QMessageBox.Yes

            if accept:
                try:
                    conn.sendall(b"CONNECT_ACCEPT")
                    if not self.chat_view:
                        self.switch_to_chat("host")
                    self.chat_view.append_log(f"Accepted connection from {username}.")
                    client_data = (conn, addr, username)
                    self.p2p_node.clients.append(client_data)
                    thread = threading.Thread(
                        target=self.p2p_node._client_handler, args=client_data, daemon=True
                    )
                    thread.start()
                    # Update start view client list if still present
                    if self.start_view:
                        self.start_view.add_client(username)
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to accept connection: {e}")
            else:
                try:
                    conn.sendall(b"CONNECT_DENY")
                finally:
                    conn.close()

        elif self.chat_view:
            if msg_type == "chat":
                self.chat_view.append_chat(str(data))
            elif msg_type == "log":
                self.chat_view.append_log(str(data))
            elif msg_type == "error":
                QMessageBox.critical(self, "Error", str(data))

    # --- Close handling ---
    def closeEvent(self, event):
        # Stop backend gracefully
        try:
            self.p2p_node.stop()
        except Exception:
            pass
        event.accept()

def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
