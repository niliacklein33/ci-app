
# Competitive Intelligence App (GitHub Pages)

Modern React + TypeScript + Tailwind app with auto-updating competitor insights, battle cards, and team updates.

## Web Upload Deploy (no terminal)

1. Create a repo on GitHub (e.g., `yourname/ci-app`) — **do not** initialize with a README.
2. Download this ZIP and unzip locally.
3. In your repo → **Add file → Upload files** → drag **all** files/folders (including `.github/`).
4. Commit to `main`.
5. In **Settings → Pages**: set **Source = GitHub Actions**.
6. Watch the **Actions** tab → “Deploy to GitHub Pages” run → your site goes live.

## Local Dev

```bash
npm install
npm run dev
```

## Auto-Ingestion

The `ingest.yml` workflow updates `public/data/insights.json` every 10 minutes. Edit `scripts/ingest.py` to add sources.
