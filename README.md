# TikTok Comment Remover

Aid against spammers and scammers on your TikTok videos. It scans the comments on one of your posts, flags bot replies, shows you the list, and deletes them only after you confirm.

## What it flags

- **Duplicate replies:** the same account posts the same reply under two or more different comments.
- **Excessive replies:** an account replies under more than three different comments. Every comment from that account is flagged.

Your own account is never flagged.

## Requirements

- [Python 3.11](https://www.python.org/downloads/)
- [Cookie-Editor extension](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm?hl=en) for Chrome

## Setup Guide

1. Install the Cookie-Editor extension from the Chrome Web Store.

   ![Cookie-Editor in the Chrome Web Store](media/cookie-editor.jpg)

2. Open [www.tiktok.com](https://www.tiktok.com) and log in. Click the Cookie-Editor extension and, when it asks for permission, choose **This site**.

   ![Cookie-Editor permission request](media/cookie-editor-permissions.jpg)

3. Open the extension again, click **Export** and choose **JSON**. This copies your cookies to the clipboard.

   ![Cookie-Editor export button](media/cookie-editor-export.jpg)

4. Paste the clipboard into a new text file and save it as `cookies.txt` in this folder. You can also save it anywhere else: when a script cannot find `cookies.txt`, it asks you to drag the file into the terminal and saves a copy for you.

5. Install the dependency:

   ```
   pip install -r requirements.txt
   ```

6. Check that your login works:

   ```
   python check_login.py
   ```

   You should see `login is valid` followed by your handle.

## Usage

Review what would be deleted. Nothing is deleted in this step:

```
python delete_comments.py <link to your post>
```

Delete the comments from that list:

```
python delete_comments.py <link to your post> --confirm
```

The link can be a full video link, a photo post link or a short share link.

| Option | Effect |
| --- | --- |
| `--confirm` | Really delete. Without it the script only lists. |
| `--limit 10` | Delete at most 10 comments in this run. |
| `--refresh` | Ignore the saved comments and fetch them again. |
| `--cookies <file>` | Use a cookie file other than `cookies.txt`. |

To only download the comments and replies of any public post:

```
python fetch_comments.py <link to a post>
```

## How a run works

1. The comments and replies are fetched without your login and saved to `data/`.
2. The saved comments are scanned and the flagged ones are listed.
3. With `--confirm`, the flagged comments are deleted one by one, 3 to 8 seconds apart. The script stops at the first failure.
4. A run that stops partway continues where it left off next time. When everything flagged is deleted, the saved comments move to `data/done/` and the next run fetches fresh ones.

Every action is also written to `logs/tiktok.jsonl`, including the author and full text of each deleted comment.

## Good to know

- **Deleted comments cannot be restored.** Read the list before you use `--confirm`, and start with `--limit 3`.
- **It only works on your own posts.** TikTok does not let anyone else delete comments there, and the script refuses other people's posts.
- **`cookies.txt` is your login.** Anyone who has it can use your account. Do not share it. It is excluded from git by `.gitignore`.
- **Cookies expire.** When `check_login.py` says the login is not valid, export them again.
- **A short genuine reply can be flagged**, for example a fan replying "lol" under two comments. This is why the list is shown first.
- **This uses TikTok's website, not an official API.** Automated access is against TikTok's terms of service, and TikTok may show a captcha or restrict an account. The scripts pace their requests and stop when they are blocked. Use it at your own risk.
