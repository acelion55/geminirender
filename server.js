const express = require('express');
const { chromium } = require('playwright');

const app = express();
app.use(express.json());

const PORT = process.env.PORT || 3000;

// Read cookies from Render environment variables
const SECURE_1PSID = process.env.SECURE_1PSID || '';
const SECURE_1PSIDTS = process.env.SECURE_1PSIDTS || '';

app.get('/health', (req, res) => {
  res.status(200).send('OK');
});

app.post('/generate-image', async (req, res) => {
  const { prompt } = req.body;
  if (!prompt || typeof prompt !== 'string') {
    return res.status(400).json({ success: false, error: 'Prompt string is required' });
  }

  let browser;
  try {
    console.log(`[Gemini Render] Processing prompt: "${prompt}"`);

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
      viewport: { width: 1280, height: 800 }
    });

    // Inject Google Gemini session cookies
    if (SECURE_1PSID) {
      const cookies = [
        {
          name: '__Secure-1PSID',
          value: SECURE_1PSID,
          domain: '.google.com',
          path: '/',
          secure: true,
          httpOnly: true
        }
      ];

      if (SECURE_1PSIDTS) {
        cookies.push({
          name: '__Secure-1PSIDTS',
          value: SECURE_1PSIDTS,
          domain: '.google.com',
          path: '/',
          secure: true,
          httpOnly: true
        });
      }

      await context.addCookies(cookies);
      console.log('[Gemini Render] Cookies injected successfully.');
    } else {
      console.warn('[Gemini Render] Warning: SECURE_1PSID environment variable is not set!');
    }

    const page = await context.newPage();
    console.log('[Gemini Render] Navigating to Gemini...');
    await page.goto('https://gemini.google.com/app', { waitUntil: 'domcontentloaded', timeout: 35000 });

    // Selector strategy for Gemini input box
    const promptSelectors = [
      'div[contenteditable="true"]',
      'rich-textarea div[contenteditable="true"]',
      'textarea',
      'p[data-placeholder]'
    ];

    let promptInput = null;
    for (const selector of promptSelectors) {
      try {
        await page.waitForSelector(selector, { timeout: 8000 });
        promptInput = selector;
        break;
      } catch (e) {
        // try next
      }
    }

    if (!promptInput) {
      throw new Error('Could not find Gemini prompt input field. Ensure SECURE_1PSID cookie is valid.');
    }

    await page.click(promptInput);
    await page.fill(promptInput, `Generate a photorealistic commercial marketing banner: ${prompt}`);
    await page.waitForTimeout(500);
    await page.keyboard.press('Enter');

    // Optional click fallback on send button
    try {
      const sendBtn = await page.$('button[aria-label*="Send"], button.send-button');
      if (sendBtn) await sendBtn.click();
    } catch (_) {}

    console.log('[Gemini Render] Prompt submitted. Waiting for Imagen 3 output...');

    const imgSelector = 'img[src*="googleusercontent.com"]';

    // Wait for output image
    await page.waitForSelector(imgSelector, { timeout: 70000 });
    await page.waitForTimeout(1500);

    const images = await page.$$eval(imgSelector, imgs => 
      imgs.map(img => img.src).filter(src => src && src.includes('googleusercontent.com'))
    );

    if (!images || images.length === 0) {
      throw new Error('No generated image URL found.');
    }

    const latestImage = images[images.length - 1];
    console.log('[Gemini Render] Successfully extracted image:', latestImage);

    await browser.close();
    return res.json({ success: true, imageUrl: latestImage, allImages: images });

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
