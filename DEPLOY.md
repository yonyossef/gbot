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
| `GOOGLE_CREDENTIALS_JSON` | Full Service Account JSON as a single line (reuse from a1/a4) |
| `SHEET_KEY` | `1YJX-BQhF2CTZvbpA5XWDdmjXpFhllUQeNPm6OjUXMrU` (gbot sheet) |
| `SHEET_NAME` | `Low` (worksheet tab name) |

**gbot sheet:** [docs.google.com/spreadsheets/d/1YJX-BQhF2CTZvbpA5XWDdmjXpFhllUQeNPm6OjUXMrU](https://docs.google.com/spreadsheets/d/1YJX-BQhF2CTZvbpA5XWDdmjXpFhllUQeNPm6OjUXMrU/edit)

**Tip for GOOGLE_CREDENTIALS_JSON:** Reuse service account from a1/a4. Minify with:
```bash
python -c "import json; print(json.dumps(json.load(open('/home/yonyossef/a4/service_account.json'))))"
```

**Share the gbot sheet** with the service account email (from `client_email` in the JSON) as **Editor**.

**Sheet columns:** Timestamp | Item Name | Quantity | Status | Sender Phone | Supplier (add if missing).

**Note (Railway):** Items DB (`data/items.json`) is file-based. On Railway, the filesystem is ephemeral—items reset on redeploy. For production, consider Redis or a database.

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

---

## Local test chat

Open **http://localhost:8000/test** for a WhatsApp-style chat that posts to the real `/whatsapp` webhook. Useful for testing without Twilio.
