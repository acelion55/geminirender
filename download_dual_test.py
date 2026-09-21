import os
import json
import asyncio
import base64
import requests
from main import run_automation
from chatgpt import run_chatgpt_automation

async def test_and_download_both():
    prompt = "A futuristic cybernetic tiger with glowing neon blue stripes, 8k cinematic studio render."
    print("🚀 [DUAL TEST] Triggering Parallel Gemini & ChatGPT Generation...")

    # Load session cookies
    if os.path.exists("cookies.json"):
        with open("cookies.json", "r", encoding="utf-8-sig") as f:
            os.environ["GOOGLE_COOKIES_JSON"] = f.read()

    if os.path.exists("chatgpt_cookies.json"):
        with open("chatgpt_cookies.json", "r", encoding="utf-8-sig") as f:
            os.environ["CHATGPT_COOKIES_JSON"] = f.read()

    # Gather tasks concurrently
    gemini_task = asyncio.create_task(run_automation(prompt))
    chatgpt_task = asyncio.create_task(run_chatgpt_automation(prompt))

    results = await asyncio.gather(gemini_task, chatgpt_task, return_exceptions=True)

    gemini_res, chatgpt_res = results

    print("\n--- RESULTS ---")
    print("Gemini Result:", gemini_res if not isinstance(gemini_res, Exception) else f"Error: {gemini_res}")
    print("ChatGPT Result:", chatgpt_res if not isinstance(chatgpt_res, Exception) else f"Error: {chatgpt_res}")

    def save_image(img_url, filename):
        if not img_url or not isinstance(img_url, str):
            return False
        if img_url.startswith("data:image"):
            header, b64_data = img_url.split(",", 1)
            img_bytes = base64.b64decode(b64_data)
            with open(filename, "wb") as f:
                f.write(img_bytes)
            print(f"✅ Saved {filename} ({len(img_bytes)} bytes)")
            return True
        elif img_url.startswith("http"):
            resp = requests.get(img_url)
            with open(filename, "wb") as f:
                f.write(resp.content)
            print(f"✅ Downloaded {filename} ({len(resp.content)} bytes)")
            return True
        return False

    if isinstance(gemini_res, dict) and gemini_res.get("image_url"):
        save_image(gemini_res["image_url"], "gemini_image.png")

    if isinstance(chatgpt_res, dict) and chatgpt_res.get("image_url"):
        save_image(chatgpt_res["image_url"], "chatgpt_image.png")

if __name__ == "__main__":
    asyncio.run(test_and_download_both())
