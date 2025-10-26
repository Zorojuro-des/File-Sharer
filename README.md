# Cool P2P Chat & File Sharer 🚀

Yo! 👋 This is a fun little app for **P2P chatting and file sharing**.  
You can spin up a private chat room with your friends and just send messages, files, or even whole folders back and forth — all peer-to-peer, no servers needed.  

All you need is Python — no extra junk. 😎

---

## 💡 Now You Can Use It in 3 Ways!

You get to choose how you want to roll:

1. **🖥️ CLI Mode (Classic)**  
   Run it straight from the terminal using:  
   ```bash
   python p2p_host_client_app.py --host
   ```  
   or connect to someone using:  
   ```bash
   python p2p_host_client_app.py --connect HOST_IP_ADDRESS
   ```

2. **🪟 GUI Mode (Easy & Split Interface)**  
   If you prefer a graphical interface, you can use:  
   ```bash
   python p2p_gui_split.py
   ```  
   This gives you an intuitive split-window UI for chatting and file sharing — perfect if you’re not into terminals.

3. **⚡ Executable Mode (Windows 11 Only for Now)**  
   You can just download and run the ready-to-use executable:  
   ```
   dist/P2PSharer.exe
   ```  
   No Python setup needed! Just open it and start sharing. (Currently only available for **Windows 11**.)

---

## How It Works (The Simple Version) 🤔

It’s pretty simple, tbh. One person acts as the **Host**, and everyone else connects to them.

- **👑 The Host:**  
  Starts the chat room and approves who joins. The host can also chat and share files.

- **🧍 The Client:**  
  Joins the host using their IP address. Once approved, clients can freely chat and exchange files.

After approval, you can share files or folders without any further prompts. No annoying confirmations every time. 👍

---

## What It Can Do ✨

- **Group Chat:** Chat live with everyone connected.  
- **Usernames:** Choose a nickname so people know who’s talking.  
- **Host Approval:** Host decides who gets in.  
- **Real-Time Messaging:** Instant communication.  
- **Send Files:** Share single files easily.  
- **Send Folders:** Transfer entire folders with structure preserved.  
- **Progress Bar:** See how fast your files are flying!  
- **Cross-Platform:** Works on Windows, Mac, and Linux (Python version).  

---

## What You Need ✅

- Python 3.6 or newer  
- Or use the pre-built `P2PSharer.exe` on Windows 11 — no Python required.

---

## How to Get it Goin’ 👉

### 🏠 Be the Host:
```bash
python p2p_host_client_app.py --host
```
You’ll see your IP address — share it with your friends so they can join.

### 👥 Join as a Client:
```bash
python p2p_host_client_app.py --connect HOST_IP_ADDRESS
```
Then choose your username when prompted.

### ✅ Host Approval:
The host will be asked whether to allow each new connection. Type `y` to let them in.

### 🎉 Chat Away:
Once approved, you can send messages, files, or folders freely.

---

## Commands ⌨️

- **To Chat:**  
  Just type and hit Enter.

- **To Send a File:**  
  ```
  You> send "path/to/your/file.txt"
  ```

- **To Send a Folder:**  
  ```
  You> send "path/to/your/folder"
  ```

- **To Leave the Chat:**  
  ```
  You> exit
  ```

All received files/folders are saved inside a `downloads` folder created next to the script or executable. 📂

---

## TL;DR 🧠
- Use the **CLI** if you love terminals.  
- Use the **GUI** if you like visuals.  
- Use the **.exe** if you just wanna double-click and go (Windows 11).  

Either way, enjoy private, fast, and secure P2P chatting and file sharing. 🚀  
