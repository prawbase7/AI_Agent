# Contributing

Solo project for now, but it's run with normal conventions so it stays easy to
pick back up.

## Local setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in keys
```

Run the data layer directly:

```bash
python data_sources.py
```

Run the web app:

```bash
python app.py             # dev server, http://localhost:8000
gunicorn app:app          # prod-like
```

## Branching

- `main` is always deployable; Render auto-deploys it.
- Work on `feat/<short-name>`, `fix/<short-name>`, or `docs/<short-name>`.
- Open a PR into `main` (even solo — it's the paper trail). Squash-merge.

## Commits

Short imperative subject, body explaining *why* when it isn't obvious:

```
Compute 52-week range from price history instead of stock.info

Yahoo rate-limits the .info endpoint from cloud IPs, leaving the range
blank on the deployed site.
```

## Definition of done for a phase

A phase isn't done until its **exit criteria in [ROADMAP.md](ROADMAP.md)** are
met, the [CHANGELOG](CHANGELOG.md) is updated, and it's deployed and verified on
the live URL.

## Conventions

- Keep external-data code in `data_sources.py`; keep web concerns in `app.py`.
- Every new data source gets a graceful fallback or a clear "not configured"
  path — the app must still render without it.
- No secrets in the repo. New config goes in `.env.example` with a comment.
- No build step for the frontend; it stays a single template.
