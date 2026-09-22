import os
import json
import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright

# Robust import for playwright_stealth
try:
    from playwright_stealth import Stealth
except ImportError:
    Stealth = None

import cloudinary
import cloudinary.uploader
import httpx

app = FastAPI(title="Gemini 1:1 Automation Service")

PORT = int(os.getenv("PORT", 8000))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", f"http://localhost:{PORT}")

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")

if CLOUDINARY_CLOUD_NAME:
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
        secure=True
    )

COOKIES_JSON = os.getenv("GOOGLE_COOKIES_JSON", "")
SECURE_1PSID = os.getenv("SECURE_1PSID", "")
SECURE_1PSIDTS = os.getenv("SECURE_1PSIDTS", "")

class ImageRequest(BaseModel):
    prompt: str

@app.get("/health")
async def health():
    import time
    return {
        "status": "ok",
        "service": "gemini-render-service",
        "timestamp": time.time()
    }

async def keep_awake():
    """Background task to self-ping /health every 10 minutes to prevent Render sleep."""
    while True:
        await asyncio.sleep(600)  # Every 10 minutes
        health_url = f"{RENDER_EXTERNAL_URL}/health"
        print(f"[Keep-Awake] Pinging health check: {health_url}")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(health_url, timeout=10.0)
                print(f"[Keep-Awake] Heartbeat status: {resp.status_code}")
        except Exception as e:
            print(f"[Keep-Awake] Heartbeat note: {e}")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(keep_awake())

async def apply_stealth(page):
    if Stealth:
        try:
            await Stealth().apply_stealth_async(page)
            print("[Gemini Render] Stealth evasion applied successfully!")
        except Exception as e:
            print(f"[Stealth Warning]: {e}")

async def run_automation(raw_prompt: str):
    clean_prompt = raw_prompt.lstrip("=").strip()
    lower_p = clean_prompt.lower()
    if not (lower_p.startswith("create") or lower_p.startswith("generate") or lower_p.startswith("draw") or lower_p.startswith("make")):
        formatted_prompt = f"Create an image of: {clean_prompt}"
    else:
        formatted_prompt = clean_prompt
    print(f"🚀 Sent Prompt: {formatted_prompt}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled"
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )


        cookies_env = os.getenv("GOOGLE_COOKIES_JSON")
        if not cookies_env and os.path.exists("cookies.json"):
            try:
                with open("cookies.json", "r", encoding="utf-8-sig") as f:
                    cookies_env = f.read()
            except Exception as e:
                print(f"[Gemini Cookie File Error]: {e}")

        if cookies_env:
            try:
                cookies = json.loads(cookies_env.strip().strip("\ufeff"))
                playwright_cookies = []
                names_added = set()

                for c in cookies:
                    name = str(c.get("name", "")).strip()
                    value = str(c.get("value", "")).strip()
                    if not name or not value:
                        continue

                    domain = str(c.get("domain", ".google.com")).strip()
                    if not domain:
                        domain = ".google.com"

                    cookie_obj = {
                        "name": name,
                        "value": value,
                        "domain": domain,
                        "path": str(c.get("path", "/")).strip() or "/",
                        "secure": bool(c.get("secure", True)),
                        "httpOnly": bool(c.get("httpOnly", False))
                    }
                    same_site = str(c.get("sameSite", "")).strip().capitalize()
                    if same_site in ["Strict", "Lax", "None"]:
                        cookie_obj["sameSite"] = same_site

                    playwright_cookies.append(cookie_obj)
                    names_added.add(name)

                await context.add_cookies(playwright_cookies)
                print(f"[Gemini Render] {len(playwright_cookies)} cookies mounted. Key auth present: SID={'SID' in names_added}, HSID={'HSID' in names_added}, APISID={'APISID' in names_added}, 1PSID={'__Secure-1PSID' in names_added}, 1PSIDTS={'__Secure-1PSIDTS' in names_added}")
            except Exception as e:
                print(f"[Cookie Error]: {e}")
        elif SECURE_1PSID:
            await context.add_cookies([
                {"name": "__Secure-1PSID", "value": SECURE_1PSID, "domain": ".google.com", "path": "/", "secure": True, "httpOnly": True, "sameSite": "None"},
                {"name": "__Secure-1PSIDTS", "value": SECURE_1PSIDTS, "domain": ".google.com", "path": "/", "secure": True, "httpOnly": True, "sameSite": "None"}
            ])

        page = await context.new_page()
        await apply_stealth(page)

        print("[Gemini Render] Navigating to Gemini...")
        await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=40000)
        await asyncio.sleep(2.0)

        input_sel = 'rich-textarea p, div[contenteditable="true"], p[data-placeholder]'
        try:
            await page.wait_for_selector(input_sel, timeout=30000)
        except Exception as e:
            content = await page.content()
            curr_url = page.url
            if "Sign in" in content or "accounts.google.com" in curr_url or "Sign In" in content:
                print("[Gemini Render] Session expired / Bot detected. Google redirect to login.")
                raise HTTPException(status_code=401, detail="Google session expired or invalid. Full GOOGLE_COOKIES_JSON export required.")
            raise HTTPException(status_code=504, detail=f"Timeout waiting for prompt box. (URL: {curr_url})")

        await page.click(input_sel)
        await page.fill(input_sel, formatted_prompt)
        await asyncio.sleep(0.3)

        send_btn = await page.query_selector('button[aria-label*="Send message"], button[aria-label*="Send"]')
        if send_btn and await send_btn.is_enabled():
            print("[Gemini Render] Clicking Send button...")
            await send_btn.click()
        else:
            print("[Gemini Render] Pressing Enter key...")
            await page.keyboard.press("Enter")

        print("[Gemini Render] Prompt sent. Polling for generated <img> element...")

        start_time = asyncio.get_event_loop().time()
        base64_data = None

        while (asyncio.get_event_loop().time() - start_time) < 65.0:
            base64_data = await page.evaluate('''() => {
                const imgs = Array.from(document.querySelectorAll('img'));
                const target = imgs.find(img => {
                    const src = img.src || '';
                    const isValidSrc = src.startsWith('blob:') || src.includes('googleusercontent.com') || src.includes('/gg/');
                    const isNotIcon = !src.includes('s32-') && !src.includes('s64-') && !src.includes('s96-') && !src.includes('/a/') && !src.includes('avatar') && !src.includes('profile');
                    return isValidSrc && isNotIcon && img.naturalWidth > 200;
                });

                if (!target) return null;

                try {
                    const canvas = document.createElement('canvas');
                    canvas.width = target.naturalWidth;
                    canvas.height = target.naturalHeight;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(target, 0, 0);
                    return canvas.toDataURL('image/png');
                } catch (e) {
                    return null;
                }
            }''')

            if base64_data:
                print("✅ Found pure image and converted to DataURL via Canvas!")
                break

            await asyncio.sleep(1.0)

        if not base64_data:
            text_dump = await page.inner_text("body")
            print(f"❌ [Gemini Output Dump]: {text_dump[-300:]}")
            await browser.close()
            raise HTTPException(status_code=422, detail="Gemini did not generate an image.")

        await browser.close()

        print("[Gemini Render] Uploading pure base64 to Cloudinary...")
        if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
            upload_res = await asyncio.to_thread(
                cloudinary.uploader.upload,
                base64_data,
                folder="finonest_car_loans"
            )
            final_cdn_url = upload_res.get("secure_url")
            print(f"[Gemini Render] Cloudinary upload successful: {final_cdn_url}")
        else:
            print("[Gemini Render] Warning: Cloudinary keys not found. Returning base64 URI.")
            final_cdn_url = base64_data

        return {
            "status": "success",
            "success": True,
            "aspect_ratio": "1:1",
            "image_url": final_cdn_url
        }

