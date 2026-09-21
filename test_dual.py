import os
import json
import asyncio
import sys

sys.stdout.reconfigure(encoding='utf-8')
from chatgpt import run_chatgpt_automation
from main import run_automation

async def test_dual():
    prompt = "A photorealistic commercial scene of a happy couple standing in front of a newly purchased modern house, under bright, natural daylight."
    print("🚀 [DUAL TEST] Launching simultaneous Gemini + ChatGPT image generation...")
    
    if os.path.exists("cookies.json"):
        with open("cookies.json", "r", encoding="utf-8-sig") as f:
            os.environ["GOOGLE_COOKIES_JSON"] = f.read()

    if os.path.exists("chatgpt_cookies.json"):
        with open("chatgpt_cookies.json", "r", encoding="utf-8-sig") as f:
            os.environ["CHATGPT_COOKIES_JSON"] = f.read()

    results = await asyncio.gather(
        run_automation(prompt),
        run_chatgpt_automation(prompt),
        return_exceptions=True
    )

    gemini_res, chatgpt_res = results

    print("\n================ DUAL TEST RESULTS ================")
    print("🔹 Gemini Result:", gemini_res.get("image_url")[:80] if isinstance(gemini_res, dict) else f"Error: {gemini_res}")
    print("🔹 ChatGPT Result:", chatgpt_res.get("image_url")[:80] if isinstance(chatgpt_res, dict) else f"Error: {chatgpt_res}")
    print("====================================================")

if __name__ == "__main__":
    asyncio.run(test_dual())
