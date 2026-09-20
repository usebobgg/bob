# Bob

Bob is a free TikTok antibot: an aid against spammers and scammers on your videos. It scans the comments on one of your posts, flags bot replies, shows you the list, and deletes them only after you confirm. Bob runs on your own computer and opens in your browser.

## Table of Contents

- [What It Flags](#what-it-flags)
- [Requirements](#requirements)
- [Setup](#setup)
- [Using Bob](#using-bob)
- [Command Line](#command-line)
- [Good to Know](#good-to-know)

## What It Flags

- **Duplicate replies:** the same account posts the same reply under two or more different comments.
- **Excessive replies:** an account replies under more than three different comments. Every comment from that account is flagged.

Several replies under one comment count once, and your own account is never flagged. Both limits can be changed in Settings.

## Requirements

- [Python 3.11](https://www.python.org/downloads/) or newer
- [Cookie-Editor extension](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm?hl=en) for Chrome

## Setup

1. Download this folder: press **Code**, then **Download ZIP**, and unzip it.
2. Open the folder and double-click the start file:
   - Mac: `start.command`
   - Windows: `start.bat`
3. Your browser opens with Bob. Keep the start window open while you use it.

The start window explains each thing it does before doing it. It puts everything in a `.venv` folder inside this folder, downloads one library (`curl_cffi`) from pypi.org, and never installs Python without asking. To remove Bob, delete the folder.

On a Mac, the first time you may need to right-click `start.command` and choose **Open**.

## Using Bob

1. **Connect.** Bob shows how to copy your TikTok login with Cookie-Editor. Drag the file onto the dashed box, or press Ctrl V.

   ![Cookie-Editor in the Chrome Web Store](media/cookie-editor.jpg)

   ![Cookie-Editor permission request](media/cookie-editor-permissions.jpg)

   ![Cookie-Editor export button](media/cookie-editor-export.jpg)

2. **Scan.** Paste the link to one of your posts. Video links, photo links and short share links all work. Nothing is deleted here.
3. **Review.** Bot replies are tinted red. Press **Keep** on anything genuine, then press **Delete** and confirm.
4. **Done.** Open the post on TikTok and check that they are gone.

The sidebar also has **History** (what Bob deleted before), **Settings** (how strict Bob is and how fast it deletes) and **Show Log**.

## Command Line

The same tools work without the browser:

```
python check_login.py
python fetch_comments.py <link to a post>
python delete_comments.py <link to your post>
python delete_comments.py <link to your post> --confirm
```

`delete_comments.py` only lists what it would delete unless you add `--confirm`. `--limit 10` caps a run and `--refresh` fetches the comments again.

## Good to Know

- Deleted comments cannot be restored.
- It only works on your own posts.
- `cookies.txt` is your login. Never share it.
- When the login stops working, export your cookies again.
- Automated access is against TikTok's terms of service. Use it at your own risk.
