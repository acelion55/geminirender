import subprocess
import time
import re
import sys

def main():
    print("🚀 Starting Cloudflare Tunnel with host header override...")
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", "http://127.0.0.1:8000", "--http-host-header", "localhost"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    url = None
    for line in proc.stdout:
        print(line, end="")
        if "trycloudflare.com" in line:
            match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
            if match:
                url = match.group(0)
                print(f"\n✨ FOUND TUNNEL URL: {url}\n", flush=True)
                with open("active_tunnel_url.txt", "w") as f:
                    f.write(url)
                break

    # Keep running
    proc.wait()

if __name__ == "__main__":
    main()
