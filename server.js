const express = require('express');
const { chromium } = require('playwright');
const cloudinary = require('cloudinary').v2;
const http = require('http');
const https = require('https');

const app = express();
app.use(express.json());

const PORT = process.env.PORT || 8000;
const RENDER_EXTERNAL_URL = process.env.RENDER_EXTERNAL_URL || `http://localhost:${PORT}`;

// Configure Cloudinary from Environment Variables
const CLOUDINARY_CLOUD_NAME = process.env.CLOUDINARY_CLOUD_NAME || '';
const CLOUDINARY_API_KEY = process.env.CLOUDINARY_API_KEY || '';
const CLOUDINARY_API_SECRET = process.env.CLOUDINARY_API_SECRET || '';

if (CLOUDINARY_CLOUD_NAME) {
  cloudinary.config({
    cloud_name: CLOUDINARY_CLOUD_NAME,
    api_key: CLOUDINARY_API_KEY,
    api_secret: CLOUDINARY_API_SECRET,
    secure: true
  });
}

// Read Google cookies from Render Environment Variables
const GOOGLE_COOKIES_JSON = process.env.GOOGLE_COOKIES_JSON || '';
const SECURE_1PSID = process.env.SECURE_1PSID || '';
const SECURE_1PSIDTS = process.env.SECURE_1PSIDTS || '';

// 1. Health check API endpoint
app.get('/health', (req, res) => {
  res.status(200).json({ status: 'ok', service: 'gemini-render-service', uptime: process.uptime(), timestamp: new Date().toISOString() });
});

// 2. Keep-Awake Cron (Pings /health every 10 minutes so Render never sleeps)
setInterval(() => {
  const healthUrl = `${RENDER_EXTERNAL_URL}/health`;
  console.log(`[Keep-Awake] Pinging self health check: ${healthUrl}`);
  
  const client = healthUrl.startsWith('https') ? https : http;
  client.get(healthUrl, (res) => {
    console.log(`[Keep-Awake] Heartbeat status: ${res.statusCode}`);
  }).on('error', (err) => {
    console.log(`[Keep-Awake] Self-ping note: ${err.message}`);
  });
}, 10 * 60 * 1000); // Every 10 minutes

