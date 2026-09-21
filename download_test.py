import os
import json
import asyncio
import base64
import requests
from main import run_automation

async def test_and_download():
    prompt = "A majestic glowing golden lion sitting on a dark marble throne, dramatic studio lighting, 8k render."
    print("🚀 [TEST] Running Gemini Image Generation...")

    if os.path.exists("cookies.json"):
        with open("cookies.json", "r", encoding="utf-8-sig") as f:
            os.environ["GOOGLE_COOKIES_JSON"] = f.read()

    res = await run_automation(prompt)
    print("Result Status:", res.get("status"))

    image_url = res.get("image_url")
    if not image_url:
        print("❌ No image URL returned:", res)
        return

    out_file = "generated_gemini_image.png"

    if image_url.startswith("data:image"):
        # Base64 Data URL
        header, b64_data = image_url.split(",", 1)
        img_bytes = base64.b64decode(b64_data)
        with open(out_file, "wb") as f:
            f.write(img_bytes)
        print(f"✅ Saved Base64 image to {out_file} ({len(img_bytes)} bytes)")
    elif image_url.startswith("http"):
        # HTTP URL
        resp = requests.get(image_url)
        with open(out_file, "wb") as f:
            f.write(resp.content)
        print(f"✅ Downloaded HTTP image to {out_file} ({len(resp.content)} bytes)")

if __name__ == "__main__":
    asyncio.run(test_and_download())
