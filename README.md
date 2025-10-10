# Cool P2P Chat & File Sharer 🚀

Yo! 👋 So this is a fun little command-line app for P2P chatting and
file sharing. You can spin up a private chat room with your friends and
just send messages, files, or even whole folders back and forth. All you
need is Python, no extra junk.

## How it Works (The Simple Version) 🤔

It\'s pretty simple, tbh. One person is the \"Host\" and everyone else
just connects to them.

- **👑 The Host:** The Host is basically the boss of the chat room. They
  > start it up, and everyone connects to their computer. The host is
  > like the bouncer---they gotta give the thumbs up for anyone to join.
  > They can chat and stuff, too.

- **🧍 The Client:** Clients are everyone else who joins the party. You
  > just need the host\'s IP address to connect and you\'re in! You can
  > chat, send files, whatever.

The best part? You only have to get permission once. After the host lets
you in, you can share stuff freely without them having to approve every
single file. No annoying popups, lol. 👍

## What it Can Do ✨

- **Group Chat:** Chat with all your buddies at once.

- **Usernames:** Pick a nickname so people actually know who\'s talking.

- **Host Approval:** The host decides who gets in. No randoms.

- **Real-Time Chat:** The chat is live, so no laggy messages.

- **Send Files:** Send pretty much any single file you want.

- **Send Folders:** Or just yeet a whole folder over. The app keeps all
  > the files inside organized for the person receiving it. Pog.

- **Progress Bar:** You even get a cool little progress bar when you\'re
  > sending big stuff so you know it\'s not stuck.

- **Works Anywhere:** As long as you have Python, it\'ll run. Windows,
  > Mac, Linux, whatever. 💻

## What You Need ✅

- Python 3.6 (or newer)

- That\'s literally it. No need to install anything else.

## How to Get it Goin\' 👉

1.  Get the script:  
    > First, just save the code as p2p_host_client_app.py.

2.  Be the Host:  
    > Someone\'s gotta be the host. If that\'s gonna be you, open your
    > terminal, go to where you saved the file, and run this:  
    > python p2p_host_client_app.py \--host  
    >   
    > It\'ll show you your IP address. You\'ll need to give that to your
    > friends.

3.  Join as a Client:  
    > For everyone else, you\'re a client. Run this command, but make
    > sure to swap in the host\'s real IP address.  
    > python p2p_host_client_app.py \--connect HOST_IP_ADDRESS  
    >   
    > Then it\'ll ask you to pick a username.

4.  Host, Let \'Em In!  
    > Heads up, host! Your terminal will ask if you wanna let the person
    > in. Just type y and hit Enter.

5.  Go Wild!  
    > And you\'re in! Go nuts. Chat, send files, have fun. 🎉

## Commands ⌨️

- **To Chat:** Just type stuff and press Enter. Duh. 💬

- **To Send a File:**  
  > You\> send \"path/to/your/file.txt\"

- **To Send a Folder:**  
  > You\> send \"path/to/your/folder\"

- **To Leave:**  
  > You\> exit  
  >   
  > Tired of us? Just type exit to bounce. 🚪

**Btw:** any files or folders you get will be chucked into a downloads
folder right where the script is. Easy peasy. 😉
