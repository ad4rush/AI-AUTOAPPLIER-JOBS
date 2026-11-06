import subprocess
import time
from typing import Optional

def send_whatsapp_message(target_name: str, message_text: str) -> bool:
    """
    Sends a message to a specific WhatsApp chat or group (e.g., 'IIS')
    using macOS native automation via AppleScript and clipboard integration.
    """
    try:
        # Load message into system clipboard to support emojis, formatting, and long text cleanly
        p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        p.communicate(message_text.encode("utf-8"))

        # AppleScript automation sequence
        applescript = f"""
        tell application "WhatsApp" to activate
        delay 0.8

        tell application "System Events"
            -- Focus search bar in WhatsApp
            keystroke "f" using {{command down}}
            delay 0.4

            -- Select all in search and type the group or contact name
            keystroke "a" using {{command down}}
            delay 0.2
            keystroke "{target_name}"
            delay 1.2

            -- Navigate down into search result and open the chat
            key code 125 -- Down arrow
            delay 0.4
            key code 36  -- Return to select chat
            delay 0.8

            -- Paste message into the input field
            keystroke "v" using {{command down}}
            delay 0.4

            -- Send message
            key code 36  -- Return to send
        end tell
        """

        res = subprocess.run(["osascript", "-e", applescript], capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            print(f"[+] WhatsApp message successfully dispatched to '{target_name}'.")
            return True
        else:
            print(f"[!] Error sending WhatsApp message: {res.stderr}")
            return False
    except Exception as e:
        print(f"[!] Unexpected error in WhatsApp notifier: {e}")
        return False

def notify_job_application(company: str, title: str, location: str, match_score: int, url: str, resume_path: Optional[str] = None):
    """Formats and sends a job application alert to the 'IIS' group on WhatsApp."""
    msg = (
        f"🚀 *Job Application Update*\n\n"
        f"• *Company:* {company}\n"
        f"• *Role:* {title}\n"
        f"• *Location:* {location}\n"
        f"• *Match Score:* {match_score}%\n"
        f"• *Link:* {url}\n"
    )
    if resume_path:
        msg += f"• *Tailored Resume:* `{resume_path}`\n"
    msg += f"• *Timestamp:* {time.strftime('%Y-%m-%d %H:%M:%S')}"
    return send_whatsapp_message("IIS", msg)
