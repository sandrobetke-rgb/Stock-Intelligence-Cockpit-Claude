# Stock Intelligence Cockpit

Umsetzung des Lastenhefts V1.1 (31.10.2026): kostenlose, quellenübergreifende Aktien- und
Unternehmensanalyse mit vier strikt getrennten Bewertungsdimensionen – **Company Quality**,
**Market Intelligence**, **Political Intelligence** und **Risk**.

Informations- und Analyseplattform. Keine Anlageberatung, keine Kauf-/Verkaufsempfehlung, keine Orderausführung.

## Bedienung im Alltag

**Adresse:** https://sandrobetke-rgb.github.io/Stock-Intelligence-Cockpit-Claude/

| Wann | Was passiert automatisch |
|---|---|
| Mo–Fr 06:15 MEZ | Morgenlauf: Nachrichten, Insider, Politiker, Trump, Social Media, Termine; **Tagesbericht** per Push/E-Mail |
| Mo–Fr 22:40 MEZ | Abendlauf: zusätzlich Kurse, Fundamentaldaten, Setups/Strategien, Superinvestoren; **Watchlist-Alarme** |
| bei jeder Änderung im Repo | kurzer Lauf ohne Datenabruf (z. B. nach Speichern der Watchlist) |

**Seiten:** Tagesbericht · Dashboard · Watchlist & Alarme · Swing-Setups · Signal-Zusammenfluss · Opportunity Radar ·
Trump Mention Radar · Markt- & Wirtschaftsticker · Quality Stocks · Superinvestoren · Politiker-Trades ·
Insider & Institutionen · Social Media · Fact-Checking · Risk Overview

**Kennzeichnung an jeder Aktie:** ☆ Watchlist · **A–E** Qualitätsnote (Company Quality ≥80/65/50/35/darunter, ? = zu wenige Daten) ·
**↗ ↘ →** Trend (über/unter EMA 200 mit EMA 20 vs. 50) · schwarzes Kürzel = heute erfülltes Setup bzw. Strategie ·
„Zahlen in X T.“ / „Ex-Div.“ = anstehender Termin.

**Setups/Strategien (Tagesbasis, nach US-Börsenschluss):**
S01 Rebound · S02 Rising Star · S03 Breakout · S04 HHLL+OBV (deine TradingView-Screener) ·
DSM Daily Swing Master · RSI2 Überdehnter Rücksetzer · QM Momentum-Breakout (regelbasierte Annäherungen).
Einstiegsplan je Aktie: Auslöser, max. +2 %, Stopp 1,5 × ATR, Ziel 2:1, Stückzahl bei 1 % Risiko (Kapital im Browser eintragen).
Trader XO (S04) ist durch EMA 12 > EMA 25 angenähert; „Daily Score 8+“ und „Trend-Bestätigter Rebound“ sind noch nicht abgebildet.

### Secrets (GitHub → Settings → Secrets and variables → Actions)

