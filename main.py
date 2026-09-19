import os
import json
import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright

# Robust import for playwright_stealth across versions
try:
    from playwright_stealth import stealth_async
except ImportError:
    try:
        from playwright_stealth import stealth_sync as stealth_async
    except ImportError:
        import playwright_stealth
        stealth_async = getattr(playwright_stealth, "stealth_async", getattr(playwright_stealth, "stealth", None))

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
def health():
    return {
        "status": "ok",
        "service": "gemini-render-service",
        "timestamp": asyncio.get_event_loop().time()
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
    if stealth_async:
        try:
            res = stealth_async(page)
            if asyncio.iscoroutine(res):
                await res
        except Exception as e:
            print(f"[Stealth Warning]: {e}")

async def run_automation(raw_prompt: str):
    clean_prompt = raw_prompt.lstrip("=").strip()
    formatted_prompt = f"Draw: {clean_prompt}"
    print(f"🚀 Sent Prompt: {formatted_prompt}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process"
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1024, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )

        if COOKIES_JSON:
            try:
                cookies = json.loads(COOKIES_JSON)
                playwright_cookies = []
                for c in cookies:
                    playwright_cookies.append({
                        "name": c.get("name"),
                        "value": c.get("value"),
                        "domain": c.get("domain", ".google.com"),
                        "path": c.get("path", "/"),
                        "secure": c.get("secure", True),
                        "httpOnly": c.get("httpOnly", True),
                        "sameSite": c.get("sameSite", "None")
                    })
                await context.add_cookies(playwright_cookies)
                print(f"[Gemini Render] {len(playwright_cookies)} cookies mounted.")
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
        await page.goto("https://gemini.google.com/app", wait_until="commit", timeout=40000)

        input_sel = 'rich-textarea p, div[contenteditable="true"], p[data-placeholder]'
        try:
            await page.wait_for_selector(input_sel, timeout=30000)
        except Exception as e:
            content = await page.content()
            curr_url = page.url
            if "Sign in" in content or "accounts.google.com" in curr_url:
                print("[Gemini Render] Session expired / Bot detected.")
                raise HTTPException(status_code=401, detail="Google session verification required.")
            raise HTTPException(status_code=504, detail=f"Timeout waiting for prompt box. (URL: {curr_url})")

        await page.click(input_sel)
        await page.fill(input_sel, formatted_prompt)
        await asyncio.sleep(0.5)

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

            await asyncio.sleep(2.5)

        if not base64_data:
            text_dump = await page.inner_text("body")
            print(f"❌ [Gemini Output Dump]: {text_dump[-300:]}")
            await browser.close()
            raise HTTPException(status_code=422, detail="Gemini did not generate an image.")

        await browser.close()

        print("[Gemini Render] Uploading pure base64 to Cloudinary...")
        if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
            upload_res = cloudinary.uploader.upload(
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

@app.post("/generate-image")
async def generate_image(req: ImageRequest):
    try:
        return await asyncio.wait_for(run_automation(req.prompt), timeout=100.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Operation timed out after 100 seconds.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
