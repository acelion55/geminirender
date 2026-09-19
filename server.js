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
cloudinary.config({
  cloud_name: process.env.CLOUDINARY_CLOUD_NAME || '',
  api_key: process.env.CLOUDINARY_API_KEY || '',
  api_secret: process.env.CLOUDINARY_API_SECRET || '',
  secure: true
});

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

// 3. Generate Image & Upload to Cloudinary API
app.post('/generate-image', async (req, res) => {
  const { prompt } = req.body;
  if (!prompt || typeof prompt !== 'string') {
    return res.status(400).json({ success: false, error: 'Prompt string is required' });
  }

  // Force 1:1 square aspect ratio
  const formattedPrompt = `Create an image in 1:1 square aspect ratio of: ${prompt}`;

  let browser;
  try {
    console.log(`🚀 Processing 1:1 prompt: "${formattedPrompt}"`);

    browser = await chromium.launch({
      headless: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-blink-features=AutomationControlled'
      ]
    });

    const context = await browser.newContext({
      viewport: { width: 1280, height: 800 },
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

    console.log('[Gemini Render] Navigating to Gemini with domcontentloaded...');
    await page.goto('https://gemini.google.com/app', { waitUntil: 'domcontentloaded', timeout: 45000 });

    // Selector for Gemini prompt input box
    const inputSel = 'rich-textarea p, div[contenteditable="true"]';
    try {
      await page.waitForSelector(inputSel, { timeout: 30000 });
    } catch (e) {
      const pageText = await page.content();
      const currentUrl = page.url();
      if (pageText.includes('Sign in') || currentUrl.includes('accounts.google.com')) {
        console.error('[Gemini Render] Google session verification required / Bot detected.');
        throw new Error('Google session verification required.');
      }
      throw new Error(`Timeout waiting for Gemini prompt box. (Current URL: ${currentUrl})`);
    }

    await page.click(inputSel);
    await page.fill(inputSel, formattedPrompt);
    await page.keyboard.press('Enter');

    console.log('[Gemini Render] Prompt submitted. Waiting for Imagen 3 output...');

    const startTime = Date.now();
    let geminiRawUrl = null;

    while ((Date.now() - startTime) < 75000) {
      const elements = await page.$$('img');
      for (const elem of elements) {
        const src = await elem.getAttribute('src');
        if (src) {
          const isAvatar = src.includes('/a/') || ['s32-', 's64-', 's96-', 's128-', 's192-', 's256-'].some(dim => src.includes(dim)) || src.includes('avatar') || src.includes('profile');
          const isGeneratedImg = (src.includes('googleusercontent.com') || src.includes('/gg/') || src.includes('generativeai') || src.startsWith('blob:')) && !isAvatar;
          
          if (isGeneratedImg) {
            geminiRawUrl = src;
            console.log('[Gemini Render] Found matching generated image URL:', src);
            break;
          }
        }
      }
      if (geminiRawUrl) break;
      await page.waitForTimeout(2500);
    }

    if (!geminiRawUrl) {
      throw new Error('Gemini image generation timed out or no generated image found.');
    }

    console.log('[Gemini Render] Extracted Generated Gemini Image URL:', geminiRawUrl);

    let finalCDNUrl = geminiRawUrl;

    // Upload to Cloudinary if credentials present
    if (process.env.CLOUDINARY_CLOUD_NAME && process.env.CLOUDINARY_API_KEY && process.env.CLOUDINARY_API_SECRET) {
      try {
        console.log('[Gemini Render] Uploading generated image to Cloudinary...');
        const uploadRes = await cloudinary.uploader.upload(geminiRawUrl, {
          folder: 'finonest_car_loans',
          resource_type: 'image'
        });
        finalCDNUrl = uploadRes.secure_url;
        console.log('[Gemini Render] Uploaded to Cloudinary successfully:', finalCDNUrl);
      } catch (cloudErr) {
        console.error('[Gemini Render] Cloudinary upload error, fallback to raw URL:', cloudErr.message);
      }
    }

    await browser.close();
    return res.json({ 
      status: 'success',
      success: true, 
      aspect_ratio: '1:1',
      image_url: finalCDNUrl,
      raw_google_url: geminiRawUrl
    });

  } catch (err) {
    console.error('[Gemini Render] Error:', err.message);
    if (browser) {
      try { await browser.close(); } catch (_) {}
    }
    const statusCode = err.message.includes('session verification') ? 401 : 500;
    return res.status(statusCode).json({ success: false, status: 'error', detail: err.message, error: err.message });
  }
});

app.listen(PORT, () => {
  console.log(`Gemini Render Microservice listening on port ${PORT}`);
});