| Name | Pflicht | Zweck |
|---|---|---|
| `SIC_USER_AGENT` | ja | Kontaktangabe für SEC EDGAR, z. B. `StockIntelligenceCockpit/1.1 (mail@example.com)` |
| `NTFY_TOPIC` | empfohlen | Push aufs Handy über die App ntfy (gleicher Themenname in der App abonnieren) |
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | empfohlen | eigener kostenloser Reddit-Zugang (reddit.com/prefs/apps, Typ „script“) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO` | optional | Alarme und Tagesbericht per E-Mail |
| `OPENFIGI_API_KEY` | optional | schnellere CUSIP-Zuordnung bei Superinvestoren |

### Pflege per CSV (`backend/data/imports/`)

`watchlist/*.csv` (vom Cockpit erzeugt) · `trump_statements.csv` (Truth-Social-Posts) · `aliases.csv` (Firmennamen für Trump/Social) ·
`market_calendar.csv` (Termine) · `superinvestors.csv` (beobachtete Investoren) · `index_changes.csv`, `exclusions.csv` (Universum) ·
`fact_checks.csv`, `quality_manual.csv`, `risk_manual.csv`, `insider_manual.csv` (BaFin), `institutional_holdings.csv`, `social_mentions.csv`.

### Bekannte Grenzen (Stand 01.11.2026)

- Senat (eFD), Truth Social und Reddit ohne eigenen Zugang blockieren Abrufe von GitHub-Servern.
- X/Twitter ist nicht kostenlos angebunden; StockTwits dient als Ersatz.
- Kurse/Fundamentaldaten (Yahoo), Termine (Nasdaq) und Indexlisten (Wikipedia/iShares) sind inoffizielle bzw. Proxy-Quellen.
- 13F-Depots: Quartalsstand, bis 45 Tage verzögert. Politiker-Trades: bis 45 Tage verzögert, Wertbandbreiten.
- Alle Scores sind ein Startmodell (Gewichte in `backend/sic/config.py`); keine Anlageberatung.

## Aufbau

```
backend/                 Python-Pipeline (Pandas/NumPy, yfinance, feedparser)
  sic/
    config.py            Gewichte, Schwellen, Quellen (Pflichtenheft-Stellschrauben)
    universe.py          Kap. 3  Indizes laden, deduplizieren, Austrittsregeln, Archiv
    market.py            Kap. 12 Kurse (Batch), ADR20, RVOL, EMA/SMA, Fundamentaldaten-Cache
    quality.py           Kap. 4  Company Quality, Datenabdeckung, Finanzmodell, Proxys
    risk.py              Kap. 11 Risk Score
    signals.py           Kap. 5/10 Signalmodell, Duplikat-Fingerprint, Syndizierung, Verifizierung
    news.py              Kap. 5  Yahoo-RSS je Ticker (rotierend) + CSV
    intelligence.py      Kap. 5  Multi-Source-Radar (Market Intelligence Score)
    politics.py          Kap. 6  Trump Mention Radar (5-Tage-Regel), politische Ereignisse/Trades
    events.py            Kap. 7  Markt- & Wirtschaftsticker (Fed/EZB/BLS/Destatis + Kalender-CSV)
    insider.py           Kap. 8  SEC Form 4, BaFin-/13F-CSV
    social.py            Kap. 9  Erwähnungen, Sentiment, Manipulationshinweise
    export.py            Kap. 14/15 JSON-Schemas, Validierung, atomare Veröffentlichung
    run.py               Pipeline (jeder Schritt isoliert, Fehler protokolliert)
    demo.py              synthetische DEMO-Daten für die Frontend-Entwicklung
  data/imports/*.csv     CSV-Importe (Vorlagen mit Kommentarzeile #)
  data/state/            Zustand: Universum, Signalhistorie, Insider, Ereignisse
  tests/test_rules.py    Abnahmekriterien Kap. 16 als Tests
frontend/                React + TypeScript (Vite), GitHub Pages
  public/data/           Live-JSON (von der Pipeline geschrieben)
  public/demo-data/      DEMO-JSON (Fallback, mit Warnbanner)
.github/workflows/pipeline.yml   Börsentagslauf, Tests, Commit der Daten, Pages-Deployment
```

## JSON-Endpunkte

`summary.json`, `stocks.json`, `intelligence.json`, `politics.json`, `trump-mentions.json`,
`market-events.json`, `social.json`, `fact-checks.json` – zusätzlich `insider.json`
(Insider & Institutionen) und `company/<SYMBOL>.json` (Detailseiten, hält `stocks.json` klein).

## Einrichtung

1. Inhalt dieses Ordners ins GitHub-Repo übernehmen.
2. **Settings → Pages → Source: GitHub Actions** aktivieren.
3. **Settings → Secrets → Actions**: `SIC_USER_AGENT` setzen, z. B.
   `StockIntelligenceCockpit/1.1 (dein.name@example.com)` – die SEC verlangt einen identifizierbaren User-Agent.
4. **Actions → Daten-Pipeline & Deployment → Run workflow** einmal manuell starten.
   Danach läuft die Pipeline Mo–Fr um 21:40 UTC (nach US-Börsenschluss in Sommer- und Winterzeit).

Lokal:

```bash
cd backend && pip install -r requirements.txt
python -m pytest -q                 # Abnahmekriterien
python -m sic.run                   # Volllauf (Netzwerk nötig)
python -m sic.run --no-fetch        # nur Zustand + CSV neu auswerten
python -m sic.demo                  # DEMO-Daten erzeugen
cd ../frontend && npm install && npm run dev
```

Der erste Volllauf dauert länger: Fundamentaldaten werden gestaffelt geladen (max. 400 Titel je
Lauf, Aktualisierung alle 7 Tage, Cache in `backend/data/cache`). Nachrichten und SEC-Meldungen
werden rotierend abgefragt (300 bzw. 150 Ticker je Lauf). Über Umgebungsvariablen
`SIC_FUNDAMENTALS_MAX`, `SIC_NEWS_MAX_TICKERS`, `SIC_INSIDER_MAX_TICKERS` anpassbar.

## Kernregeln (umgesetzt und getestet)

- **Trump-Sonderbonus** nur für verifizierte direkte (+30) oder dokumentiert indirekte (+15)
  Unternehmensnennungen, deren *Original*zeitpunkt höchstens 5 Kalendertage zurückliegt;
  automatischer Verfall, Historie bleibt. Branchen-/allgemeine Aussagen, unklares Datum,
  unbestätigte Quelle oder ungeprüfte Namenszuordnung → kein Bonus. Mehrdeutige Firmennamen
  (z. B. „Target“) brauchen einen Eintrag in `aliases.csv`. Bonushöhe in `config.py`.
- **Negative Aussagen** werden nie als positiv dargestellt; Relevanz und Wirkungsrichtung sind getrennt.
- **Company Quality** importiert weder News, Social, Politik noch Kursindikatoren (per Test geprüft).
  Fehlende Werte = unbekannt, Gewicht wird umverteilt, Abdeckung in % ausgewiesen. Finanzwerte
  nutzen ein angepasstes Modell. Marktposition, Wachstumspotenzial und Management sind kostenlos
  nur über gekennzeichnete Proxys messbar; belegte manuelle Einschätzungen (`quality_manual.csv`) haben Vorrang.
- **Universum**: Indexaustritt beendet nur die Zugehörigkeit; Universumsaustritt erst ohne
  Zielindex oder bei Ausschlussgrund (`exclusions.csv`). Datenfehler sind kein Ausschluss.
  Unplausibler Indexabruf überschreibt nie die letzte gültige Liste.
- **Duplikate/Syndizierung** zählen nicht als unabhängige Quellen.
- **Veröffentlichung** nur nach Schema-Validierung aller Dateien.

## Quellen und Einschränkungen

| Bereich | Quelle | Hinweis |
|---|---|---|
| Kurse/Fundamentaldaten | Yahoo Finance via yfinance | inoffiziell, Limits/Bedingungen prüfen |
| Indizes | Wikipedia (CC BY-SA), Nasdaq-API als Ausweichquelle, iShares IWM-Bestand | IWM ist Russell-2000-*Proxy*; BlackRock-Bedingungen prüfen |
| Nachrichten | Yahoo-Finance-RSS | nur Schlagzeile, Link, Datum |
| Trump | whitehouse.gov-RSS, `trump_statements.csv` | Truth Social hat keine kostenlose API → CSV mit Original-URL |
| Wirtschaftsticker | Fed, EZB, BLS (RSS), `market_calendar.csv` (Destatis-Feed derzeit ohne gültige Adresse) | Termine Stand 31.10.2026, vor Nutzung prüfen |
| Insider USA | SEC EDGAR Form 4 (Tagesindex, gesamter Markt) | max. 10 Anfragen/s |
| Superinvestoren | SEC EDGAR 13F-HR, CUSIP-Zuordnung über OpenFIGI | Quartalsstichtag, bis 45 Tage Verzug; Liste in `superinvestors.csv` |
| Insider DE, 13F, Politiker | CSV-Importe | keine kostenlose strukturierte API eingebunden |
| Social Media | `social_mentions.csv`, Reddit-RSS optional (`SIC_ENABLE_REDDIT_RSS=1`) | X-API kostenpflichtig; Reddit-Bedingungen prüfen |

Alle Gewichte und Schwellen sind ein Startmodell und im Pflichtenheft zu validieren.

## Zugriffsschutz mit Cloudflare Pages + Cloudflare Access

Ist das Secret `CLOUDFLARE_API_TOKEN` gesetzt, veröffentlicht der Workflow das Cockpit auf Cloudflare Pages statt auf GitHub Pages.

1. Cloudflare: **My Profile → API Tokens → Create Token → Custom token**, Berechtigung *Account → Cloudflare Pages → Edit*.
2. GitHub **Settings → Secrets and variables → Actions**:
   - Secrets: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` (Cloudflare-Startseite → Account-ID).
   - Variables (optional): `CF_PAGES_PROJECT` (Standard `sic-cockpit`), `COCKPIT_URL` (z. B. `https://sic-cockpit.pages.dev/`).
3. Workflow starten. Das Cloudflare-Projekt wird automatisch angelegt.
4. Cloudflare **Zero Trust → Access → Applications → Add → Self-hosted**: Domain `<projekt>.pages.dev` und `*.<projekt>.pages.dev`; Policy *Allow*, Include *Emails* = eigene Adresse; Login per *One-time PIN*.
5. GitHub **Settings → Pages**: GitHub-Pages-Seite deaktivieren (Unpublish), sonst bleibt die alte öffentliche Adresse bestehen.

Hinweis: Access schützt nur die Webseite. Solange das Repository öffentlich ist, sind die Rohdaten (JSON/CSV) auf GitHub einsehbar.
