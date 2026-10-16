import os
import sys
import time
import json
import random
import base64
import threading
import re
from datetime import datetime, timezone

from curl_cffi import requests as cffi_requests
import websocket



CONFIG_FILE = "config.json"
API_BASE = "https://discord.com/api/v9"
GATEWAY_URL = "wss://gateway.discord.gg/?v=9&encoding=json"

C_CYAN = "\033[96m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_RST = "\033[0m"

def detect_local_discord_version():
    localapp = os.getenv("LOCALAPPDATA")
    if not localapp:
        return "1.0.9261"

    ddir = os.path.join(localapp, "Discord")
    if os.path.exists(ddir):
        for entry in os.listdir(ddir):
            if entry.startswith("app-"):
                return entry.replace("app-", "")

    return "1.0.9261"

def fetch_live_build_number():
    try:
        r = cffi_requests.get("https://discord.com/app", impersonate="chrome120", timeout=8)
        scripts = re.findall(r'/assets/[a-zA-Z0-9\.\-]+\.js', r.text)
        for s in reversed(scripts[-15:]):
            res = cffi_requests.get("https://discord.com" + s, impersonate="chrome120", timeout=6)
            m = re.search(r'buildNumber["\':\s]+(\d{6,7})', res.text) or re.search(r'build_number["\':\s]+(\d{6,7})', res.text)
            if m:
                return int(m.group(1))
    except cffi_requests.RequestsError:
        pass
    return 638651

def load_token():
    for fpath in (CONFIG_FILE, "orb_config.json"):
        if os.path.isfile(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    if cfg.get("token"):
                        return cfg["token"].strip()
            except (OSError, json.JSONDecodeError):
                pass

    env_tok = os.getenv("DISCORD_TOKEN")
    if env_tok:
        return env_tok.strip()

    print(f"{C_YELLOW}[*] No saved token found.{C_RST}")
    user_input = input("Enter your Discord User Token: ").strip()
    if user_input:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"token": user_input}, f, indent=2)
        return user_input

    return None

class Gateway:
    def __init__(self, token, super_properties):
        self.token = token
        self.super_properties = super_properties
        self.ws = None
        self.session_id = None
        self.running = False
        self.thread = None
        self.heartbeat_thread = None
        self.heartbeat_interval = 41.25
        self.ready_event = threading.Event()

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run_ws, daemon=True)
        self.thread.start()
        self.ready_event.wait(timeout=8.0)

    def stop(self):
        self.running = False
        if self.ws:
            try:
                self.ws.close()
            except (OSError, ValueError):
                pass

    def _run_ws(self):
        try:
            self.ws = websocket.WebSocket()
            self.ws.connect(GATEWAY_URL)
            hello = json.loads(self.ws.recv())
            if hello.get("op") == 10:
                self.heartbeat_interval = hello["d"]["heartbeat_interval"] / 1000.0

            self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
            self.heartbeat_thread.start()

            ident = {"token": self.token, "capabilities": 30717, "properties": self.super_properties}
            ident["presence"] = {"status": "online", "since": 0, "activities": [], "afk": False}
            ident["compress"] = False
            ident["client_state"] = {"guild_versions": {}}
            payload = {"op": 2, "d": ident}
            self.ws.send(json.dumps(payload))

            while self.running:
                data = self.ws.recv()
                if not data:
                    break
                msg = json.loads(data)
                if msg.get("t") == "READY":
                    self.session_id = msg.get("d", {}).get("session_id")
                    self.ready_event.set()
        except (websocket.WebSocketException, OSError, json.JSONDecodeError):
            pass

    def _heartbeat_loop(self):
        while self.running:
            time.sleep(self.heartbeat_interval)
            if self.ws and self.running:
                try:
                    self.ws.send(json.dumps({"op": 1, "d": None}))
                except websocket.WebSocketException:
                    break

    def update_presence(self, activities=None):
        if not self.ws or not self.running:
            return
        payload = {
            "op": 3,
            "d": {
                "since": None,
                "activities": activities or [],
                "status": "online",
                "afk": False
            }
        }
        try:
            self.ws.send(json.dumps(payload))
        except websocket.WebSocketException:
            pass

