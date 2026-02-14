# Deploy Shop Assistant Bot to Railway

## Step 1: Push to a Git repo

Create a new repository on GitHub (or GitLab) and push:

```bash
# Add your remote (replace with your repo URL)
git remote add origin https://github.com/YOUR_USERNAME/shop-assistant-bot.git

# Push
git push -u origin main
```

## Step 2: Create Railway project

1. Go to [railway.app](https://railway.app) and sign in (GitHub/GitLab)
2. Click **New Project** → **Deploy from GitHub repo**
3. Select your repository and connect it
4. Railway will auto-detect the `Procfile` and start the build

## Step 3: Set environment variables

In your Railway project → **Variables** tab, add:

| Variable | Value |
|----------|-------|
| `TWILIO_AUTH_TOKEN` | Your Twilio Auth Token from [console.twilio.com](https://console.twilio.com) |
| `GOOGLE_CREDENTIALS_JSON` | Full Service Account JSON as a single line (minify your `key.json`) |
| `SHEET_KEY` | Google Sheet ID from the URL: `https://docs.google.com/spreadsheets/d/SHEET_KEY/edit` |

**Tip for GOOGLE_CREDENTIALS_JSON:** Minify with:
```bash
python -c "import json; print(json.dumps(json.load(open('path/to/key.json'))))"
```

## Step 4: Get your webhook URL

1. In Railway, open your service → **Settings** → **Networking**
2. Click **Generate Domain** to get a public URL (e.g. `https://your-app.up.railway.app`)
3. In Twilio Console → WhatsApp Sandbox (or your number) → set webhook to:
   ```
   https://your-app.up.railway.app/whatsapp
   ```
4. Method: **POST**

## Step 5: Configure Twilio WhatsApp

1. Go to [Twilio Console](https://console.twilio.com) → Messaging → Try it out → Send a WhatsApp message
2. Set the webhook URL for "When a message comes in" to your Railway URL + `/whatsapp`

---

**Verify:** Send "Low Milk" to your WhatsApp sandbox number. You should get a confirmation and see a new row in your Google Sheet.
