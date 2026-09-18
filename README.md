# Gemini Render Microservice (Playwright + Docker)

Complete production setup to run a headful/headless Chromium instance on **Render.com** (using Playwright's official Docker container) to generate images on Google Gemini and send direct CDN links (`googleusercontent.com`) to **n8n**.

---

## 📁 Repository Structure

```text
gemini-render-service/
├── Dockerfile        # Official Playwright Ubuntu Jammy container setup
├── package.json      # Dependencies
├── server.js         # Express app + Cookie injection + Gemini Playwright logic
└── .dockerignore     # Docker build excludes
```

---

## 🚀 Step 1: Push Code to GitHub

Execute in your local project folder:

```bash
git init
git add .
git commit -m "Deploy Gemini Playwright Microservice to Render"
git branch -M main
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/gemini-render-service.git
git push -u origin main
```

---

## 🌐 Step 2: Deploy on Render.com

1. Login to **[dashboard.render.com](https://dashboard.render.com)**.
2. Click **New +** > **Web Service**.
3. Connect your GitHub Repository `gemini-render-service`.
4. Configure service settings:
   - **Name**: `gemini-render-service`
   - **Environment**: `Docker` (Render auto-detects `Dockerfile`)
   - **Region**: Choose nearest region (e.g. Frankfurt / Singapore / Oregon)
   - **Instance Type**: Starter / Free
5. Scroll to **Environment Variables** and add:
   - `SECURE_1PSID`: *(Value copied from Chrome Developer Tools > Application > Cookies for gemini.google.com)*
   - `SECURE_1PSIDTS`: *(Value copied from Chrome Developer Tools > Application > Cookies)*
6. Click **Create Web Service**.

Once deployed, Render provides a URL (e.g., `https://gemini-render-service.onrender.com`).

---

## ⚡ Step 3: Connect to n8n

In your **n8n Workflow**, configure an **HTTP Request Node**:

- **Method**: `POST`
- **URL**: `https://gemini-render-service.onrender.com/generate-image`
- **Headers**:
  - `Content-Type`: `application/json`
- **Body Content Type**: `JSON`
- **Body**:
```json
{
  "prompt": "={{ $json.image_prompt || 'A modern car loan promotional marketing banner' }}"
}
```

---

## 🧪 Response Format

```json
{
  "success": true,
  "imageUrl": "https://lh3.googleusercontent.com/gg/...",
  "allImages": [
    "https://lh3.googleusercontent.com/gg/..."
  ]
}
```
