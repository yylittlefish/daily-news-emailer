# Daily News Emailer

每天抓取并发送 Top5 新闻（International, AI, Entertainment）。

使用说明、环境变量以及如何在 GitHub Actions 中定时执行请见下文。

## 本地运行

1. 创建虚拟环境并安装依赖：
python3 -m venv venv
source venv/bin/activate
pip install requests feedparser python-dotenv
2. 准备 `.env`（可参考 `.env.example`）并放在项目根目录。

3. 运行：
python send_news_daily.py

## 使用 GitHub Actions 定时运行

仓库包含 `.github/workflows/daily.yml`，可每天自动运行。需要在仓库 Settings -> Secrets and variables -> Actions 中添加以下 Secrets：
- NEWSAPI_KEY （可选）
- SENDGRID_API_KEY 或 SMTP_USER、SMTP_PASSWORD、SMTP_SERVER、SMTP_PORT
- FROM_EMAIL
- TO_EMAILS （逗号分隔）
- SUBJECT_PREFIX （可选）

调整 workflow 的 cron 表达式以符合你希望的触发时间（注意 GitHub Actions 的 cron 使用 UTC）。
