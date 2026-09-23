import os
import json
import sys
import asyncio
import base64
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

# Force UTF-8 output streams on Windows to prevent charmap encoding errors
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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

def get_cloudinary_config():
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
    api_key = os.getenv("CLOUDINARY_API_KEY", "").strip()
    api_secret = os.getenv("CLOUDINARY_API_SECRET", "").strip()
    if cloud_name and api_key and api_secret:
        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True
        )
        return True
    return False

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
    print(f"[Gemini Prompt] Sent Prompt: {formatted_prompt}")

    proxy_server = os.getenv("PROXY_SERVER", None)
    proxy_user = os.getenv("PROXY_USER", None)
    proxy_pass = os.getenv("PROXY_PASS", None)

    is_headless = os.getenv("HEADLESS", "true").lower() == "true"
    launch_args = {
        "headless": is_headless,
        "args": [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled"
        ]
    }
    if proxy_server:
        launch_args["proxy"] = {
            "server": proxy_server,
            "username": proxy_user,
            "password": proxy_pass
        }

    async with async_playwright() as p:
        browser = await p.chromium.launch(**launch_args)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )

        cookies_env = None
        if os.path.exists("cookies.json"):
            try:
                with open("cookies.json", "r", encoding="utf-8-sig") as f:
                    cookies_env = f.read()
                    print("[Gemini Render] Using fresh cookies.json file.")
            except Exception as e:
                print(f"[Gemini Cookie File Error]: {e}")
        
        if not cookies_env:
            cookies_env = os.getenv("GOOGLE_COOKIES_JSON")

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
        await page.keyboard.type(formatted_prompt, delay=5)
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")
        await asyncio.sleep(0.5)

        print("[Gemini Render] Prompt sent via Enter key. Polling for generated img element...")

        start_time = asyncio.get_event_loop().time()
        base64_data = None

        while (asyncio.get_event_loop().time() - start_time) < 95.0:
            raw_extracted = await page.evaluate('''async () => {
                const imgs = Array.from(document.querySelectorAll('img, picture img, [role="img"]'));
                const target = imgs.find(img => {
                    const src = img.src || img.currentSrc || '';
                    const isValidSrc = src.startsWith('blob:') || src.includes('googleusercontent') || src.includes('ggpht') || src.includes('/gg/') || src.includes('lh3') || src.startsWith('data:image');
                    const isNotIcon = !src.includes('s32-') && !src.includes('s64-') && !src.includes('s96-') && !src.includes('/a/') && !src.includes('avatar') && !src.includes('profile') && !src.includes('favicon');
                    const w = img.naturalWidth || img.clientWidth || img.width || 0;
                    const h = img.naturalHeight || img.clientHeight || img.height || 0;
                    return isValidSrc && isNotIcon && (w > 50 || h > 50);
                });

                if (!target) return null;

                const targetSrc = target.currentSrc || target.src;

                // Tier 1: Try Canvas
                try {
                    const canvas = document.createElement('canvas');
                    canvas.width = target.naturalWidth || target.width;
                    canvas.height = target.naturalHeight || target.height;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(target, 0, 0);
                    const dataUrl = canvas.toDataURL('image/png');
                    if (dataUrl && dataUrl.length > 5000) return dataUrl;
                } catch (e) {}

                // Tier 2: Try Fetch
                try {
                    const resp = await fetch(targetSrc, { credentials: 'include' });
                    const blob = await resp.blob();
                    return await new Promise((resolve) => {
                        const reader = new FileReader();
                        reader.onloadend = () => resolve(reader.result);
                        reader.readAsDataURL(blob);
                    });
                } catch (e) {}

                // Tier 3: Return raw URL
                return targetSrc;
            }''')

            if raw_extracted:
                if raw_extracted.startswith("data:image"):
                    base64_data = raw_extracted
                    print("[SUCCESS] Found Gemini image and converted to DataURL!")
                    break
                elif raw_extracted.startswith("http"):
                    try:
                        # Fetch image content directly via playwright request context
                        img_resp = await page.request.get(raw_extracted)
                        if img_resp.status == 200:
                            img_bytes = await img_resp.body()
                            b64_str = base64.b64encode(img_bytes).decode('utf-8')
                            base64_data = f"data:image/png;base64,{b64_str}"
                            print(f"[SUCCESS] Fetched Gemini image from URL ({len(img_bytes)} bytes) and converted to DataURL!")
                            break
                    except Exception as ex:
                        print(f"[WARNING] Error fetching Gemini image URL: {ex}")
                        base64_data = raw_extracted
                        break

            await asyncio.sleep(1.0)

        if not base64_data:
            await page.screenshot(path="gemini_debug.png")
            text_dump = await page.inner_text("body")
            print(f"[ERROR] [Gemini Output Dump]: {text_dump[-400:]}")
            await browser.close()
            raise HTTPException(status_code=422, detail="Gemini did not generate an image.")

        await browser.close()

        print("[Gemini Render] Uploading image to Cloudinary...")
        if get_cloudinary_config():
            try:
                upload_res = await asyncio.to_thread(
                    cloudinary.uploader.upload,
                    base64_data,
                    folder="finonest_car_loans"
                )
                final_cdn_url = upload_res.get("secure_url")
                print(f"[Gemini Render] Cloudinary upload successful: {final_cdn_url}")
            except Exception as ce:
                print(f"[Gemini Render] Cloudinary upload error: {ce}")
                final_cdn_url = base64_data
        else:
            print("[Gemini Render] Warning: Cloudinary keys not found in environment. Returning base64/URL directly.")
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
        print(f"[DUAL GENERATION] Launching Gemini + ChatGPT generation concurrently for prompt: {req.prompt}")
        
        gemini_task = asyncio.wait_for(run_automation(req.prompt), timeout=110.0)
        chatgpt_task = asyncio.wait_for(run_chatgpt_automation(req.prompt), timeout=110.0)

        results = await asyncio.gather(gemini_task, chatgpt_task, return_exceptions=True)
        gemini_res, chatgpt_res = results[0], results[1]

        if isinstance(gemini_res, Exception):
            print(f"[WARNING] Gemini Dual Exception: {gemini_res}")
        if isinstance(chatgpt_res, Exception):
            print(f"[WARNING] ChatGPT Dual Exception: {chatgpt_res}")

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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
