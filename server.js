const express = require('express');
const { chromium } = require('playwright');
const cloudinary = require('cloudinary').v2;
const http = require('http');
const https = require('https');

const app = express();
app.use(express.json());

const PORT = process.env.PORT || 3000;
const RENDER_EXTERNAL_URL = process.env.RENDER_EXTERNAL_URL || `http://localhost:${PORT}`;

// Configure Cloudinary from Environment Variables
cloudinary.config({
  cloud_name: process.env.CLOUDINARY_CLOUD_NAME || '',
  api_key: process.env.CLOUDINARY_API_KEY || '',
  api_secret: process.env.CLOUDINARY_API_SECRET || '',
  secure: true
});

// Read Google cookies from Render Environment Variables
const SECURE_1PSID = process.env.SECURE_1PSID || '';
const SECURE_1PSIDTS = process.env.SECURE_1PSIDTS || '';

// 1. Health check API endpoint
app.get('/health', (req, res) => {
  res.status(200).json({ status: 'ok', uptime: process.uptime(), timestamp: new Date().toISOString() });
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
    console.log(`[Gemini Render] Processing 1:1 prompt: "${formattedPrompt}"`);

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
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
    });

    const page = await context.newPage();

    // Stealth script to hide Playwright automation traces from Google
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
      window.chrome = window.chrome || { runtime: {} };
    });

    // Inject Google Gemini session cookies
    const GOOGLE_COOKIES_JSON = process.env.GOOGLE_COOKIES_JSON || '';
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
      const cookies = [
        {
          name: '__Secure-1PSID',
          value: SECURE_1PSID,
          domain: '.google.com',
          path: '/',
          secure: true,
          httpOnly: true,
          sameSite: 'None'
        },
        {
          name: '__Secure-3PSID',
          value: process.env.SECURE_3PSID || SECURE_1PSID,
          domain: '.google.com',
          path: '/',
          secure: true,
          httpOnly: true,
          sameSite: 'None'
        },
        {
          name: 'SID',
          value: SECURE_1PSID,
          domain: '.google.com',
          path: '/',
          secure: true,
          httpOnly: false,
          sameSite: 'None'
        }
      ];

      if (SECURE_1PSIDTS) {
        cookies.push({
          name: '__Secure-1PSIDTS',
          value: SECURE_1PSIDTS,
          domain: '.google.com',
          path: '/',
          secure: true,
          httpOnly: true,
          sameSite: 'None'
        });
        cookies.push({
          name: '__Secure-3PSIDTS',
          value: process.env.SECURE_3PSIDTS || SECURE_1PSIDTS,
          domain: '.google.com',
          path: '/',
          secure: true,
          httpOnly: true,
          sameSite: 'None'
        });
      }

      await context.addCookies(cookies);
      console.log(`[Gemini Render] ${cookies.length} Google cookies injected successfully.`);
    } else {
      console.warn('[Gemini Render] Warning: SECURE_1PSID environment variable is not set!');
    }

    console.log('[Gemini Render] Navigating to Gemini...');
    await page.goto('https://gemini.google.com/app', { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(3000);

    // Dismiss potential onboarding popups or "Got it" dialogs
    const popupSelectors = [
      'button:has-text("Got it")',
      'button:has-text("I agree")',
      'button:has-text("Continue")',
      'button:has-text("Dismiss")',
      '[aria-label*="Close"]'
    ];
    for (const popSel of popupSelectors) {
      try {
        const btn = await page.$(popSel);
        if (btn) {
          await btn.click();
          console.log(`[Gemini Render] Clicked onboarding popup: ${popSel}`);
          await page.waitForTimeout(1000);
        }
      } catch (_) {}
    }

    // Check if Gemini is showing an unauthenticated landing page with "Sign in"
    const signInBtn = await page.$('a[href*="accounts.google.com"], button:has-text("Sign in"), a:has-text("Sign in")');
    if (signInBtn) {
      console.error('[Gemini Render] Gemini page displays "Sign in" button. Cookies are missing or invalid.');
      throw new Error('Google Gemini is asking to "Sign in". Your SECURE_1PSID cookie in Render Environment Variables is missing or invalid. Please update SECURE_1PSID in Render.');
    }

    const promptSelectors = [
      'div[role="textbox"]',
      'div[contenteditable="true"]',
      'rich-textarea div[contenteditable="true"]',
      'rich-textarea',
      '[aria-label*="Enter a prompt"]',
      '[aria-label*="Ask Gemini"]',
      'textarea',
      'p[data-placeholder]'
    ];

    let promptInput = null;
    for (const selector of promptSelectors) {
      try {
        await page.waitForSelector(selector, { timeout: 8000 });
        promptInput = selector;
        console.log(`[Gemini Render] Found prompt input selector: "${selector}"`);
        break;
      } catch (e) {}
    }

    if (!promptInput) {
      const currentUrl = page.url();
      console.error(`[Gemini Render] Prompt input not found. Current page URL: ${currentUrl}`);
      if (currentUrl.includes('accounts.google.com') || currentUrl.includes('signin')) {
        throw new Error('Google redirected to Sign-In page. Your SECURE_1PSID cookie in Render Environment Variables is EXPIRED or INVALID. Please copy a fresh __Secure-1PSID cookie from Chrome.');
      }
      throw new Error(`Could not find Gemini prompt input field (Current URL: ${currentUrl}). Ensure SECURE_1PSID cookie is set in Render Environment Variables.`);
    }

    await page.click(promptInput);
    await page.fill(promptInput, formattedPrompt);
    await page.waitForTimeout(500);
    await page.keyboard.press('Enter');

    try {
      const sendBtn = await page.$('button[aria-label*="Send"], button.send-button');
      if (sendBtn) await sendBtn.click();
    } catch (_) {}

    console.log('[Gemini Render] Prompt submitted. Waiting for Imagen 3 output...');

    const imgSelector = 'img[src*="googleusercontent.com"]';
    await page.waitForSelector(imgSelector, { timeout: 70000 });
    await page.waitForTimeout(1500);

    const images = await page.$$eval(imgSelector, imgs => 
      imgs.map(img => img.src).filter(src => src && src.includes('googleusercontent.com') && !src.includes('s64-') && !src.includes('s32-'))
    );

    if (!images || images.length === 0) {
      throw new Error('No generated image URL found.');
    }

    const geminiRawUrl = images[images.length - 1];
    console.log('[Gemini Render] Extracted Gemini Image URL:', geminiRawUrl);

    let finalCDNUrl = geminiRawUrl;

    // Check if Cloudinary credentials are provided
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
    } else {
      console.log('[Gemini Render] Cloudinary env variables not set. Returning raw Google CDN link.');
    }

    await browser.close();
    return res.json({ 
      success: true, 
      image_url: finalCDNUrl,
      raw_google_url: geminiRawUrl,
      aspect_ratio: "1:1"
    });

  } catch (err) {
    console.error('[Gemini Render] Error:', err.message);
    if (browser) {
      try { await browser.close(); } catch (_) {}
    }
    return res.status(500).json({ success: false, error: err.message });
  }
});

app.listen(PORT, () => {
  console.log(`Gemini Render Microservice listening on port ${PORT}`);
});
