import subprocess
import time
import re
import sys
import os
import urllib.request

SUBDOMAIN = "gemini-chatgpt-dual-gen-99"

def start_server():
    print("[SERVER] Starting local FastAPI server (main.py)...", flush=True)
    return subprocess.Popen(
        [sys.executable, "main.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore"
    )

def start_tunnel():
    print(f"[TUNNEL] Starting Localtunnel with fixed subdomain ({SUBDOMAIN})...", flush=True)
    return subprocess.Popen(
        ["npx.cmd", "localtunnel", "--port", "8000", "--subdomain", SUBDOMAIN],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore",
        bufsize=1
    )

def main():
    server_proc = start_server()
    time.sleep(3)

    tunnel_proc = start_tunnel()
    tunnel_url = f"https://{SUBDOMAIN}.loca.lt"

    start_time = time.time()
    while time.time() - start_time < 20:
        line = tunnel_proc.stdout.readline()
        if line:
            print("[Tunnel Log]", line.strip(), flush=True)
            if "your url is:" in line or "loca.lt" in line:
                match = re.search(r'https://[a-zA-Z0-9-]+\.loca\.lt', line)
                if match:
                    tunnel_url = match.group(0)
                break

    print(f"\n=======================================================", flush=True)
    print(f"SUCCESS: STABLE TUNNEL LIVE AT: {tunnel_url}", flush=True)
    print(f"=======================================================\n", flush=True)
    
    with open("active_tunnel_url.txt", "w", encoding="utf-8") as f:
        f.write(tunnel_url)

    # Heartbeat keep-alive loop to prevent 503 idle timeouts
    ping_counter = 0
    try:
        while True:
            time.sleep(15)
            ping_counter += 1
            # Check local server health
            try:
                urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5)
            except Exception as e:
                print(f"[HEARTBEAT] Local server ping warning: {e}", flush=True)

            # Check tunnel health every 30s to keep connection alive
            if ping_counter % 2 == 0:
                try:
                    req = urllib.request.Request(
                        f"{tunnel_url}/health",
                        headers={"Bypass-Tunnel-Reminder": "true", "User-Agent": "Heartbeat"}
                    )
                    urllib.request.urlopen(req, timeout=8)
                    print(f"[HEARTBEAT] Tunnel ping OK ({tunnel_url})", flush=True)
                except Exception as e:
                    print(f"[HEARTBEAT] Tunnel ping failed: {e}. Restarting tunnel...", flush=True)
                    try:
                        tunnel_proc.terminate()
                    except Exception:
                        pass
                    tunnel_proc = start_tunnel()

    except KeyboardInterrupt:
        print("[EXIT] Shutting down server and tunnel...", flush=True)
        server_proc.terminate()
        tunnel_proc.terminate()

if __name__ == "__main__":
    main()
