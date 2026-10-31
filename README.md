# Stock Intelligence Cockpit

Umsetzung des Lastenhefts V1.1 (31.10.2026): kostenlose, quellenübergreifende Aktien- und
Unternehmensanalyse mit vier strikt getrennten Bewertungsdimensionen – **Company Quality**,
**Market Intelligence**, **Political Intelligence** und **Risk**.

Informations- und Analyseplattform. Keine Anlageberatung, keine Kauf-/Verkaufsempfehlung, keine Orderausführung.

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
| Insider USA | SEC EDGAR Form 4 | max. 10 Anfragen/s |
| Insider DE, 13F, Politiker | CSV-Importe | keine kostenlose strukturierte API eingebunden |
| Social Media | `social_mentions.csv`, Reddit-RSS optional (`SIC_ENABLE_REDDIT_RSS=1`) | X-API kostenpflichtig; Reddit-Bedingungen prüfen |

Alle Gewichte und Schwellen sind ein Startmodell und im Pflichtenheft zu validieren.