// Helper function to execute Playwright automation
async function runAutomation(rawPrompt) {
  const cleanPrompt = rawPrompt.replace(/^=+/, '').trim();
  
  // Gemini Imagen 3 explicit trigger command
  const formattedPrompt = `Draw: ${cleanPrompt}`;
  console.log(`🚀 Sent Direct Command: ${formattedPrompt}`);

  let browser;
  try {
    browser = await chromium.launch({
      headless: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--disable-blink-features=AutomationControlled'
      ]
    });

    const context = await browser.newContext({
      viewport: { width: 1024, height: 768 },
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
    });

    const page = await context.newPage();

    // Stealth script to hide Playwright automation traces from Google
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
      window.chrome = window.chrome || { runtime: {} };
    });

    // Inject Google Gemini session cookies
    if (GOOGLE_COOKIES_JSON) {
      try {
        const parsedCookies = JSON.parse(GOOGLE_COOKIES_JSON);
        const formattedCookies = parsedCookies.map(c => ({
          name: c.name,
          value: c.value,
          domain: c.domain || '.google.com',
          path: c.path || '/',
          secure: c.secure !== false,
          httpOnly: c.httpOnly !== false,
          sameSite: c.sameSite || 'None'
        }));
        await context.addCookies(formattedCookies);
        console.log(`[Gemini Render] ${formattedCookies.length} cookies injected from GOOGLE_COOKIES_JSON.`);
      } catch (e) {
        console.error('[Gemini Render] Error parsing GOOGLE_COOKIES_JSON:', e.message);
      }
    } else if (SECURE_1PSID) {
      await context.addCookies([
        { name: '__Secure-1PSID', value: SECURE_1PSID, domain: '.google.com', path: '/', secure: true, httpOnly: true, sameSite: 'None' },
        { name: '__Secure-1PSIDTS', value: SECURE_1PSIDTS, domain: '.google.com', path: '/', secure: true, httpOnly: true, sameSite: 'None' }
      ]);
    } else {
      console.warn('[Gemini Render] Warning: No Google cookies configured!');
    }

    console.log('[Gemini Render] Navigating to Gemini with fast commit strategy...');
    await page.goto('https://gemini.google.com/app', { waitUntil: 'commit', timeout: 35000 });

    // Selector for Gemini prompt input box
    const inputSel = 'rich-textarea p, div[contenteditable="true"], p[data-placeholder]';
    console.log('[Gemini Render] Waiting for prompt input box...');
    try {
      await page.waitForSelector(inputSel, { timeout: 30000 });
    } catch (e) {
      const pageText = await page.content();
      const currentUrl = page.url();
      if (pageText.includes('Sign in') || currentUrl.includes('accounts.google.com')) {
        console.error('[Gemini Render] Google session verification required / Bot detected.');
        const err = new Error('Google session verification required.');
        err.statusCode = 401;
        throw err;
      }
      const err = new Error(`Timeout waiting for Gemini prompt box. (Current URL: ${currentUrl})`);
      err.statusCode = 504;
      throw err;
    }

    await page.click(inputSel);
    await page.fill(inputSel, formattedPrompt);
    await page.waitForTimeout(1000);

    // Trigger send via explicit Send button click or Enter key
    const sendBtnSel = 'button[aria-label*="Send message"], button[aria-label*="Send"], button.send-button, send-button';
    const sendBtn = await page.$(sendBtnSel);
    if (sendBtn && await sendBtn.isEnabled()) {
      console.log('[Gemini Render] Clicking Send button...');
      await sendBtn.click();
    } else {
      console.log('[Gemini Render] Pressing Enter key...');
      await page.keyboard.press('Enter');
    }

    console.log('[Gemini Render] Prompt sent. Watching for image output...');

    let imageFound = false;
    const startTime = Date.now();
    let generationStarted = false;

    while ((Date.now() - startTime) < 55000) {
      // Check if stop response button is present (generation in progress)
      const stopBtn = await page.$('button[aria-label*="Stop response"], button[aria-label*="Stop generation"], button.stop-button');
      if (stopBtn) {
        generationStarted = true;
      }

      const hasTargetImg = await page.evaluate(() => {
        const imgs = Array.from(document.querySelectorAll('img'));
        return imgs.some(img => {
          const src = img.src || '';
          const isBlobOrGen = src.startsWith('blob:') || src.includes('/gg/') || src.includes('googleusercontent.com');
          const isNotAvatar = !src.includes('s32-') && !src.includes('s64-') && !src.includes('s96-') && !src.includes('/a/') && !src.includes('avatar') && !src.includes('profile');
          return isBlobOrGen && isNotAvatar && (img.naturalWidth > 200 || img.clientWidth > 200);
        });
      });

      if (hasTargetImg) {
        imageFound = true;
        break;
      }

      // Smart early exit: if generation started and completed without an image
      if (generationStarted && !stopBtn) {
        console.log('[Gemini Render] Response completed without an image element.');
        break;
      }

      await page.waitForTimeout(2000);
    }

    if (!imageFound) {
      const textDump = await page.innerText('body').catch(() => '');
      console.log(`❌ [Gemini Actual Output]:\n${textDump.slice(-400)}`);
      await browser.close();
      browser = null;
      const err = new Error(`Gemini did not generate an image. Check Render logs for output dump.`);
      err.statusCode = 422;
      throw err;
    }

    console.log('[Gemini Render] Extracting pure image data via HTML5 Canvas (No UI)...');

    const base64Image = await page.evaluate(async () => {
      const imgs = Array.from(document.querySelectorAll('img'));
      const targetImg = imgs.find(img => {
        const src = img.src || '';
        const isBlobOrGen = src.startsWith('blob:') || src.includes('/gg/') || src.includes('googleusercontent.com');
        const isNotAvatar = !src.includes('s32-') && !src.includes('s64-') && !src.includes('s96-') && !src.includes('/a/') && !src.includes('avatar') && !src.includes('profile');
        return isBlobOrGen && isNotAvatar && (img.naturalWidth > 200 || img.clientWidth > 200);
      });

      if (!targetImg) return null;

      // Draw pure image directly to HTML5 canvas and export base64
      try {
        const canvas = document.createElement('canvas');
        canvas.width = targetImg.naturalWidth || targetImg.clientWidth || 1024;
        canvas.height = targetImg.naturalHeight || targetImg.clientHeight || 1024;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(targetImg, 0, 0);
        return canvas.toDataURL('image/png');
      } catch (canvasErr) {
        // Fallback: If canvas is tainted or errors out, fetch blob directly
        const res = await fetch(targetImg.src);
        const blob = await res.blob();
        return new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onloadend = () => resolve(reader.result);
          reader.onerror = reject;
          reader.readAsDataURL(blob);
        });
      }
    });

    await browser.close();
    browser = null;

    if (!base64Image) {
      const err = new Error(`Failed to extract canvas base64 image data.`);
      err.statusCode = 500;
      throw err;
    }

    console.log('[Gemini Render] Uploading pure image base64 to Cloudinary...');
    let finalCDNUrl;

    if (CLOUDINARY_CLOUD_NAME && CLOUDINARY_API_KEY && CLOUDINARY_API_SECRET) {
      const uploadRes = await cloudinary.uploader.upload(base64Image, {
        folder: 'finonest_car_loans'
      });
      finalCDNUrl = uploadRes.secure_url;
      console.log('[Gemini Render] Cloudinary upload successful:', finalCDNUrl);
    } else {
      console.warn('[Gemini Render] Cloudinary keys not found. Returning base64 URI.');
      finalCDNUrl = base64Image;
    }

    return {
      status: 'success',
      success: true,
      aspect_ratio: '1:1',
      image_url: finalCDNUrl
    };

  } finally {
    if (browser) {
      try { await browser.close(); } catch (_) {}
    }
  }
}

// 3. Generate Image Route with Strict 120-Second Hard Timeout
app.post('/generate-image', async (req, res) => {
  const { prompt } = req.body;
  if (!prompt || typeof prompt !== 'string') {
    return res.status(400).json({ success: false, error: 'Prompt string is required' });
  }

  // 120-second hard timeout wrapper to ensure Cloudinary upload completes & returns JSON to n8n
  const timeoutPromise = new Promise((_, reject) => {
    setTimeout(() => {
      const err = new Error('Operation timed out after 120 seconds.');
      err.statusCode = 504;
      reject(err);
    }, 120000);
  });

  try {
    const result = await Promise.race([runAutomation(prompt), timeoutPromise]);
    return res.json(result);
  } catch (err) {
    console.error('[Gemini Render Error]:', err.message);
    const statusCode = err.statusCode || 500;
    return res.status(statusCode).json({
      success: false,
      status: 'error',
      detail: err.message,
      error: err.message
    });
  }
});

app.listen(PORT, () => {
  console.log(`Gemini Render Microservice listening on port ${PORT}`);
});
