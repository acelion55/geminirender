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
                    name = str(c.get("name", "")).strip()
                    value = str(c.get("value", "")).strip()
                    if not name or not value:
                        continue
                    domain = str(c.get("domain", ".chatgpt.com")).strip()
                    if not domain.endswith("chatgpt.com"):
                        domain = ".chatgpt.com"
                    path = str(c.get("path", "/")).strip() or "/"
                    
                    cookie_obj = {
                        "name": name,
                        "value": value,
                        "domain": domain,
                        "path": path,
                        "secure": bool(c.get("secure", True)),
                        "httpOnly": bool(c.get("httpOnly", False))
                    }
                    
                    same_site = str(c.get("sameSite", "")).strip().capitalize()
                    if same_site in ["Strict", "Lax", "None"]:
                        cookie_obj["sameSite"] = same_site

                    playwright_cookies.append(cookie_obj)
                await context.add_cookies(playwright_cookies)
                print(f"[ChatGPT Render] {len(playwright_cookies)} cookies mounted successfully.")
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
        max_attempts = 60
        attempt = 0
        final_image_data = None

        while attempt < max_attempts:
            await asyncio.sleep(1.5)
            attempt += 1

            # Search for DALL-E image tags or general rendered images in assistant messages
            eval_js = """
            () => {
                // Strategy 1: Look for any img in assistant conversation turns
                const articles = Array.from(document.querySelectorAll("article, div[data-message-author-role='assistant'], div[class*='agent-turn']"));
                for (let i = articles.length - 1; i >= 0; i--) {
                    const article = articles[i];
                    const role = article.getAttribute("data-message-author-role") || "";
                    if (role === "user") continue;

                    const imgs = Array.from(article.querySelectorAll("img"));
                    for (let img of imgs) {
                        const src = img.currentSrc || img.src || img.getAttribute("src") || "";
                        if (!src) continue;
                        if (src.includes("avatar") || src.includes("profile") || src.includes("googleusercontent") || src.endsWith(".svg")) continue;
                        return { src: src, alt: img.alt || "" };
                    }

                    const canvases = Array.from(article.querySelectorAll("canvas"));
                    if (canvases.length > 0) {
                        try {
                            const dataUrl = canvases[0].toDataURL("image/png");
                            if (dataUrl && dataUrl.length > 500) {
                                return { src: dataUrl, isCanvas: true };
                            }
                        } catch(e) {}
                    }
                }

                // Strategy 2: Global document search for DALL-E / generated images
                const allImgs = Array.from(document.querySelectorAll("img"));
                for (let img of allImgs) {
                    const src = img.currentSrc || img.src || "";
                    if (!src) continue;
                    if (src.includes("avatar") || src.includes("profile") || src.includes("googleusercontent") || src.endsWith(".svg")) continue;
                    if (src.includes("oaiusercontent") || src.includes("oaidalleapiprod") || src.includes("files.oai") || (img.alt && img.alt.toLowerCase().includes("generated"))) {
                        return { src: src, alt: img.alt || "" };
                    }
                }
                return null;
            }
            """
            result = await page.evaluate(eval_js)
            if result and result.get("src"):
                img_src = result["src"]
                print(f"[ChatGPT Render] Found image element on attempt {attempt}: {img_src[:60]}...")
                
                if result.get("isCanvas") or img_src.startswith("data:image"):
                    final_image_data = img_src
                    print("[ChatGPT Render] Extracted directly from canvas!")
                    break

                # Multi-tier extraction: Canvas -> Fetch -> Direct HTTP URL fallback
                b64_js = """
                async (targetSrc) => {
                    // Method 1: Draw onto Canvas
                    try {
                        const imgs = Array.from(document.querySelectorAll('img'));
                        const targetImg = imgs.find(i => (i.currentSrc || i.src) === targetSrc) || imgs.find(i => i.src && i.src.includes(targetSrc));
                        if (targetImg) {
                            targetImg.scrollIntoView({ block: 'center' });
                            const canvas = document.createElement('canvas');
                            canvas.width = targetImg.naturalWidth || targetImg.width || 1024;
                            canvas.height = targetImg.naturalHeight || targetImg.height || 1024;
                            const ctx = canvas.getContext('2d');
                            ctx.drawImage(targetImg, 0, 0, canvas.width, canvas.height);
                            const dataUrl = canvas.toDataURL('image/png');
                            if (dataUrl && dataUrl.length > 500 && !dataUrl.includes("data:image/png;base64,iVBORw0KGgoAAAANSUEUgAAAAEAAAAB")) {
                                return dataUrl;
                            }
                        }
                    } catch (e) {
                        console.log("Canvas export error:", e);
                    }

                    // Method 2: Fetch blob with credentials
                    try {
                        const resp = await fetch(targetSrc, { credentials: 'include' });
                        const blob = await resp.blob();
                        return new Promise((resolve) => {
                            const reader = new FileReader();
                            reader.onloadend = () => resolve(reader.result);
                            reader.readAsDataURL(blob);
                        });
                    } catch (e) {
                        console.log("Fetch export error:", e);
                    }

                    // Method 3: Direct URL fallback if http(s)
                    if (targetSrc.startsWith('http')) {
                        return targetSrc;
                    }
                    return null;
                }
                """
                try:
                    extracted_data = await page.evaluate(b64_js, img_src)
                    if extracted_data and len(extracted_data) > 30:
                        final_image_data = extracted_data
                        print("[ChatGPT Render] Successfully extracted image data!")
                        break
                except Exception as e:
                    print(f"[ChatGPT Fetch Warning]: {e}")
                    if img_src.startswith("http"):
                        final_image_data = img_src
                        break

        if not final_image_data:
            # Capture assistant's text response for diagnostics
            try:
                text_content = await page.evaluate("""() => {
                    const el = document.querySelector("div[data-message-author-role='assistant']");
                    return el ? el.innerText : document.body.innerText;
                }""")
                print(f"⚠️ [ChatGPT Output Dump]: {text_content[:300]}")
            except Exception:
                pass
            await browser.close()
            raise Exception("422: ChatGPT did not generate an image.")

        await browser.close()

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
