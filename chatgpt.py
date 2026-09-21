import os
import json
import asyncio
import base64
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright
try:
    from playwright_stealth import Stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False

import cloudinary
import cloudinary.uploader

async def upload_to_cloudinary_async(image_data: str) -> Optional[str]:
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")

    if not (cloud_name and api_key and api_secret):
        print("[ChatGPT Render] Warning: Cloudinary keys not found. Returning base64 URI.")
        return None

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True
    )

    try:
        response = await asyncio.to_thread(
            cloudinary.uploader.upload,
            image_data,
            folder="chatgpt_renders"
        )
        return response.get("secure_url")
    except Exception as e:
        print(f"[ChatGPT Render] Cloudinary upload error: {e}")
        return None

async def apply_stealth_if_available(page):
    if STEALTH_AVAILABLE:
        try:
            await Stealth().apply_stealth_async(page)
            print("[ChatGPT Render] Stealth evasion applied successfully!")
        except Exception as e:
            print(f"[ChatGPT Stealth Warning]: {e}")

async def run_chatgpt_automation(raw_prompt: str) -> Dict[str, Any]:
    clean_prompt = raw_prompt.lstrip("=").strip()
    lower_p = clean_prompt.lower()
    if not (lower_p.startswith("create") or lower_p.startswith("generate") or lower_p.startswith("draw") or lower_p.startswith("make")):
        formatted_prompt = f"Create an image of: {clean_prompt}"
    else:
        formatted_prompt = clean_prompt
    print(f"🚀 [ChatGPT] Sent Prompt: {formatted_prompt}")

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

        cookies_env = os.getenv("CHATGPT_COOKIES_JSON")
        if not cookies_env and os.path.exists("chatgpt_cookies.json"):
            try:
                with open("chatgpt_cookies.json", "r", encoding="utf-8-sig") as f:
                    cookies_env = f.read()
            except Exception as e:
                print(f"[ChatGPT Cookie File Error]: {e}")

        if cookies_env:
            try:
                cookies = json.loads(cookies_env.strip().strip("\ufeff"))
                playwright_cookies = []
                for c in cookies:
                    name = c.get("name")
                    value = c.get("value")
                    if not name or not value:
                        continue
                    domain = c.get("domain", ".chatgpt.com").strip()
                    if not domain:
                        domain = ".chatgpt.com"
                    path = c.get("path", "/")
                    playwright_cookies.append({
                        "name": name,
                        "value": value,
                        "domain": domain,
                        "path": path,
                        "secure": bool(c.get("secure", True)),
                        "httpOnly": bool(c.get("httpOnly", False))
                    })
                await context.add_cookies(playwright_cookies)
                print(f"[ChatGPT Render] {len(playwright_cookies)} cookies mounted.")
            except Exception as e:
                print(f"[ChatGPT Cookie Error]: {e}")

        page = await context.new_page()
        await apply_stealth_if_available(page)

        print("[ChatGPT Render] Navigating to ChatGPT...")
        await page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(2)

        # Check for prompt textarea
        input_selector = "#prompt-textarea, textarea, div[contenteditable='true']"
        try:
            await page.wait_for_selector(input_selector, timeout=15000)
        except Exception:
            print("[ChatGPT Render] Prompt input not found or auth expired.")
            await browser.close()
            raise Exception("401: Session expired or prompt input unavailable.")

        # Fill prompt
        try:
            await page.fill("#prompt-textarea", formatted_prompt)
        except Exception:
            await page.type(input_selector, formatted_prompt)

        await asyncio.sleep(1)

        # Click send button or press Enter
        send_btn = "button[data-testid='send-button']"
        try:
            await page.click(send_btn, timeout=3000)
        except Exception:
            await page.keyboard.press("Enter")

        print("[ChatGPT Render] Prompt submitted. Polling for generated image...")

        # Poll for image generation (DALL-E images in ChatGPT)
        max_attempts = 45
        attempt = 0
        final_image_data = None

        while attempt < max_attempts:
            await asyncio.sleep(1.5)
            attempt += 1

            # Search for DALL-E image tags or general rendered canvas/img elements
            eval_js = """
            () => {
                const imgs = Array.from(document.querySelectorAll('img'));
                for (let img of imgs) {
                    const src = img.src || '';
                    const alt = img.alt || '';
                    if (src.includes('oaidalleapiprod') || src.includes('files.oaiusercontent.com') || alt.toLowerCase().includes('generated by dall')) {
                        return { src: src, alt: alt };
                    }
                }
                return null;
            }
            """
            result = await page.evaluate(eval_js)
            if result and result.get("src"):
                print(f"[ChatGPT Render] Found DALL-E image on attempt {attempt}!")
                img_src = result["src"]
                
                # Fetch image bytes via browser fetch to avoid CORS/auth restrictions
                b64_js = """
                async (url) => {
                    const resp = await fetch(url);
                    const blob = await resp.blob();
                    return new Promise((resolve) => {
                        const reader = new FileReader();
                        reader.onloadend = () => resolve(reader.result);
                        reader.readAsDataURL(blob);
                    });
                }
                """
                try:
                    data_url = await page.evaluate(b64_js, img_src)
                    if data_url:
                        final_image_data = data_url
                        break
                except Exception as e:
                    print(f"[ChatGPT Fetch Warning]: {e}")
                    final_image_data = img_src
                    break

        await browser.close()

        if not final_image_data:
            raise Exception("422: ChatGPT did not generate an image.")

        # Upload to Cloudinary if available
        cloud_url = await upload_to_cloudinary_async(final_image_data)
        image_url = cloud_url if cloud_url else final_image_data

        return {
            "status": "success",
            "success": True,
            "engine": "ChatGPT DALL-E 3",
            "image_url": image_url,
            "aspect_ratio": "1:1"
        }
