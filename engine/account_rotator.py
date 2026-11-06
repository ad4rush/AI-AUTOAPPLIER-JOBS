import json
from pathlib import Path
from typing import Dict, Any, List

from engine.config import DATA_DIR, CLAUDE_ACCOUNTS, EGO_BROWSER_PROFILE_ID

ACCOUNT_STATE_FILE = DATA_DIR / "account_state.json"

def get_account_state() -> Dict[str, Any]:
    if ACCOUNT_STATE_FILE.exists():
        try:
            with open(ACCOUNT_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "current_index": 0,
        "accounts": CLAUDE_ACCOUNTS,
        "history": []
    }

def save_account_state(state: Dict[str, Any]):
    ACCOUNT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ACCOUNT_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def get_current_account() -> str:
    state = get_account_state()
    idx = state.get("current_index", 0) % len(CLAUDE_ACCOUNTS)
    return CLAUDE_ACCOUNTS[idx]

def rotate_to_next_account(reason: str = "rate_limit_exceeded") -> str:
    """Rotates to the next Google account in round-robin order."""
    state = get_account_state()
    curr_idx = state.get("current_index", 0)
    next_idx = (curr_idx + 1) % len(CLAUDE_ACCOUNTS)
    state["current_index"] = next_idx
    state.setdefault("history", []).append({
        "from": CLAUDE_ACCOUNTS[curr_idx],
        "to": CLAUDE_ACCOUNTS[next_idx],
        "reason": reason
    })
    save_account_state(state)
    print(f"[+] Account rotated: {CLAUDE_ACCOUNTS[curr_idx]} -> {CLAUDE_ACCOUNTS[next_idx]} (Reason: {reason})")
    return CLAUDE_ACCOUNTS[next_idx]

def generate_browser_switch_script(target_email: str) -> str:
    """Generates nodejs ego-browser script to switch Google account on Claude/ChatGPT."""
    return f"""
const spaces = await listTaskSpaces();
const existing = spaces.find(s => s.name === "job_applier_workload");
const task = existing ? await taskSpace(existing.id) : await taskSpace("job_applier_workload", {{ profileId: "{EGO_BROWSER_PROFILE_ID}" }});
const p1 = task.page("p1");

console.log("[AccountRotator] Switching active session to: {target_email}");

// Navigate to Google OAuth or Claude sign out / sign in
await p1.goto("https://claude.ai/login");
await p1.waitForTimeout(3000);

const isLoginPage = await p1.evaluate(() => {{
  return !!document.querySelector("button:has-text('Continue with Google')") || window.location.href.includes("login");
}});

if (!isLoginPage) {{
  // Log out of current session
  console.log("[AccountRotator] Logging out of current session...");
  await p1.goto("https://claude.ai/api/auth/signout");
  await p1.waitForTimeout(3000);
  await p1.goto("https://claude.ai/login");
  await p1.waitForTimeout(3000);
}}

// Click Continue with Google
const googleBtn = await p1.locator("button:has-text('Continue with Google')");
if (await googleBtn.isVisible()) {{
  await googleBtn.click();
  await p1.waitForTimeout(4000);
}}

// Select the specific account
const tabs = await task.tabs();
const oauthTab = tabs.find(t => t.url.includes("accounts.google.com"));
if (oauthTab) {{
  const pOauth = task.page(oauthTab.label);
  console.log("[AccountRotator] Selecting Google account: {target_email}...");
  const accSelector = `div[data-identifier='{target_email}']`;
  try {{
    await pOauth.click(accSelector, {{ timeout: 5000 }});
    await pOauth.waitForTimeout(3000);
  }} catch (e) {{
    console.log("[AccountRotator] Direct selector not found, looking for text: {target_email}");
    await pOauth.click(`text='{target_email}'`);
  }}
}}
console.log("[AccountRotator] Account switch flow executed.");
"""
