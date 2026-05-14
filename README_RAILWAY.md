Quick Railway deploy notes

1. Ensure `BOT_TOKEN` is set in Railway Variables.
2. Railway provides `DATABASE_URL` when adding Postgres.
3. This project uses `Procfile` with `web: python chat_bot.py`.

If the container exits with `failed to exec pid1: No such file or directory`:
- Verify Railway Start Command is empty (Procfile is preferred).
- Ensure `chat_bot.py` exists at repo root and is named exactly.
- If you used a custom Start Command, set it to: `python chat_bot.py`.
- If issue persists, capture the full container logs in Railway and share them.

Redeploy steps:
- Push changes to GitHub
- On Railway, trigger a redeploy for the project

If the app still crashes quickly, collect logs via Railway UI and paste them here.