from chatgpt import run_chatgpt_automation

@app.post("/generate-image")
async def generate_image(req: ImageRequest):
    try:
        return await asyncio.wait_for(run_automation(req.prompt), timeout=150.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Operation timed out after 150 seconds.")

@app.post("/generate-chatgpt-image")
async def generate_chatgpt_image(req: ImageRequest):
    try:
        return await asyncio.wait_for(run_chatgpt_automation(req.prompt), timeout=150.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="ChatGPT operation timed out after 150 seconds.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate-dual-images")
async def generate_dual_images(req: ImageRequest):
    try:
        print(f"🚀 Launching simultaneous Gemini + ChatGPT generation for: {req.prompt}")
        gemini_task = run_automation(req.prompt)
        chatgpt_task = run_chatgpt_automation(req.prompt)

        results = await asyncio.wait_for(
            asyncio.gather(gemini_task, chatgpt_task, return_exceptions=True),
            timeout=150.0
        )

        gemini_res, chatgpt_res = results

        gemini_url = gemini_res.get("image_url") if isinstance(gemini_res, dict) else None
        chatgpt_url = chatgpt_res.get("image_url") if isinstance(chatgpt_res, dict) else None

        return {
            "status": "success",
            "prompt": req.prompt,
            "gemini": {
                "success": isinstance(gemini_res, dict) and gemini_res.get("success", False),
                "image_url": gemini_url,
                "error": str(gemini_res) if isinstance(gemini_res, Exception) else None
            },
            "chatgpt": {
                "success": isinstance(chatgpt_res, dict) and chatgpt_res.get("success", False),
                "image_url": chatgpt_url,
                "error": str(chatgpt_res) if isinstance(chatgpt_res, Exception) else None
            }
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Dual generation timed out after 150 seconds.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
