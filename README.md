Daily News Emailer

Fetches and sends the top 5 news items daily (International, AI, Entertainment).
It supports two execution modes:
1. Scheduled via GitHub Actions (recommended if you want automated daily delivery without keeping a machine running).
2. Manual / one-off runs by invoking the Python script locally (useful for testing).

Usage instructions, environment variables, and how to schedule runs with GitHub Actions are described below.

For Local run:
1. Create a virtual environment and install dependencies:
   - python3 -m venv venv
   - source venv/bin/activate
   - pip install requests feedparser python-dotenv

2. Prepare a .env file (use .env.example as a reference) and place it in the project root.

3. Run:
   - python send_news_daily.py

Scheduled runs with GitHub Actions
This repository includes .github/workflows/daily.yml so the job can run automatically every day. You must add the following Secrets in the repository Settings → Secrets and variables → Actions:

- NEWSAPI_KEY (optional)
- SENDGRID_API_KEY or SMTP_USER, SMTP_PASSWORD, SMTP_SERVER, SMTP_PORT
- FROM_EMAIL
- TO_EMAILS (comma-separated)
- SUBJECT_PREFIX (optional)

Adjust the workflow cron expression to match your desired trigger time (note: GitHub Actions cron uses UTC).