class DiscordRunner:
    def __init__(self, token):
        self.token = token
        self.session = cffi_requests.Session(impersonate="chrome120")
        self.client_version = detect_local_discord_version()
        self.build_number = fetch_live_build_number()

        self.super_properties = {
            "os": "Windows",
            "browser": "Discord Client",
            "release_channel": "stable",
            "client_version": self.client_version,
            "os_version": "10.0.19045",
            "os_arch": "x64",
            "app_arch": "x64",
            "system_locale": "en-US",
            "browser_user_agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/{self.client_version} Chrome/128.0.6613.186 Electron/32.2.7 Safari/537.36",
            "browser_version": "32.2.7",
            "client_build_number": self.build_number,
            "native_build_number": 55260,
            "client_event_source": None
        }

        self.encoded_props = base64.b64encode(json.dumps(self.super_properties).encode("utf-8")).decode("utf-8")
        self.context_props = base64.b64encode(json.dumps({"location": "Quest Home"}).encode("utf-8")).decode("utf-8")

        self.session.headers.update({
            "Authorization": self.token,
            "Content-Type": "application/json",
            "User-Agent": self.super_properties["browser_user_agent"],
            "X-Super-Properties": self.encoded_props,
            "X-Context-Properties": self.context_props,
            "X-Discord-Locale": "en-US",
            "X-Discord-Timezone": "America/New_York",
            "Accept": "*/*",
            "Sec-Ch-Ua": '"Not?A_Brand";v="99", "Chromium";v="128"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
        })

        self.gateway = Gateway(self.token, self.super_properties)

    def start_gateway(self):
        print(f"{C_YELLOW}[*] Connecting gateway...{C_RST}")
        self.gateway.start()
        if self.gateway.session_id:
            print(f"{C_GREEN}[+] Gateway active ({self.gateway.session_id[:10]}...){C_RST}")

    def close(self):
        self.gateway.stop()

    def get_user_profile(self):
        res = self.session.get(f"{API_BASE}/users/@me")
        if res.status_code == 200:
            return res.json()
        if res.status_code == 401:
            raise PermissionError("Token rejected by Discord (401)")
        res.raise_for_status()

    def get_quests(self):
        res = self.session.get(f"{API_BASE}/quests/@me")
        return res.json() if res.status_code == 200 else {}

    def get_claimed_quests(self):
        res = self.session.get(f"{API_BASE}/quests/@me/claimed")
        return res.json() if res.status_code == 200 else {}

    def enroll_quest(self, quest_id):
        res = self.session.post(f"{API_BASE}/quests/{quest_id}/enroll", json={"location": 1})
        if res.status_code in (200, 204):
            return res.json() if res.content else {}
        if res.status_code == 429:
            data = res.json() if res.content else {}
            return {"rate_limited": True, "retry_after": data.get("retry_after", 300)}
        return {}

    def send_video_progress(self, quest_id, timestamp):
        res = self.session.post(f"{API_BASE}/quests/{quest_id}/video-progress", json={"timestamp": round(timestamp, 2)})
        return res.json() if res.status_code == 200 else {}

    def claim_reward(self, quest_id):
        res = self.session.post(f"{API_BASE}/quests/{quest_id}/claim-reward", json={"location": 1, "platform": 0})
        if res.status_code == 200:
            return res.json()
        if res.status_code == 404:
            res2 = self.session.post(f"{API_BASE}/quests/{quest_id}/claim", json={})
            if res2.status_code == 200:
                return res2.json()
        if res.status_code == 400 and res.content:
            err = res.json()
            if "captcha_key" in err or "captcha_service" in err:
                return {"captcha_required": True, "details": err}
        return {}

    def stream_video_chunk(self, video_path, byte_start, byte_length=131072):
        if not video_path:
            return
        headers = {"Range": f"bytes={byte_start}-{byte_start + byte_length - 1}"}
        try:
            self.session.get(f"https://cdn.discordapp.com/{video_path}", headers=headers, timeout=5)
        except cffi_requests.RequestsError:
            pass

    def send_quest_heartbeat(self, quest_id, app_id, terminal=False):
        payload = {"stream_key": None, "application_id": str(app_id), "terminal": terminal}
        res = self.session.post(f"{API_BASE}/quests/{quest_id}/heartbeat", json=payload)
        return res.json() if res.status_code == 200 else {}

def show_progress(done, total, prefix=""):
    pct = (done / total * 100) if total > 0 else 100
    print(f"\r  {prefix}{done:.0f}/{total:.0f}s ({pct:.0f}%)", end="", flush=True)

