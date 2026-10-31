"""Zentrale Konfiguration des Stock Intelligence Cockpit (Lastenheft V1.1).

Alle Gewichte, Schwellen und Quellen stehen hier, damit sie im Pflichtenheft
festgelegt und getestet werden koennen, ohne Code anzufassen.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
IMPORT_DIR = DATA_DIR / "imports"
STATE_DIR = DATA_DIR / "state"
CACHE_DIR = DATA_DIR / "cache"
OUTPUT_DIR = Path(os.environ.get("SIC_OUTPUT_DIR", ROOT.parent / "frontend" / "public" / "data"))

USER_AGENT = os.environ.get(
    "SIC_USER_AGENT",
    # SEC verlangt einen identifizierbaren User-Agent mit Kontakt (in GitHub Secrets setzen)
    "StockIntelligenceCockpit/1.1 (kontakt: bitte-in-SIC_USER_AGENT-setzen@example.com)",
)

# --------------------------------------------------------------------------
# 3. Aktienuniversum – Phase 1
# --------------------------------------------------------------------------
# Kostenlose Quellen der Indexzusammensetzung. Wikipedia-Inhalte stehen unter
# CC BY-SA (Quelle wird gespeichert). Russell 2000: iShares IWM-Holdings-CSV als
# frei abrufbarer Proxy (ETF-Bestand != offizielle FTSE-Russell-Liste; im Output
# als Einschränkung ausgewiesen).
INDEXES = {
    "NDX": {
        "name": "Nasdaq 100",
        "source": "https://en.wikipedia.org/wiki/Nasdaq-100",
        "kind": "wikipedia",
        # Ausweichquelle: offizielle Nasdaq-Indexliste (kostenlos, JSON)
        "fallbacks": [{"kind": "nasdaq_api", "source": "https://api.nasdaq.com/api/quote/list-type/nasdaq100"}],
        "min_members": 95, "max_members": 105, "region": "US", "currency": "USD", "suffix": "",
    },
    "SPX": {
        "name": "S&P 500",
        "source": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "kind": "wikipedia",
        "min_members": 495, "max_members": 510, "region": "US", "currency": "USD", "suffix": "",
    },
    "RUT": {
        "name": "Russell 2000",
        "source": "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/latest-holdings.csv",
        "kind": "ishares_csv",
        "fallbacks": [{"kind": "ishares_csv", "source": "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/1467271812596.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund"}],
        "min_members": 1800, "max_members": 2100, "region": "US", "currency": "USD", "suffix": "",
        "limitation": "Proxy über iShares-IWM-Bestand; Nutzungsbedingungen von BlackRock prüfen.",
    },
    "DAX": {
        "name": "DAX 40",
        "source": "https://en.wikipedia.org/wiki/DAX",
        "kind": "wikipedia",
        "min_members": 40, "max_members": 40, "region": "DE", "currency": "EUR", "suffix": ".DE",
    },
}

# --------------------------------------------------------------------------
# 4. Company Quality – Gewichte (Startmodell, zu validieren)
# --------------------------------------------------------------------------
QUALITY_WEIGHTS = {
    "revenue_growth": 0.15,
    "profitability": 0.15,
    "financial_stability": 0.15,
    "cashflow": 0.10,
    "market_position": 0.15,
    "growth_potential": 0.20,
    "management": 0.10,
}
# Mindestabdeckung (Gewichtsanteil), ab der ein Gesamtscore ausgegeben wird
QUALITY_MIN_COVERAGE = 0.40
FINANCIAL_SECTORS = {"Financial Services", "Financials", "Banks", "Insurance"}

# --------------------------------------------------------------------------
# 6. Political Intelligence – Trump-Sonderregel
# --------------------------------------------------------------------------
TRUMP_MAX_AGE_DAYS = 5            # Kalendertage ab Originaläußerung
TRUMP_BONUS = {                   # Numerische Höhe: im Pflichtenheft festzulegen
    "direct": 30,
    "indirect": 15,
    "sector": 0,
    "general": 0,
}
TRUMP_SOURCES = [
    # Offizielle, kostenlose Quellen (RSS). Truth-Social-Posts: CSV-Import.
    {"id": "whitehouse-news", "url": "https://www.whitehouse.gov/news/feed/", "type": "official"},
    {"id": "whitehouse-actions", "url": "https://www.whitehouse.gov/presidential-actions/feed/", "type": "official"},
]

# --------------------------------------------------------------------------
# 5. Market Intelligence
# --------------------------------------------------------------------------
NEWS_WINDOWS_H = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}
# Ticker-spezifische Yahoo-RSS-Schlagzeilen (frei, nur Titel/Link/Datum)
YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
NEWS_MAX_TICKERS_PER_RUN = int(os.environ.get("SIC_NEWS_MAX_TICKERS", "300"))
SIMILARITY_DUPLICATE = 0.80      # Jaccard-Aehnlichkeit für Syndizierung/Kopie

# --------------------------------------------------------------------------
# 7. Market & Economic Ticker – kostenlose offizielle Quellen
# --------------------------------------------------------------------------
MARKET_NEWS_FEEDS = [
    {"id": "fed-press", "name": "Federal Reserve – Press Releases",
     "url": "https://www.federalreserve.gov/feeds/press_all.xml", "markets": ["USA", "global"],
     "category": "Zentralbank"},
    {"id": "ecb-press", "name": "EZB – Pressemitteilungen",
     "url": "https://www.ecb.europa.eu/rss/press.html", "markets": ["Europa"], "category": "Zentralbank"},
    {"id": "bls-news", "name": "U.S. BLS – Latest Releases",
     "url": "https://www.bls.gov/feed/bls_latest.rss", "markets": ["USA"], "category": "Konjunkturdaten"},
    # Destatis: alte RSS-Adresse liefert 404, keine neue gefunden (Stand 31.10.2026).
    # Bei gefundener Adresse hier wieder eintragen; "page" aktiviert die RSS-Autodiscovery.
    # {"id": "destatis", "name": "Destatis – Pressemitteilungen", "url": "...",
    #  "page": "https://www.destatis.de/DE/Presse/_inhalt.html", "markets": ["Europa"], "category": "Konjunkturdaten"},
]
# Relevanzfilter: nur Eintraege mit plausibler Markt-/Wirtschaftsrelevanz
MARKET_KEYWORDS = {
    "Zentralbank": ["rate", "monetary", "fomc", "interest", "zins", "geldpolit", "balance sheet"],
    "Inflation": ["inflation", "cpi", "pce", "verbraucherpreis", "preise", "hicp"],
    "Arbeitsmarkt": ["employment", "payroll", "unemployment", "jobs", "arbeitsmarkt", "erwerbs"],
    "Wachstum": ["gdp", "bip", "growth", "output", "industrial production", "produktion", "auftragseingang"],
    "Handel/Zölle": ["tariff", "zoll", "trade", "export", "import", "sanction", "sanktion"],
    "Finanzstabilität": ["bank", "liquidity", "stress test", "financial stability", "credit"],
    "Energie/Rohstoffe": ["oil", "gas", "energy", "energie", "commodity", "rohstoff"],
}

# --------------------------------------------------------------------------
# 8. Insider (SEC EDGAR)
# --------------------------------------------------------------------------
SEC_TICKER_MAP = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
SEC_MAX_REQ_PER_SEC = 8          # SEC-Fair-Access: max. 10/s
INSIDER_LOOKBACK_DAYS = 30
INSIDER_MAX_TICKERS_PER_RUN = int(os.environ.get("SIC_INSIDER_MAX_TICKERS", "150"))

# --------------------------------------------------------------------------
# 15. Stabilität
# --------------------------------------------------------------------------
PRICE_BATCH_SIZE = 200
FUNDAMENTALS_REFRESH_DAYS = 7    # gestaffelte Aktualisierung
FUNDAMENTALS_MAX_PER_RUN = int(os.environ.get("SIC_FUNDAMENTALS_MAX", "400"))
HTTP_TIMEOUT = 20
HTTP_RETRIES = 3
