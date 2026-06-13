# Tearsheet Bot

Telegram bot that looks up a company, scrapes FiinGate / Vietstock,
structures the data with Claude, and sends back a PDF tearsheet.

---

## Setup in 5 steps

### 1. Get a Telegram Bot Token
1. Open Telegram, message **@BotFather**
2. Send `/newbot`, follow prompts, copy the token
3. Message your new bot once (so it has your chat ID)
4. To find your chat ID: message **@userinfobot**

### 2. Get your Anthropic API key
Go to https://console.anthropic.com → API Keys → Create key

### 3. Deploy to Railway (free tier available)
1. Create account at https://railway.app
2. New Project → Deploy from GitHub (push this folder first)
   — or — New Project → Empty → add this code via CLI
3. Add environment variables (Settings → Variables):
   ```
   TELEGRAM_TOKEN=...
   ANTHROPIC_API_KEY=...
   FIINGATE_EMAIL=...
   FIINGATE_PASSWORD=...
   ALLOWED_CHAT_IDS=your_chat_id   ← get from @userinfobot
   USD_VND_RATE=26500
   ```
4. Railway auto-detects Python and runs `Procfile`

### 4. Install Playwright browser on the server
Add a **start command** in Railway settings:
```
playwright install chromium --with-deps && python bot.py
```

### 5. Test it
Send your bot: `Kingfoodmart`

---

## Local development

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Copy and fill in env vars
cp .env.example .env
# edit .env with your values

# Run
export $(cat .env | xargs)
python bot.py
```

---

## How it works

```
You (Telegram) → bot.py
                    ↓
              lookup.py
              ├── Web search MST (tax code) via masothue.com
              ├── scraper.py → FiinGate (private) or Vietstock (public)
              │               headless Playwright browser
              ├── claude_client.py → Claude API structures raw text → JSON
              └── pdf_gen.py → ReportLab → tearsheet PDF
                    ↓
              PDF sent back to you on Telegram
```

---

## Commands
| Message | Action |
|---------|--------|
| `Kingfoodmart` | private company → FiinGate |
| `MSN public` | public company → Vietstock |
| `Masan private` | force FiinGate |
| `/start` or `/help` | show usage |

---

## Notes
- FiinGate requires you to be logged in — bot uses your credentials
  from env vars and saves the session cookie to avoid re-logging in every time
- All figures converted to USDm at the rate in `USD_VND_RATE`
- Financials are unaudited tax filings from FiinGate unless otherwise noted
- Set `ALLOWED_CHAT_IDS` to your Telegram chat ID to keep the bot private