def process_video_quest(client, quest):
    quest_id = quest["id"]
    cfg = quest.get("config", {})
    msgs = cfg.get("messages", {})
    quest_name = msgs.get("quest_name", f"Quest #{quest_id}")

    task_config = cfg.get("task_config_v2") or cfg.get("task_config") or {}
    tasks = task_config.get("tasks", {})

    task_name = next((t for t in ("WATCH_VIDEO", "WATCH_VIDEO_ON_MOBILE") if t in tasks), None)
    if not task_name:
        return False

    task_data = tasks[task_name]
    seconds_needed = float(task_data.get("target", 30.0))
    user_status = quest.get("user_status") or {}

    task_assets = task_data.get("assets", {})
    video_asset = (
        task_assets.get("video", {}).get("url")
        or task_assets.get("video_low_res", {}).get("url")
        or cfg.get("assets", {}).get("hero_video")
        or cfg.get("assets", {}).get("quest_bar_hero_video")
    )

    rewards_data = cfg.get("rewards") or cfg.get("rewards_config", {})
    rewards_list = rewards_data.get("rewards", []) if isinstance(rewards_data, dict) else (rewards_data if isinstance(rewards_data, list) else [])

    reward_desc = "Reward"
    for r in rewards_list:
        if isinstance(r, dict):
            if r.get("orb_quantity"):
                reward_desc = f"{r.get('orb_quantity')} Orbs"
                break
            if r.get("messages", {}).get("name"):
                reward_desc = r["messages"]["name"]
                break

    print(f"\n{C_BOLD}{C_CYAN}--- Video Quest: {quest_name} ---{C_RST}")
    print(f"  ID: {quest_id} | Reward: {C_GREEN}{reward_desc}{C_RST} | Target: {seconds_needed:.0f}s")

    if not user_status.get("enrolled_at"):
        print(f"  {C_YELLOW}[*] Enrolling...{C_RST}")
        enroll_res = client.enroll_quest(quest_id)
        if enroll_res.get("rate_limited"):
            retry_sec = float(enroll_res.get("retry_after", 300))
            print(f"  {C_YELLOW}[!] Rate limited (429). Wait {retry_sec:.0f}s.{C_RST}")
            return {"rate_limited": True, "retry_after": retry_sec}
        user_status = enroll_res.get("user_status", enroll_res)
        print(f"  {C_GREEN}[+] Enrolled.{C_RST}")

    if user_status.get("completed_at"):
        print(f"  {C_GREEN}[+] Already completed.{C_RST}")
    else:
        prog_dict = user_status.get("progress", {}).get(task_name) or {}
        seconds_done = float(prog_dict.get("value", 0.0))
        cdn_offset = 0

        if video_asset:
            client.stream_video_chunk(video_asset, 0, 262144)
            cdn_offset += 262144

        start_time = time.time()
        while seconds_done < seconds_needed:
            step = min(seconds_needed - seconds_done, random.uniform(5.5, 7.2))
            show_progress(seconds_done, seconds_needed, prefix="Streaming: ")
            time.sleep(step)

            if video_asset and seconds_done < seconds_needed:
                client.stream_video_chunk(video_asset, cdn_offset, 131072)
                cdn_offset += 131072

            next_ts = min(seconds_needed, seconds_done + step + random.uniform(0.05, 0.3))
            res = client.send_video_progress(quest_id, next_ts)
            prog = res.get("progress", {}).get(task_name, {}) if isinstance(res, dict) else {}
            seconds_done = float(prog.get("value", next_ts))
            show_progress(seconds_done, seconds_needed, prefix="Streaming: ")

            if res.get("completed_at") or seconds_done >= seconds_needed:
                break

        final_res = client.send_video_progress(quest_id, seconds_needed)
        print(f"\n  {C_GREEN}[+] Video finished in {time.time() - start_time:.1f}s.{C_RST}")

    if user_status.get("claimed_at"):
        print(f"  {C_GREEN}[+] Already claimed.{C_RST}")
    else:
        print(f"  {C_YELLOW}[*] Claiming reward...{C_RST}")
        time.sleep(random.uniform(1.2, 2.5))
        claim_res = client.claim_reward(quest_id)
        if isinstance(claim_res, dict) and claim_res.get("captcha_required"):
            print(f"  {C_GREEN}[+] 100% Complete! Direct claim requires app verification: click Claim in Discord.{C_RST}")
        else:
            orbs = claim_res.get("orb_quantity_claimed") if isinstance(claim_res, dict) else None
            msg = f"+{orbs} Orbs!" if orbs else "Claimed successfully."
            print(f"  {C_GREEN}[+] {msg}{C_RST}")

    return True

