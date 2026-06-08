# Setup Guide

This guide will get the automation running on your computer from scratch. Follow each step in order and you will be fine. If something looks different on your screen, just ask.

---

## What You Are Installing

- **Python** — the language the script is written in
- **Git** — lets you download the project from GitHub
- **VS Code** — the app you use to open and run the project
- **Box connection** — so the script can upload to Box on your behalf
- **Claude API key** — the AI that reads the PDFs

---

## Part 1 — Install Python

### Windows

1. Go to [python.org/downloads](https://python.org/downloads)
2. Click the big yellow **Download Python** button
3. Open the file that downloaded
4. On the very first screen, tick the box that says **Add Python to PATH** (this is important, do not skip it)
5. Click **Install Now**
6. When it finishes, click **Close**

### Mac

1. Go to [python.org/downloads](https://python.org/downloads)
2. Click the big yellow **Download Python** button
3. Open the `.pkg` file that downloaded
4. Click **Continue** on every screen, then click **Install**
5. Enter your Mac password if it asks
6. Click **Close** when done

---

## Part 2 — Install Git

### Windows

1. Go to [git-scm.com/download/win](https://git-scm.com/download/win)
2. The download starts automatically, open the file
3. Click **Next** on every screen without changing anything
4. Click **Install**, then **Finish**

### Mac

1. Open **Terminal** (press `Command + Space`, type `Terminal`, press Enter)
2. Type this and press Enter:
   ```
   git --version
   ```
3. If a window pops up asking you to install developer tools, click **Install** and wait for it to finish
4. If it just shows a version number, Git is already installed and you can move on

---

## Part 3 — Install VS Code

### Windows and Mac

1. Go to [code.visualstudio.com](https://code.visualstudio.com)
2. Click the big **Download** button (it detects your system automatically)
3. Open the file that downloaded and follow the installer
4. On Windows, tick the boxes that say **Add to PATH** and **Open with Code** if you see them
5. Open VS Code when the install finishes

---

## Part 4 — Open the Terminal in VS Code

You will be typing commands in the terminal throughout this guide. Here is how to open it.

1. Open VS Code
2. At the top, click **Terminal**
3. Click **New Terminal**
4. A panel opens at the bottom of the screen. That is where you type commands.

On **Windows** it looks like this:
```
PS C:\Users\YourName>
```

On **Mac** it looks like this:
```
YourName@MacName ~ %
```

---

## Part 5 — Clone the Project from GitHub

This downloads the project code files to your computer.

### Windows

1. Open **File Explorer** and go to where you want to save the project. The Desktop is fine.
2. Right click on an empty area in that folder
3. Click **Open Git Bash here** if you cant see it click more options.
4. A black window opens. Type this and press Enter:
   ```
   git clone https://github.com/Sterling-Trustees/Box-Automation.git
   ```
5. Wait for it to finish. You will see some lines appear and then stop.
6. A new folder called `Box-Automation` appears in the same location. 
7. Open VS Code, click **File**, then **Open Folder**, select Box Automation folder that you just cloned folder and click **Open**

### Mac

1. Open **Finder** and go to where you want to save the project. The Desktop is fine.
2. Right click on an empty area in that folder
3. Click **New Terminal at Folder** (if you do not see this option, open Terminal from Spotlight instead and skip to step 5)
4. A terminal window opens already in that folder
5. Type this and press Enter:
   ```
   git clone https://github.com/Sterling-Trustees/Box-Automation.git
   ```
6. Wait for it to finish
7. A new folder called `Box-Automation` appears in the same location
8. Open VS Code, click **File**, then **Open Folder**, select that folder and click **Open**

---

## Part 6 — Get Your Box App Credentials

The script needs permission to upload to Box. You get this from the Box Developer Console.

1. Go to [developer.box.com](https://developer.box.com) and sign in with your Sterling Trustees Box account
2. Click **My Apps** at the top
3. Click **Create New App**
4. Choose **Custom App**, then click **Next**
5. Choose **User Authentication (OAuth 2.0)**, then click **Next**
6. Give it any name (example: `Statement Uploader`), then click **Create App**
7. You are now on the app's configuration page. Scroll down to find:
   - **Client ID** (a long string of letters and numbers)
   - **Client Secret** (click **Fetch Client Secret** to reveal it)
8. Copy both of these. You will need them in the next step.
9. Scroll down to **OAuth 2.0 Redirect URI**
10. Click **Add** and type exactly: `http://localhost:8080/callback`
11. Click **Save Changes**

---

## Part 7 — Get Your Claude API Key

Go to Vault in ther folder Harshith(Intern) you will find Claude API keys (Confidential). 
---

## Part 8 — Create the .env File

This file stores all your credentials. The script reads it every time it runs.

1. In VS Code, look at the left panel (the file explorer)
2. Right click in an empty area and click **New File**
3. Name it exactly `.env` (with the dot at the start)
4. Click on the file to open it
5. Paste this in and fill in your values:

```
BOX_CLIENT_ID=paste_your_client_id_here
BOX_CLIENT_SECRET=paste_your_client_secret_here
ANTHROPIC_API_KEY=paste_your_claude_key_here
DOWNLOADS_FOLDER=C:\Users\YourName\Downloads
```

For **Mac**, the last line should be:
```
DOWNLOADS_FOLDER=/Users/YourName/Downloads
```

To find your exact username:

- **Windows:** Open the terminal and type `echo %USERNAME%`
- **Mac:** Open the terminal and type `whoami`

6. Save the file (press `Ctrl + S` on Windows or `Command + S` on Mac)

---

## Part 9 — Install the Required Packages

This installs everything the script depends on. You only do this once. open terminal in vs code

**Windows:**
```
pip install -r requirements.txt
```

**Mac:**
```
python3.14 -m pip install -r requirements.txt
```

Wait for it to finish. You will see a lot of text scrolling. That is normal.

---

## Part 10 — Connect Your Box Account

This links the script to your personal Box login. You only do this once (and again every 60 days when the connection expires). Run the command given.

**Windows:**
```
python setup_box_auth.py
```

**Mac:**
```
python3.14 setup_box_auth.py
```

1. Your browser opens and takes you to a Box login page
2. Sign in with your Sterling Trustees Box account
3. Click **Authorize**
4. The browser shows **Box authorised. You can close this tab.**
5. Go back to VS Code. The terminal should say the token was saved.

---

## Part 11 — Run the Script

This starts the automation. Leave it running in the background while you work.

**Windows:**
```
python main.py
```

**Mac:**
```
python3.14 main.py
```

When it is ready you will see something like:
```
Watching: C:\Users\YourName\Downloads
```

From this point on, any custodial financial statement PDF that lands in your Downloads folder will be automatically read, renamed and uploaded to the correct Box folder.

---

## Daily Use

Every day when you start work, just open VS Code, open the terminal, and run:

**Windows:**
```
python main.py
```

**Mac:**
```
python3.14 main.py
```

Leave it running. Do not close the terminal while you are working.

---



## Something Is Not Working

- **"Missing in .env"** means one of your credentials is wrong or missing. Open `.env` and check everything is filled in with no extra spaces.
- **"Box not authenticated"** means you need to run `setup_box_auth.py` again.
- **"No module named..."** means the packages are not installed. Run the `pip install` command from Part 9 again.
- **"Downloads folder not found"** means the path in `DOWNLOADS_FOLDER` is wrong. Check your username spelling.

If you see anything else, take a screenshot of the terminal and send it in teams or message me in the teams. Thank you.
