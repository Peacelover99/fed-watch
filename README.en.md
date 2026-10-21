# Fed Watch · US Economic Data Surprise Monitor

[中文](README.md) | **English**

[![Fed Watch](https://github.com/Peacelover99/fed-watch/actions/workflows/fedwatch.yml/badge.svg)](https://github.com/Peacelover99/fed-watch/actions/workflows/fedwatch.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

The Fed is data-dependent, and markets price in the *expected* data well before it is released. **What moves Treasuries and equities is the gap between the actual print and expectations.**

After each key US economic release, Fed Watch automatically:

1. Fetches the latest data and official release dates from FRED (St. Louis Fed)
2. Compares the print with the market consensus, computes a **standardized surprise (z-score)** and maps it to a **hawkish / dovish direction**
3. Shows how the 2-year Treasury yield, S&P 500 and Nasdaq moved on the day of similar past surprises
4. Sends an alert via WeChat (ServerChan), WeCom, Telegram or email
5. After the close, checks whether the 2-year yield moved in the direction of the surprise (**market confirms / market disagrees**) and sends a follow-up
6. Updates a dashboard hosted on GitHub Pages

Everything runs on GitHub Actions: no server needed, and free for personal use.

**Live dashboard**: <https://peacelover99.github.io/fed-watch/> · [Demo (simulated data)](https://peacelover99.github.io/fed-watch/demo.html)

> ⚠️ For research purposes only. Not investment advice.

## Example alert

Alerts are in Chinese:

```
🔴 核心CPI 环比 鹰派意外 +2.1σ            (Core CPI MoM — hawkish surprise +2.1σ)

核心CPI 环比（2026-09）
实际 0.5%，预期 0.3%（来源：Investing.com）  (actual 0.5%, consensus 0.3%)
意外 +0.2% = +2.10σ → 鹰派 z +2.10
历史同指标同类意外 8 次：2年美债平均 +9.5bp，标普 -1.12%（下跌概率 75%）
(8 similar past surprises: 2Y yield +9.5bp on average, S&P 500 −1.12%, down 75% of the time)
```

## Method

```
surprise        = actual − consensus  (+ net revisions to the prior two months, for payrolls)
z               = surprise ÷ std. dev. of this indicator's past surprises
hawkish z       = z × direction  (+1 for inflation / jobs / retail; −1 for unemployment / jobless claims)
surprise index  = time-decayed weighted average of hawkish z across indicators
                  (30-day half-life, weighted by how much the Fed cares)
```

- **Why standardize**: a 0.1pp miss in core CPI and a 50k miss in payrolls aren't comparable; z-scores put every surprise in units of "standard deviations". By default |z| ≥ 1.5 counts as a major surprise.
- **Short history**: while an indicator has fewer than 6 past consensus records, the std. dev. of naive forecast errors (last value as the forecast) is used instead. It is usually larger than professional forecast errors, so z is conservative. The alert says so when this applies.
- **First print**: surprises use the first-released value the market actually saw; later data revisions never rewrite past surprises.
- **Precision**: values are rounded to their published precision before comparison, avoiding false surprises like 0.349% vs 0.3%.

Indicators monitored by default (add, remove or re-weight in `config/indicators.yaml`):

| Indicator | FRED series | Weight | Above consensus |
|---|---|---|---|
| Core CPI MoM | CPILFESL | 3 | Hawkish |
| CPI MoM | CPIAUCSL | 2 | Hawkish |
| Core PCE MoM | PCEPILFE | 3 | Hawkish |
| Nonfarm payrolls (incl. revisions) | PAYEMS | 3 | Hawkish |
| Unemployment rate | UNRATE | 2 | Dovish |
| Retail sales MoM | RSAFS | 1 | Hawkish |
| Initial jobless claims | ICSA | 1 | Dovish |

## Quick start (~10 minutes)

### 1. Fork this repository

Click **Fork**, then enable Actions in your fork (green button on the **Actions** tab).

### 2. Get a FRED API key (free)

Register at <https://fred.stlouisfed.org/docs/api/api_key.html>. The key is a 32-character lowercase alphanumeric string.

### 3. Add secrets

**Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Description |
|---|---|
| `FRED_API_KEY` | Required. The key from step 2 |
| `SERVERCHAN_KEY` | [ServerChan](https://sct.ftqq.com) SendKey, pushes to your personal WeChat |
| `WECOM_WEBHOOK` | WeCom (WeChat Work) group bot webhook URL |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Telegram bot |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `ALERT_EMAIL_TO` | Email |

Configure at least one channel; alerts go to every channel you configure. Credentials live only in Secrets and never appear in code, data or logs.

### 4. Enable GitHub Pages

**Settings → Pages**: Source *Deploy from a branch*, branch `main`, folder `/docs`. The dashboard will be at `https://<user>.github.io/<repo>/`.

### 5. Send a test alert

**Actions → Fed Watch → Run workflow ▾**, tick **"只发送一条测试推送"** (send a test alert only) and run. You'll receive a sample alert built from the latest real data.

> The GitHub mobile app doesn't show this checkbox; use a browser.

From then on it checks every 15 minutes on weekdays between 8:00 and 11:00 ET, plus a daily morning run to pick up the previous day's market close.

## Day-to-day: entering consensus forecasts

Professional consensus data (Bloomberg, Reuters) is paid, so forecasts are **entered by hand**: before a release, append a line to `data/consensus.csv`. You can edit it directly on GitHub; committing triggers a recalculation.

```csv
indicator,period,consensus,source,actual,revision,note
core_cpi,2026-10,0.3,Investing.com,,,
nfp,2026-10,120,Investing.com,,,
claims,2026-10-24,225,Investing.com,,,
```

| Indicator | `indicator` | `period` | `consensus` units |
|---|---|---|---|
| CPI / core CPI MoM | `cpi` / `core_cpi` | reference month `2026-10` | `0.3` = 0.3% |
| Core PCE MoM | `core_pce` | `2026-09` | `0.2` = 0.2% |
| Nonfarm payrolls | `nfp` | `2026-10` | `100` = 100k |
| Unemployment rate | `unrate` | `2026-10` | `4.2` = 4.2% |
| Retail sales MoM | `retail` | `2026-10` | `0.4` = 0.4% |
| Initial jobless claims | `claims` | week-ending Saturday `2026-10-24` | `225` = 225k |

- `period` is the **reference period**, not the release date: CPI released in mid-November is October data, so write `2026-10`.
- Leave `actual` and `revision` **empty** day to day; the first print and payroll revisions are captured automatically. Fill them only when backfilling history, because FRED's historical values have since been revised.
- Sources: the "forecast" / "consensus" column of economic calendars such as Investing.com or ForexFactory.
- If data is released without a consensus entry, you get a reminder; add it and the surprise is computed automatically.

## Reliability

- **FRED maintenance or outages**: the run logs a warning and retries on the next run, so no data is lost. If the outage lasts more than 3 hours you get one alert, and another when it recovers.
- **One failing indicator** doesn't affect the others. Actions only marks a run as failed for configuration errors (e.g. an invalid API key).
- Each event is alerted once; re-runs never send duplicates.

## Running locally

```bash
pip install -r requirements.txt
python -m fedwatch demo          # offline demo with simulated data → docs/demo.html (no network needed)
export FRED_API_KEY=your_key
python -m fedwatch run --dry-run # fetch real data without sending alerts
python -m fedwatch backfill      # backfill history from consensus.csv (no alerts)
python -m fedwatch test-notify   # test alert channels
python -m unittest discover -s tests
```

## Project layout

```
config/indicators.yaml     indicators, weights, thresholds
data/consensus.csv         consensus forecasts (maintained by hand)
data/events.csv            computed results for each release (generated)
data/snapshots/            raw series snapshots, used to compute revisions
docs/                      dashboard (generated, served by GitHub Pages)
fedwatch/
  fred.py                  FRED client
  surprise.py              surprises, std. dev., composite index, historical analogs (pure functions)
  market.py                market reaction on release day
  pipeline.py              main flow and alert text
  notify.py                alert channels
  dashboard.py             dashboard generation
  demo.py                  simulated data
```

## Known limitations

- **Same-day releases**: when CPI and retail sales come out on the same day, or a Fed speech coincides, the market move can't be attributed to a single release.
- **Daily data**: uses closing prices rather than intraday reactions; FRED usually updates Treasury yields the next day, so "market confirms" arrives a day later.
- **Manual consensus**: releases without a consensus entry can't be scored.

## Roadmap

- Rate-decision surprises (2-year yield around FOMC meetings)
- Dot plot vs. market pricing
- Hawkish/dovish scoring of Fed speeches
- Automatic consensus data

## License

[MIT](LICENSE). Data from [FRED®](https://fred.stlouisfed.org); use is subject to FRED's [terms of use](https://fred.stlouisfed.org/legal/). This project is not affiliated with the Federal Reserve Bank of St. Louis or the Federal Reserve System.