def process_game_quest(client, quest):
    quest_id = quest["id"]
    cfg = quest.get("config", {})
    msgs = cfg.get("messages", {})
    quest_name = msgs.get("quest_name", f"Quest #{quest_id}")
    game_title = msgs.get("game_title", quest_name)

    task_config = cfg.get("task_config_v2") or cfg.get("task_config") or {}
    tasks = task_config.get("tasks", {})
    task_data = tasks.get("PLAY_ON_DESKTOP")
    if not task_data:
        return False

    apps = task_data.get("applications", [])
    if not apps:
        return False
    app_id = apps[0].get("id")
    target_seconds = float(task_data.get("target", 900.0))
    user_status = quest.get("user_status") or {}

    print(f"\n{C_BOLD}{C_CYAN}--- Game Quest: {quest_name} ---{C_RST}")
    print(f"  Game: {game_title} | App ID: {app_id} | Target: {target_seconds/60:.0f}m")

    if not user_status.get("enrolled_at"):
        print(f"  {C_YELLOW}[*] Enrolling...{C_RST}")
        enroll_res = client.enroll_quest(quest_id)
        if isinstance(enroll_res, dict) and enroll_res.get("rate_limited"):
            retry_sec = float(enroll_res.get("retry_after", 300))
            return {"rate_limited": True, "retry_after": retry_sec}
        user_status = enroll_res.get("user_status", enroll_res)
        print(f"  {C_GREEN}[+] Enrolled.{C_RST}")

    if user_status.get("completed_at"):
        print(f"  {C_GREEN}[+] Quest already completed.{C_RST}")
        return True

    activity = [{
        "name": game_title,
        "type": 0,
        "application_id": str(app_id),
        "timestamps": {"start": int(time.time() * 1000)}
    }]
    client.gateway.update_presence(activity)
    print(f"  {C_GREEN}[+] Gateway presence set to Playing '{game_title}'{C_RST}")

    prog_dict = user_status.get("progress", {}).get("PLAY_ON_DESKTOP") or {}
    seconds_done = float(prog_dict.get("value", 0.0))

    try:
        while seconds_done < target_seconds:
            step = min(random.uniform(45.0, 58.0), max(5.0, target_seconds - seconds_done + 2))
            show_progress(seconds_done, target_seconds, prefix="Playing: ")
            time.sleep(step)

            is_terminal = (seconds_done + step >= target_seconds)
            hb_res = client.send_quest_heartbeat(quest_id, app_id, terminal=is_terminal)
            p_info = hb_res.get("progress", {}).get("PLAY_ON_DESKTOP") or {}
            seconds_done = float(p_info.get("value", seconds_done + step))
            if hb_res.get("completed_at") or is_terminal:
                show_progress(target_seconds, target_seconds, prefix="Playing: ")
                print(f"\n  {C_GREEN}[+] Finished 15-minute game quest!{C_RST}")
                break
    finally:
        client.gateway.update_presence([])

    return True

def run_watcher(client):
    print(f"\n{C_BOLD}[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checking quests...{C_RST}")
    quests_data = client.get_quests()
    if not quests_data or not isinstance(quests_data, dict):
        print(f"{C_RED}[!] Could not fetch quests.{C_RST}")
        return

    quests = quests_data.get("quests", [])
    if not quests:
        print(f"{C_DIM}[i] No active quests found on account.{C_RST}")
        return

    video_quests = []
    game_quests = []
    now = datetime.now(timezone.utc)

    for q in quests:
        cfg = q.get("config", {})
        exp_str = cfg.get("expires_at")
        if exp_str:
            try:
                if datetime.fromisoformat(exp_str) <= now:
                    continue
            except (OSError, ValueError):
                pass

        tasks = (cfg.get("task_config_v2") or cfg.get("task_config") or {}).get("tasks", {})
        ustatus = q.get("user_status") or {}
        if ustatus.get("claimed_at"):
            continue

        if any(t in tasks for t in ("WATCH_VIDEO", "WATCH_VIDEO_ON_MOBILE")):
            video_quests.append(q)
        elif "PLAY_ON_DESKTOP" in tasks:
            game_quests.append(q)

    all_quests = [("video", q) for q in video_quests] + [("game", q) for q in game_quests]
    if not all_quests:
        print(f"{C_DIM}[i] All available quests are already completed/claimed.{C_RST}")
        return

    print(f"{C_GREEN}[+] Found {len(video_quests)} video ad quest(s) and {len(game_quests)} game quest(s).{C_RST}")

    for idx, (qtype, q) in enumerate(all_quests):
        handler = process_video_quest if qtype == "video" else process_game_quest
        res = handler(client, q)
        if isinstance(res, dict) and res.get("rate_limited"):
            wait_s = float(res.get("retry_after", 300)) + 5
            print(f"\n{C_YELLOW}[i] Discord cooldown: waiting {wait_s:.0f}s...{C_RST}")
            time.sleep(wait_s)
            handler(client, q)
        elif idx < len(all_quests) - 1:
            delay = random.uniform(15.0, 30.0)
            print(f"\n{C_DIM}[i] Waiting {delay:.0f}s before next quest...{C_RST}")
            time.sleep(delay)

def main():
    token = load_token()
    if not token:
        print("[!] No Discord token provided.")
        sys.exit(1)

    client = DiscordRunner(token)
    user = client.get_user_profile()
    if not user or not user.get("username"):
        print("[!] Login failed: invalid user profile.")
        sys.exit(1)
    print(f"[+] Logged in as: {user.get('global_name') or user.get('username')} (@{user['username']})")

    client.start_gateway()
    try:
        run_watcher(client)
        print("\n[✔] Done.")
    finally:
        client.close()

if __name__ == "__main__":
    main()
