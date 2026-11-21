# Завтра ближе — автоматическая редакция

GitHub Actions запускает редакцию каждые 30 минут, RSS → Gemini → Telegram @zavtrablize. Не более 3 постов в день. База SQLite (`news.db`) сохраняется коммитом в репозиторий между запусками.

## Подготовка
1. Upload all files/folders to private repo `zavtrablize-news` (including hidden `.github/workflows/publish.yml`).
2. Repository Settings → Secrets and variables → Actions → add repository secrets:
   - `GEMINI_API_KEY` — API key from Google AI Studio.
   - `TELEGRAM_BOT_TOKEN` — bot token. Bot must be administrator of the channel with posting rights.
   - `TELEGRAM_ADMIN_ID` — optional numeric Telegram ID for failure alerts.
3. Repository Settings → Actions → General → Workflow permissions → ensure Read and write permissions.
4. Actions → workflow → Run workflow. First run processes at most one eligible story; subsequent scheduled runs continue, up to 3/day.

## Notes
- `news.db` is committed after each workflow run; workflow concurrency prevents overlapping jobs.
- RSS timestamps are filtered to 14 days where available. This does not guarantee source verification; AI filtering can make mistakes.
- Google Docs/Sheets archive is intentionally omitted from initial deployment to reduce failure points. It can be added after Telegram publication is verified.
- Do not share secrets publicly or in chat.
