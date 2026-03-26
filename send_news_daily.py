#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
send_news_daily.py (updated)
- Robust NewsAPI JSON parsing (fallback to utf-8 decode with replacement)
- Simple dedupe by URL and normalized title
- Robust TO_EMAILS parsing (comma / semicolon / whitespace)
- Timezone-aware datetime usage
"""
from datetime import datetime, timezone
import os
import sys
import logging
import json
import time
import re
from urllib.parse import quote_plus

import requests
import feedparser
from dotenv import load_dotenv

load_dotenv()

# === Config (from env) ===
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "").strip() or None
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "").strip() or None

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER or "")
# Robust parsing of TO_EMAILS: allow comma, semicolon, whitespace
_raw_to = os.getenv("TO_EMAILS", "")
TO_EMAILS = [e.strip() for e in re.split(r"[,;\s]+", _raw_to) if e.strip()]

SUBJECT_PREFIX = os.getenv("SUBJECT_PREFIX", "[Daily News]")

TOP_K = int(os.getenv("TOP_K", "5"))
MAX_FETCH = int(os.getenv("MAX_FETCH", "20"))  # per source
USER_AGENT = "DailyNewsEmailer/1.0"

QUERIES = {
    "International": 'world OR international OR geopolitics OR "global news"',
    "AI": 'artificial intelligence OR AI OR "machine learning" OR "deep learning"',
    "Entertainment": 'entertainment OR celebrity OR film OR movie OR music OR tv OR show'
}

# Logging
logger = logging.getLogger("daily_news")
logger.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
h = logging.StreamHandler(sys.stdout)
h.setFormatter(fmt)
logger.addHandler(h)

# --- Helpers: fetchers ---
def fetch_newsapi(query, api_key, page_size=20):
    url = "https://newsapi.org/v2/everything"
    params = {"q": query, "pageSize": page_size, "sortBy": "publishedAt", "language": "en"}
    headers = {"Authorization": api_key}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=20)
    except Exception as e:
        logger.warning("NewsAPI request error: %s", e)
        raise

    # try normal json first, fallback to forced utf-8 decode with replacement
    try:
        data = r.json()
    except Exception:
        try:
            text = r.content.decode("utf-8", errors="replace")
            data = json.loads(text)
        except Exception:
            # include some diagnostic info but don't expose secrets
            logger.debug("NewsAPI raw content (truncated): %s", r.content[:500])
            r.raise_for_status()
            raise
    articles = data.get("articles", [])
    out = []
    for a in articles:
        out.append({
            "title": a.get("title"),
            "description": a.get("description") or "",
            "url": a.get("url"),
            "source": a.get("source", {}).get("name"),
            "publishedAt": a.get("publishedAt"),
            "content": a.get("content") or ""
        })
    return out

def fetch_google_news_rss(query, max_items=20):
    q = quote_plus(query + " when:7d")
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(url)
    items = []
    for entry in feed.entries[:max_items]:
        items.append({
            "title": entry.get("title"),
            "description": entry.get("summary") or "",
            "url": entry.get("link"),
            "source": entry.get("source", {}).get("title") if entry.get("source") else None,
            "publishedAt": entry.get("published"),
            "content": entry.get("summary") or ""
        })
    return items

# --- Utilities ---
def normalize_title(t):
    if not t:
        return ""
    t = t.lower().strip()
    # remove punctuation
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t

def unique_by_url_and_title(items):
    seen_urls = set()
    seen_titles = set()
    out = []
    for it in items:
        url = (it.get("url") or "").strip()
        title_norm = normalize_title(it.get("title") or "")
        if url and url in seen_urls:
            continue
        if title_norm and title_norm in seen_titles:
            continue
        if url:
            seen_urls.add(url)
        if title_norm:
            seen_titles.add(title_norm)
        out.append(it)
    return out

def parse_time(x):
    if not x:
        return None
    # Try ISO format
    try:
        return datetime.fromisoformat(x.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        pass
    # feedparser-style
    try:
        t = feedparser._parse_date(x)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    except Exception:
        pass
    return None

# --- Compose email ---
def build_email_html(all_sections):
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = []
    html.append(f"<h2>Daily Top {TOP_K} — Generated: {generated}</h2>")
    for title, items in all_sections:
        html.append(f"<h3>{title}</h3>")
        if not items:
            html.append("<p><em>No items found.</em></p>")
            continue
        html.append("<ol>")
        for it in items:
            t = it.get("title") or "(No title)"
            src = it.get("source") or ""
            pub = it.get("publishedAt") or ""
            desc = it.get("description") or ""
            url = it.get("url") or "#"
            html.append(
                f"<li><a href=\"{url}\">{t}</a><br>"
                f"<small>{src} • {pub}</small>"
                f"<div style='margin-top:4px'>{desc}</div>"
                f"</li>"
            )
        html.append("</ol>")
    html.append("<hr><small>Delivered by Daily News Emailer</small>")
    return "\n".join(html)

# --- Send via SMTP ---
def send_via_smtp(subject, html_body, from_email, to_emails):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    if not to_emails:
        logger.error("No recipient addresses configured.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    # header should be comma-separated
    msg["To"] = ", ".join(to_emails)
    part = MIMEText(html_body, "html", "utf-8")
    msg.attach(part)

    logger.info("Connecting to SMTP %s:%s", SMTP_SERVER, SMTP_PORT)
    server = None
    try:
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30)
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30)
            server.ehlo()
            if SMTP_PORT in (587, 25):
                server.starttls()
                server.ehlo()
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
        # pass the list of recipient addresses to sendmail
        server.sendmail(from_email, to_emails, msg.as_string())
        logger.info("Email sent to %s", ", ".join(to_emails))
    finally:
        if server:
            server.quit()

# --- Main pipeline ---
def fetch_top_for_category(category_name, query, top_k=5):
    items = []
    # Prefer NewsAPI if available
    if NEWSAPI_KEY:
        try:
            items += fetch_newsapi(query, NEWSAPI_KEY, page_size=MAX_FETCH)
            logger.info("Fetched %d items from NewsAPI for %s", len(items), category_name)
        except Exception as e:
            logger.warning("NewsAPI fetch failed for %s: %s", category_name, e)

    # Fallback to Google News RSS
    try:
        rss_items = fetch_google_news_rss(query, max_items=MAX_FETCH)
        if rss_items:
            # if items already had NewsAPI results, append rss_items
            items += rss_items
            logger.info("Fetched %d items from Google RSS for %s", len(rss_items), category_name)
    except Exception as e:
        logger.warning("Google RSS fetch failed for %s: %s", category_name, e)

    # normalize and dedupe
    for it in items:
        it["parsed_time"] = parse_time(it.get("publishedAt") or "") or datetime.min.replace(tzinfo=timezone.utc)
    # sort by time (newest first)
    items = sorted(items, key=lambda a: a.get("parsed_time"), reverse=True)
    # simple dedupe by URL and normalized title
    items = unique_by_url_and_title(items)
    top = items[:top_k]
    # remove internal parsed_time before return
    for it in top:
        it.pop("parsed_time", None)
    return top

def main():
    if not TO_EMAILS:
        logger.error("No TO_EMAILS configured. Set TO_EMAILS in environment or .env (comma/semicolon-separated).")
        return

    sections = []
    for cat, q in QUERIES.items():
        logger.info("Fetching for %s ...", cat)
        top = fetch_top_for_category(cat, q, top_k=TOP_K)
        logger.info("Got %d items for %s", len(top), cat)
        sections.append((cat, top))

    html = build_email_html(sections)
    subject = f"{SUBJECT_PREFIX} {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"

    try:
        if SENDGRID_API_KEY:
            logger.info("SENDGRID_API_KEY set but SendGrid sending not implemented in this script. Using SMTP fallback.")
        logger.info("Sending email via SMTP %s:%s ...", SMTP_SERVER, SMTP_PORT)
        send_via_smtp(subject, html, FROM_EMAIL, TO_EMAILS)
    except Exception as e:
        logger.exception("Failed to send email: %s", e)

if __name__ == "__main__":
    main()
