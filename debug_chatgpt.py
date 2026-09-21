import os
import json
import asyncio
from playwright.async_api import async_playwright

async def debug_chatgpt_view():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )

        if os.path.exists("chatgpt_cookies.json"):
            with open("chatgpt_cookies.json", "r", encoding="utf-8-sig") as f:
                cookies = json.load(f)
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
                print(f"Mounted {len(playwright_cookies)} cookies.")

        page = await context.new_page()
        print("Navigating to https://chatgpt.com ...")
        await page.goto("https://chatgpt.com", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(5)

        # Check prompt element
        prompt_el = await page.query_selector("#prompt-textarea, textarea, div[contenteditable='true']")
        print("Prompt element found:", bool(prompt_el))

        # Save screenshot
        screenshot_path = "chatgpt_playwright_view.png"
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"Captured screenshot at {screenshot_path}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_chatgpt_view())
