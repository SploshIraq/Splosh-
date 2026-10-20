import os
import sys
import json
import time
import subprocess
import traceback
import concurrent.futures
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

def load_config():
    config = {"token": "", "proxy": ""}
    if os.path.exists("config.json"):
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                config["token"] = data.get("token", "")
                config["proxy"] = data.get("proxy", "")
        except:
            pass
    return config

def delete_old_message(session, ch_id, msg_id, log_file):
    url = f"https://discord.com/api/v9/channels/{ch_id}/messages/{msg_id}"
    try:
        r = session.delete(url)
        if r.status_code == 204:
            print(f"    [-] Deleted: {msg_id}")
            log_file.write(f"Deleted: {msg_id}\n")
            log_file.flush()
            return 1
        elif r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 1.0)))
            session.delete(url)
            print(f"    [-] Deleted (after wait): {msg_id}")
            log_file.write(f"Deleted (after wait): {msg_id}\n")
            log_file.flush()
            return 1
    except:
        pass
    return 0

def main():
    print("==================================================")
    print("    Discord DM Wipe - TURBO + SHOW DELETED IDS    ")
    print("==================================================")
    
    config = load_config()
    token = config["token"]
    
    if not token or token in ("PASTE_USER_TOKEN_HERE", "PUT_YOUR_DISCORD_TOKEN_HERE"):
        token = input("[?] Please enter your Discord token: ").strip()
        
    if not token:
        print("[!] Token is required. Exiting...")
        return

    session = requests.Session()
    session.headers.update({
        "Authorization": token,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/json"
    })
    
    if config.get("proxy"):
        session.proxies = {"http": config["proxy"], "https": config["proxy"]}

    print("[*] Validating token...")
    try:
        r = session.get("https://discord.com/api/v9/users/@me")
        if r.status_code == 401:
            print("[!] ERROR: Invalid token or blocked.")
            return
        elif r.status_code != 200:
            print(f"[!] ERROR: Connection failed. HTTP {r.status_code}")
            return
    except Exception as e:
        print(f"[!] Connection error: {e}")
        return
        
    my_id = r.json()["id"]
    print(f"[+] Token valid! Logged in as {r.json()['username']}\n")

    target = input("id or all? ").strip().lower()
    channels_to_wipe = []

    if target == "all":
        print("[*] Fetching all DM channels...")
        r = session.get("https://discord.com/api/v9/users/@me/channels")
        if r.status_code == 200:
            for ch in r.json():
                if ch.get("type") == 1:
                    channels_to_wipe.append(ch["id"])
        else:
            print("[!] Failed to fetch channels.")
            return
    elif target == "id" or target.isdigit():
        user_id = input("The ID you want to delete from = ").strip() if target == "id" else target
        if not user_id.isdigit():
            print("[!] Invalid ID.")
            return
        print(f"[*] Opening DM with ID: {user_id}...")
        payload = {"recipient_id": user_id}
        r = session.post("https://discord.com/api/v9/users/@me/channels", json=payload)
        if r.status_code == 200:
            channels_to_wipe.append(r.json()["id"])
        else:
            print("[!] Failed to open DM. Check ID.")
            return
    else:
        print("[!] Invalid input. Please type 'id' or 'all'.")
        total_deleted = 0
    now = datetime.now(timezone.utc)
    
    log_file = open("deleted_log.txt", "a", encoding="utf-8")
    log_file.write(f"\n--- Wipe Session Started at {now} ---\n")

    for ch_id in channels_to_wipe:
        print(f"\n[*] Wiping Channel: {ch_id}...")
        deleted_in_ch = 0
        last_id = None
        
        while True:
            url = f"https://discord.com/api/v9/channels/{ch_id}/messages?limit=100"
            if last_id:
                url += f"&before={last_id}"
                
            r = session.get(url)
            if r.status_code != 200:
                break
                
            messages = r.json()
            if not messages:
                break
                
            my_msgs = [m for m in messages if m["author"]["id"] == my_id]
            last_id = messages[-1]["id"]
            
            if not my_msgs:
                continue

            bulk_ids = []
            old_ids = []
            
            for msg in my_msgs:
                msg_time = datetime.fromisoformat(msg["timestamp"].replace("Z", "+00:00"))
                age_days = (now - msg_time).days
                if age_days < 14:
                    bulk_ids.append(msg["id"])
                else:
                    old_ids.append(msg["id"])

            # 1. Bulk delete (prints logs too)
            if bulk_ids:
                bulk_url = f"https://discord.com/api/v9/channels/{ch_id}/messages/bulk-delete"
                br = session.post(bulk_url, json={"messages": bulk_ids})
                if br.status_code == 204:
                    for bid in bulk_ids:
                        print(f"    [-] Deleted (Bulk): {bid}")
                        log_file.write(f"Deleted (Bulk): {bid}\n")
                    log_file.flush()
                    deleted_in_ch += len(bulk_ids)
                elif br.status_code == 429:
                    time.sleep(float(br.json().get("retry_after", 1.0)))
                    session.post(bulk_url, json={"messages": bulk_ids})
                    deleted_in_ch += len(bulk_ids)

            # 2. Multi-threaded delete for old messages
            if old_ids:
                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    futures = [executor.submit(delete_old_message, session, ch_id, oid, log_file) for oid in old_ids]
                    for future in concurrent.futures.as_completed(futures):
                        deleted_in_ch += future.result()

        print(f"[+] Finished Channel {ch_id}. Total: {deleted_in_ch}")
        log_file.write(f"Finished Channel {ch_id}: {deleted_in_ch} messages.\n")
        total_deleted += deleted_in_ch

    log_file.write(f"--- Wipe Session Ended. Total: {total_deleted} ---\n")
    log_file.close()

    print(f"\n==================================================")
    print(f"[DONE] Total messages deleted: {total_deleted}")
    print(f"==================================================")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("\n[!] FATAL ERROR OCCURRED:")
        traceback.print_exc()
    finally:
        input("\n[ STOPPED ] Press Enter to exit...")
