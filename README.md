# DGCOMP-says

Tracks words used for the first time by the European Commission in published
competition decisions and emails them via [Buttondown](https://buttondown.com).
The bot ticks every 2 hours; ticks that find one new word send a single-word
email, ticks that find several send a single digest, ticks that find none
send nothing.

Source: [`competition-cases.ec.europa.eu`](https://competition-cases.ec.europa.eu/search) —
mergers, antitrust, state aid, DMA and foreign subsidies, English language only.

## Pipeline

```
PDF  →  Jina Reader  →  markdown
markdown  →  regex tokenise (preserves original case)
tokens   →  shape filter (length, vowel, ASCII)  →  Haiku validator (cached)
kept words  →  vocab.sqlite  →  Buttondown
```

## Development

Requires Python 3.11+.

```bash
uv sync --extra dev

uv run pytest -v
```

The unit tests don't hit the network or the LLM.

## Running the bot

The CLI is `dgcomp`:

```bash
uv run dgcomp backfill     # 1990-01-01 through today, M/AT/SA/DMA/FS
uv run dgcomp run          # one daily tick for today's decisions
uv run dgcomp review --limit 50
```

Configuration in `.env` (see `src/dgcomp/config.py` for the full list):

```
ANTHROPIC_API_KEY=sk-ant-...
BUTTONDOWN_API_KEY=...
```

The Buttondown API key lives at <https://buttondown.com/settings/programming>.
Subscribers, signup page, double-opt-in, unsubscribe links, GDPR data
requests, and deliverability are all handled by Buttondown — the bot just
calls `POST /v1/emails` once per non-empty tick.

## Hosting

- **Backfill**: run once with `uv run dgcomp backfill`.
- **Live cron**: a Hostinger VPS (KVM 2, Ubuntu 24.04) runs `uv run dgcomp run`
  every 2 hours via `systemd.timer`. Provisioning runbook + units are in
  [`deploy/DEPLOY.md`](deploy/DEPLOY.md); `deploy/bootstrap.sh` is idempotent
  and provider-agnostic (any Ubuntu 24.04 host with root SSH will do).
