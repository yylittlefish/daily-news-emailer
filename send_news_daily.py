#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
send_news_daily.py
每日报头：抓取三类新闻并发送 HTML 邮件
支持 NEWSAPI (若提供 API key) 或使用 Google News RSS 作为回退
支持 SMTP 或 SendGrid 发送
配置通过 .env 文件或环境变量
"""
import os
from datetime import datetime
from urllib.parse import quote_plus

import requests
import feedparser
from dotenv import load_dotenv

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

load_dotenv()

# === 配置（从环境 / .env） ===
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "").strip()  # 可选
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "").strip()  # 可选

# SMTP 配置（优先使用 SendGrid，如果提供 SENDGRID_API_KEY 可用 sendgrid）
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER or "no-reply@example.com")
TO_EMAILS = [e.strip() for e in os.getenv("TO_EMAILS", "").split(",") if e.strip()]  # 多个用逗号分隔
SUBJECT_PREFIX = os.getenv("SUBJECT_PREFIX", "[Daily News]")

TOP_K = int(os.getenv("TOP_K", "5"))
MAX_FETCH = int(os.getenv("MAX_FETCH", "20"))  # 每个源抓取的最大项数
USER_AGENT = "DailyNewsEmailer/1.0"

# 查询定义（可按需修改）
QUERIES = {
    "International": 'world OR international OR geopolitics OR "global news"',
    "AI": 'artificial intelligence OR AI OR "machine learning" OR "deep learning"',
    "Entertainment": 'entertainment OR celebrity OR film OR movie OR music OR tv OR show'
}

def fetch_newsapi(query, api_key, page_size=20):
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "pageSize": page_size,
        "sortBy": "publishedAt",
        "language": "en",
    }
    headers = {"Authorization": api_key}
    r = requests.get(url, params=params, headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json()
    articles = data.get("articles", [])
    out = []
    for a in articles:
        out.append({
            "title": a.get("title"),
            "description": a.get("description"),
            "url": a.get("url"),
            "source": a.get("source", {}).get("name"),
            "publishedAt": a.get("publishedAt"),
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
            "description": entry.get("summary"),
            "url": entry.get("link"),
            "source": entry.get("source", {}).get("title") if entry.get("source") else None,
            "publishedAt": entry.get("published"),
        })
    return items

def unique_by_title(articles):
    seen = set()
    out = []
    for a in articles:
        t = (a.get("title") or "").strip()
        if not t:
            continue
        if t in seen:
            continue
        seen.add(t)
        out.append(a)
    return out

def parse_time(x):
    if not x:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(x, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(x.replace("Z", "+00:00"))
    except Exception:
        return None

def fetch_top_for_category(category_name, query, top_k=5):
    items = []
    # 优先用 NewsAPI（若可用）
    if NEWSAPI_KEY:
        try:
            items += fetch_newsapi(query, NEWSAPI_KEY, page_size=MAX_FETCH)
        except Exception as e:
            print(f"[warn] NewsAPI fetch failed for {category_name}: {e}")
    # 再尝试 Google News RSS
    try:
        items += fetch_google_news_rss(query, max_items=MAX_FETCH)
    except Exception as e:
        print(f"[warn] Google RSS fetch failed for {category_name}: {e}")

    # 标准化和去重、排序
    for it in items:
        it["_time"] = parse_time(it.get("publishedAt") or "") or datetime.min
    items = sorted(items, key=lambda a: a["_time"], reverse=True)
    items = unique_by_title(items)
    top = items[:top_k]
    for it in top:
        it.pop("_time", None)
    return top

def build_email_html(all_sections):
    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
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

def send_via_smtp(subject, html_body, from_email, to_emails):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = ", ".join(to_emails)
    part = MIMEText(html_body, "html", "utf-8")
    msg.attach(part)

    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30)
    try:
        server.ehlo()
        if SMTP_PORT in (587, 25):
            server.starttls()
            server.ehlo()
        if SMTP_USER and SMTP_PASSWORD:
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(from_email, to_emails, msg.as_string())
    finally:
        server.quit()

def send_via_sendgrid(subject, html_body, from_email, to_emails):
    if not SENDGRID_API_KEY:
        raise RuntimeError("SENDGRID_API_KEY not set")
    url = "https://api.sendgrid.com/v3/mail/send"
    to_list = [{"email": e} for e in to_emails]
    payload = {
        "personalizations": [{"to": to_list}],
        "from": {"email": from_email},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_body}]
    }
    headers = {"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json=payload, timeout=15)
    r.raise_for_status()
    return r

def main():
    if not TO_EMAILS:
        print("[error] No TO_EMAILS configured. Set TO_EMAILS in environment or .env (comma-separated).")
        return

    sections = []
    for cat, q in QUERIES.items():
        print(f"[info] Fetching for {cat} ...")
        top = fetch_top_for_category(cat, q, top_k=TOP_K)
        print(f"[info] Got {len(top)} items for {cat}")
        sections.append((cat, top))

    html = build_email_html(sections)
    subject = f"{SUBJECT_PREFIX} {datetime.utcnow().strftime('%Y-%m-%d')}"

    try:
        if SENDGRID_API_KEY:
            print("[info] Sending email via SendGrid...")
            send_via_sendgrid(subject, html, FROM_EMAIL, TO_EMAILS)
        else:
            print(f"[info] Sending email via SMTP {SMTP_SERVER}:{SMTP_PORT} ...")
            send_via_smtp(subject, html, FROM_EMAIL, TO_EMAILS)
        print("[info] Email sent.")
    except Exception as e:
        print(f"[error] Failed to send email: {e}")

if __name__ == "__main__":
    main()