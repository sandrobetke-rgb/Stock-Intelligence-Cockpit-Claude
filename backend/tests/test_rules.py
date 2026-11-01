"""Abnahmekriterien aus Lastenheft Kap. 16 als automatisierte Tests (ohne Netzwerk)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from sic import config


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    for name in ("STATE_DIR", "CACHE_DIR", "IMPORT_DIR"):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(config, name, d)
    from sic import universe
    monkeypatch.setattr(universe, "STATE_FILE", tmp_path / "state_dir" / "universe.json")
    # Plausibilitaetsgrenzen fuer Mini-Indizes
    monkeypatch.setattr(config, "INDEXES", {
        "NDX": {**config.INDEXES["NDX"], "min_members": 3, "max_members": 5},
        "SPX": {**config.INDEXES["SPX"], "min_members": 4, "max_members": 6},
        "RUT": {**config.INDEXES["RUT"], "min_members": 2, "max_members": 4},
        "DAX": {**config.INDEXES["DAX"], "min_members": 2, "max_members": 3},
    })
    yield tmp_path


NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------- Universum --
def _m(*syms):
    from sic.universe import Member
    return [Member(s, f"{s} Corp") for s in syms]


def test_universe_dedup_and_exit_rules():
    from sic.universe import active_symbols, build_universe, index_positions
    ov = {"NDX": _m("AAPL", "MSFT", "NVDA"), "SPX": _m("AAPL", "MSFT", "NVDA", "XOM"),
          "RUT": _m("SMAL", "TINY"), "DAX": _m("SAP.DE", "BMW.DE")}
    st = build_universe(date(2026, 10, 1), fetch=False, overrides=ov)
    assert len(active_symbols(st)) == 8                     # dedupliziert
    assert index_positions(st) == 11                        # alle Zugehoerigkeiten gespeichert
    assert sorted(m["index"] for m in st["securities"]["AAPL"]["memberships"]) == ["NDX", "SPX"]

    # NVDA verlaesst NDX, bleibt aber im SPX -> aktiv; TINY verlaesst RUT -> archiviert
    ov2 = {"NDX": _m("AAPL", "MSFT", "AMD"), "SPX": _m("AAPL", "MSFT", "NVDA", "XOM"),
           "RUT": _m("SMAL", "NEWS"), "DAX": _m("SAP.DE", "BMW.DE")}
    st = build_universe(date(2026, 10, 15), fetch=False, overrides=ov2)
    nvda = st["securities"]["NVDA"]
    assert nvda["status"] == "active"
    assert any(m["index"] == "NDX" and m["until"] == "2026-10-15" for m in nvda["memberships"])
    assert st["securities"]["TINY"]["status"] == "archived"
    assert st["securities"]["TINY"]["status_reason"] == "no_target_index"
    assert "TINY" in st["securities"]                       # historisch erhalten
    assert st["securities"]["AMD"]["status"] == "active"


def test_failed_index_does_not_overwrite_valid_list():
    from sic.universe import build_universe
    good = {"NDX": _m("A1", "A2", "A3"), "SPX": _m("A1", "A2", "A3", "A4"), "RUT": _m("R1", "R2"), "DAX": _m("D1.DE", "D2.DE")}
    build_universe(date(2026, 10, 1), fetch=False, overrides=good)
    bad = {**good, "SPX": _m("A1")}                          # Abruf unvollstaendig
    st = build_universe(date(2026, 10, 2), fetch=False, overrides=bad)
    assert st["indexes"]["SPX"]["status"] == "error"
    assert st["securities"]["A4"]["status"] == "active"     # nicht faelschlich entfernt


def test_data_error_is_not_exclusion_but_csv_exclusion_is():
    from sic.universe import build_universe
    ov = {"NDX": _m("A1", "A2", "A3"), "SPX": _m("A1", "A2", "A3", "A4"), "RUT": _m("R1", "R2"), "DAX": _m("D1.DE", "D2.DE")}
    (config.IMPORT_DIR / "exclusions.csv").write_text("symbol,reason,source,date\nR1,delisted,https://x,2026-10-01\n")
    st = build_universe(date(2026, 10, 1), fetch=False, overrides=ov)
    assert st["securities"]["R1"]["status"] == "archived" and st["securities"]["R1"]["status_reason"] == "delisted"


def test_scheduled_index_change_marked_upcoming_then_applied():
    from sic.universe import build_universe
    ov = {"NDX": _m("A1", "A2", "A3"), "SPX": _m("A1", "A2", "A3", "A4"), "RUT": _m("R1", "R2"), "DAX": _m("D1.DE", "D2.DE")}
    (config.IMPORT_DIR / "index_changes.csv").write_text(
        "index,symbol,action,effective_date,source,name\nSPX,NEWCO,add,2026-11-20,https://spglobal.example,NewCo\n")
    st = build_universe(date(2026, 11, 1), fetch=False, overrides=ov)
    assert st["upcoming_changes"][0]["symbol"] == "NEWCO" and "NEWCO" not in st["securities"]
    st = build_universe(date(2026, 11, 20), fetch=False, overrides={k: v for k, v in ov.items() if k != "SPX"})
    assert st["securities"]["NEWCO"]["status"] == "active"


# --------------------------------------------------------- Quality/Risk --
def test_quality_unknown_not_negative_and_coverage():
    from sic.quality import score_quality
    full = {"revenue_cagr": 10, "revenue_growth_yoy": 10, "operating_margin": 20, "net_margin": 12,
            "debt_to_equity": 0.5, "current_ratio": 1.8, "interest_coverage": 12, "fcf_margin": 10,
            "operating_cashflow": 1e9, "gross_margin": 50, "revenue_growth_forward": 12, "rnd_intensity": 10,
            "capex_intensity": 5, "roe": 18, "share_change_yoy": -1}
    a = score_quality("X", full, "Technology")
    partial = {k: v for k, v in full.items() if k not in ("gross_margin", "interest_coverage")}
    b = score_quality("X", partial, "Technology")
    assert a["coverage_pct"] == 100 and b["coverage_pct"] < 100
    mp = next(d for d in b["dimensions"] if d["key"] == "market_position")
    assert mp["score"] is None and mp["basis"] == "unknown"
    # Fehlende Werte ziehen den Score nicht automatisch nach unten
    assert abs(a["score"] - b["score"]) < 10
    assert score_quality("X", {}, "Technology")["score"] is None


def test_quality_ignores_attention_inputs():
    """Company Quality darf durch News/Social/Trump/Technik nicht beeinflusst werden."""
    import inspect
    from sic import quality
    src = inspect.getsource(quality)
    for forbidden in ("politics", "social", "intelligence", "signals", "market import", "trump"):
        assert f"from .{forbidden.split()[0]}" not in src
    f = {"revenue_cagr": 5, "operating_margin": 10}
    assert quality.score_quality("X", {**f, "trump_bonus": 30, "rvol": 9, "mentions_7d": 999}, None)["score"] == \
        quality.score_quality("X", f, None)["score"]


def test_financial_model_marks_not_applicable():
    from sic.quality import score_quality
    q = score_quality("JPM", {"net_margin": 25, "roe": 15, "revenue_cagr": 6, "revenue_growth_yoy": 5,
                              "share_change_yoy": -2, "revenue_growth_forward": 4}, "Financial Services")
    assert q["model"] == "financial"
    cf = next(d for d in q["dimensions"] if d["key"] == "cashflow")
    assert cf["basis"] == "not_applicable"
    assert q["coverage_pct"] >= 90


def test_positive_attention_never_lowers_risk():
    from sic.risk import score_risk
    f = {"debt_to_equity": 2.5, "current_ratio": 0.8, "fcf_margin": -5}
    a = score_risk(f, {"volatility_ann": 60}, {"covered": True, "negative_signals_30d": 0})
    b = score_risk(f, {"volatility_ann": 60}, {"covered": True, "negative_signals_30d": 0, "positive_signals_30d": 50})
    c = score_risk(f, {"volatility_ann": 60}, {"covered": True, "negative_signals_30d": 3})
    assert a["score"] == b["score"] and c["score"] > a["score"]


def test_market_metrics():
    from sic.market import compute_metrics
    idx = pd.bdate_range(end="2026-10-30", periods=230)
    close = pd.Series(np.linspace(100, 150, 230), index=idx)
    df = pd.DataFrame({"Open": close, "High": close * 1.02, "Low": close * 0.98, "Close": close,
                       "Volume": [1e6] * 229 + [3e6]}, index=idx)
    m = compute_metrics(df)
    assert m["sma200"] is not None and m["ema10"] > m["sma50"]
    assert round(m["rvol"], 1) == 3.0
    assert 3.9 < m["adr20"] < 4.2
    assert compute_metrics(df.head(30))["sma200"] is None    # unknown, nicht 0


# --------------------------------------------------------------- Trump ----
def _securities():
    return {"ACME": {"name": "Acme Robotics Inc."}, "TGT": {"name": "Target Corporation"},
            "CHIP": {"name": "Chipworks Corp"}}


def _rows(**kw):
    base = {"statement_at": (NOW - timedelta(days=1)).isoformat(), "quote": "Acme Robotics is a great company, big investment!",
            "source_name": "Truth Social", "source_url": "https://truthsocial.com/@x/posts/1",
            "original_url": "https://truthsocial.com/@x/posts/1", "verification": "", "direction_override": "",
            "symbols_override": "", "context": ""}
    base.update(kw)
    return [base]


def _process(rows):
    from sic.politics import build_alias_index, process_trump
    secs = _securities()
    return process_trump(rows, build_alias_index(secs), set(secs), NOW)


def test_trump_direct_mention_within_five_days_gets_highest_bonus():
    r = _process(_rows())
    assert r[0]["symbol"] == "ACME" and r[0]["mention_type"] == "direct"
    assert r[0]["bonus"]["active"] and r[0]["bonus"]["value"] == config.TRUMP_BONUS["direct"]
    assert r[0]["direction"] == "positive"


@pytest.mark.parametrize("age_days, active", [(4.9, True), (5.0, True), (5.01, False), (12, False)])
def test_trump_bonus_expires_after_five_calendar_days(age_days, active):
    r = _process(_rows(statement_at=(NOW - timedelta(days=age_days)).isoformat()))
    assert r[0]["bonus"]["active"] is active
    if not active:
        assert r[0]["quote"]            # Meldung bleibt in der Historie sichtbar


def test_trump_deadline_counts_from_original_not_republication():
    # Original vor 9 Tagen, Wiederveroeffentlichung gestern -> statement_at = Original
    r = _process(_rows(statement_at=(NOW - timedelta(days=9)).isoformat(), context="Repost vom Vortag"))
    assert not r[0]["bonus"]["active"]


def test_trump_no_bonus_without_date_or_verified_source():
    assert not _process(_rows(statement_at=""))[0]["bonus"]["active"]
    r = _process(_rows(source_url="https://random-blog.example/x", original_url="https://random-blog.example/x"))
    assert r[0]["verification"] == "Unverified" and not r[0]["bonus"]["active"]


def test_trump_negative_statement_not_positive():
    r = _process(_rows(quote="We will put massive tariffs on Acme Robotics, terrible!"))
    assert r[0]["direction"] == "negative" and r[0]["bonus"]["active"]   # relevant, aber negativ


def test_trump_sector_statement_gives_no_company_bonus():
    r = _process(_rows(quote="Semiconductors must be made in America!"))
    assert all(x["symbol"] is None and x["mention_type"] == "sector" and not x["bonus"]["active"] for x in r)
    assert "Halbleiter" in r[0]["sectors"]


def test_trump_ambiguous_name_needs_review():
    r = _process(_rows(quote="I went to Target yesterday, great"))
    tgt = [x for x in r if x["symbol"] == "TGT"]
    assert tgt and not tgt[0]["mapping_verified"] and not tgt[0]["bonus"]["active"]


def test_trump_indirect_requires_documented_rationale():
    (config.IMPORT_DIR / "aliases.csv").write_text(
        "symbol,alias,kind,rationale,source\nACME,the robot maker,indirect,,x\nCHIP,the chip giant,indirect,eindeutig belegt,https://x\n")
    r = _process(_rows(quote="The robot maker and the chip giant are doing great"))
    syms = {x["symbol"]: x for x in r}
    assert "ACME" not in syms                                    # ohne Begruendung keine Zuordnung
    assert syms["CHIP"]["mention_type"] == "indirect"
    assert syms["CHIP"]["bonus"]["value"] == config.TRUMP_BONUS["indirect"] < config.TRUMP_BONUS["direct"]


def test_trump_date_only_flagged():
    r = _process(_rows(statement_at=(NOW - timedelta(days=2)).date().isoformat()))
    assert r[0]["date_only"] is True


# ----------------------------------------------------- Signale/Duplikate --
def test_syndication_not_counted_as_independent():
    from sic.intelligence import market_intelligence
    from sic.signals import cluster_signals, make_signal, verify
    t = (NOW - timedelta(hours=3)).isoformat()
    sigs = [make_signal(symbols=["ACME"], category="m", signal_type="news", title="Acme Robotics raises full-year guidance after strong quarter",
                        url=f"https://site{i}.example/a", source=f"site{i}", published=t, summary="(Reuters)") for i in range(5)]
    sigs.append(make_signal(symbols=["ACME"], category="m", signal_type="news", title="Acme hires new chief financial officer",
                            url="https://other.example/b", source="other", published=t))
    cluster_signals(sigs)
    verify(sigs)
    assert sum(1 for s in sigs if s["independence"] == "original") == 2
    assert sum(1 for s in sigs if s["independence"] == "syndicated") == 4
    assert all(s["verification"] == "Unverified" for s in sigs[:5])   # gleicher Agenturtext != Bestaetigung


def test_primary_source_verified():
    from sic.signals import cluster_signals, make_signal, verify
    s = [make_signal(symbols=["ACME"], category="m", signal_type="company_news", title="Acme 8-K filing",
                     url="https://www.sec.gov/Archives/x", source="SEC", published=NOW.isoformat())]
    cluster_signals(s)
    verify(s)
    assert s[0]["verification"] == "Verified"


# ------------------------------------------------------ Insider/Ticker ----
FORM4 = """<?xml version="1.0"?><ownershipDocument>
<reportingOwner><reportingOwnerId><rptOwnerName>DOE JOHN</rptOwnerName></reportingOwnerId>
<reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>CEO</officerTitle></reportingOwnerRelationship></reportingOwner>
<nonDerivativeTable>
<nonDerivativeTransaction><transactionDate><value>2026-10-20</value></transactionDate>
<transactionCoding><transactionCode>P</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>1000</value></transactionShares><transactionPricePerShare><value>50</value></transactionPricePerShare></transactionAmounts></nonDerivativeTransaction>
<nonDerivativeTransaction><transactionDate><value>2026-10-20</value></transactionDate>
<transactionCoding><transactionCode>M</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>5000</value></transactionShares></transactionAmounts></nonDerivativeTransaction>
</nonDerivativeTable></ownershipDocument>"""


def test_form4_separates_open_market_from_exercise():
    from sic.insider import insider_summary, parse_form4
    tx = parse_form4(FORM4, "ACME", "https://www.sec.gov/x", "2026-10-22")
    assert [t["transaction_kind"] for t in tx] == ["buy", "option_exercise"]
    assert tx[0]["open_market"] and not tx[1]["open_market"]
    assert tx[0]["value"] == 50000 and tx[0]["reporting_delay_days"] == 2
    s = insider_summary("ACME", tx, days=10_000)
    assert s["open_market_buys"] == 1 and s["other_transactions"] == 1


def test_calendar_events_planned_with_timezone_and_postponement(monkeypatch):
    from sic import events
    monkeypatch.setattr(events, "STATE", config.STATE_DIR / "events.json")
    p = config.IMPORT_DIR / "market_calendar.csv"
    hdr = "event_time,timezone,title,category,markets,sectors,tickers,relevance_level,status,source_name,source_url,note\n"
    p.write_text(hdr + "2026-12-09T14:00:00,America/New_York,FOMC,Zentralbank,USA,,,high,planned,Fed,https://www.federalreserve.gov/x,\n")
    out = events.build_market_events(fetch=False, now=NOW)
    ev = out["upcoming"][0]
    assert ev["status"] == "planned" and ev["timezone"] == "America/New_York" and ev["time"] == "2026-12-09T19:00:00Z"
    p.write_text(hdr + "2026-12-16T14:00:00,America/New_York,FOMC,Zentralbank,USA,,,high,planned,Fed,https://www.federalreserve.gov/x,\n")
    ev = events.build_market_events(fetch=False, now=NOW)["upcoming"][0]
    assert ev["status"] == "postponed" and ev["changes"][0]["from"] == "2026-12-09T19:00:00Z"
    out = events.build_market_events(fetch=False, now=datetime(2026, 12, 20, tzinfo=timezone.utc))
    assert out["upcoming"] == [] and out["current"][0]["status"] == "occurred"


def test_calendar_requires_source():
    from sic import events
    (config.IMPORT_DIR / "market_calendar.csv").write_text(
        "event_time,timezone,title,category,markets,sectors,tickers,relevance_level,status,source_name,source_url,note\n"
        "2026-12-09T14:00:00,UTC,Ohne Quelle,X,USA,,,high,planned,,,\n")
    assert events.load_calendar(NOW) == []


# ------------------------------------------------------------- Export -----
def test_export_rejects_invalid_and_keeps_previous(tmp_path):
    from sic.export import publish
    out = tmp_path / "out"
    out.mkdir()
    (out / "summary.json").write_text('{"old": true}')
    res = publish({"summary.json": {"generated_at": "x"}}, {}, out)
    assert not res["published"]
    assert (out / "summary.json").read_text() == '{"old": true}'


def test_social_manipulation_flags():
    from sic.social import analyze
    posts = [{"id": str(i), "platform": "reddit", "author": "bot", "posted_at": (NOW - timedelta(hours=i)).isoformat(),
              "url": "", "text": "$ACME to the moon 100x load up", "engagement": 1, "symbols": ["ACME"]} for i in range(10)]
    r = analyze(posts, NOW)["ACME"]
    assert r["manipulation_risk"] == "hoch" and r["sentiment_basis"].startswith("algorithmisch")


def test_demo_pipeline_end_to_end(tmp_path):
    from sic.demo import build_demo
    res = build_demo(tmp_path / "demo")
    assert res["published"], res
    import json
    s = json.loads((tmp_path / "demo" / "summary.json").read_text())
    assert s["mode"] == "demo"


def test_index_parsers_handle_footnotes_and_quoted_csv(monkeypatch):
    from unittest import mock
    from sic import universe
    monkeypatch.setitem(config.INDEXES, "NDX", {**config.INDEXES["NDX"], "min_members": 2})
    t = pd.DataFrame({"Company": ["A", "B"], "Ticker[7]": ["AAPL", "BRK.B"], "GICS Sector[8]": ["IT", "Fin"]})
    with mock.patch.object(universe, "http_get") as g:
        g.return_value.text = t.to_html(index=False)
        assert [m.symbol for m in universe.fetch_wikipedia("NDX")] == ["AAPL", "BRK-B"]
        g.return_value.text = ('﻿iShares Russell 2000 ETF\n"Fund Holdings as of","Oct 30, 2026"\n\n'
                               '"Ticker","Name","Sector","Asset Class"\n"SMCI","SUPER MICRO","IT","Equity"\n'
                               '"XTSLA","CASH","Cash","Money Market"\n')
        assert [m.symbol for m in universe.fetch_ishares_csv("RUT")] == ["SMCI"]


def test_translation_adds_german_fields_and_keeps_original():
    from sic import translate
    calls = []

    def fake(texts):
        calls.append(list(texts))
        return [f"DE:{t}" for t in texts]

    sigs = [{"title": "Apple raises guidance after strong quarter"}, {"title": "EZB belässt den Leitzins unverändert"}]
    ev = [{"title": "Fed holds rates steady", "summary": ""}]
    r = translate.translate_items([(sigs, ["title"]), (ev, ["title", "summary"])], translator=fake)
    assert sigs[0]["title_de"].startswith("DE:") and sigs[0]["title"].startswith("Apple")
    assert "title_de" not in sigs[1]                  # deutscher Text wird nicht übersetzt
    assert r["new"] == 2
    translate.translate_items([(sigs, ["title"])], translator=fake)   # zweiter Lauf: aus dem Cache
    assert len(calls) == 1


# ------------------------------------------------- Superinvestoren (13F) ----
INFO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
<infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>037833100</cusip>
<value>1000000</value><shrsOrPrnAmt><sshPrnamt>5000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable>
<infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>037833100</cusip>
<value>200000</value><shrsOrPrnAmt><sshPrnamt>1000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable>
<infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>PUT</titleOfClass><cusip>037833100</cusip>
<value>50000</value><shrsOrPrnAmt><sshPrnamt>300</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt><putCall>Put</putCall></infoTable>
<infoTable><nameOfIssuer>OCCIDENTAL</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>674599105</cusip>
<value>800000</value><shrsOrPrnAmt><sshPrnamt>9000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable>
</informationTable>"""


def test_13f_parse_aggregates_and_separates_options():
    from sic.superinvestors import parse_info_table
    rows = {(r["cusip"], r["put_call"]): r for r in parse_info_table(INFO_XML)}
    assert rows[("037833100", None)]["shares"] == 6000 and rows[("037833100", None)]["value"] == 1_200_000
    assert rows[("037833100", "put")]["shares"] == 300


def test_13f_compare_quarters():
    from sic.superinvestors import compare
    cur = [{"cusip": "A", "issuer": "A", "title": "COM", "put_call": None, "shares": 150, "value": 600},
           {"cusip": "N", "issuer": "N", "title": "COM", "put_call": None, "shares": 10, "value": 400},
           {"cusip": "P", "issuer": "P", "title": "PUT", "put_call": "put", "shares": 5, "value": 99}]
    prev = [{"cusip": "A", "issuer": "A", "title": "COM", "put_call": None, "shares": 100, "value": 400},
            {"cusip": "S", "issuer": "S", "title": "COM", "put_call": None, "shares": 50, "value": 300}]
    pos = {p["cusip"]: p for p in compare(cur, prev)}
    assert pos["A"]["action"] == "increased" and pos["A"]["shares_change_pct"] == 50.0
    assert pos["N"]["action"] == "new" and pos["N"]["weight_pct"] == 40.0     # Optionen nicht im Depotwert
    assert pos["S"]["action"] == "sold_out" and "P" not in pos


def test_13f_wrong_cik_is_skipped(monkeypatch):
    from unittest import mock
    from sic import superinvestors
    (config.IMPORT_DIR / "superinvestors.csv").write_text(
        "cik,manager,fund,expected_name\n1067983,Warren Buffett,Berkshire Hathaway,BERKSHIRE HATHAWAY\n")
    with mock.patch.object(superinvestors, "http_get") as g:
        g.return_value.json.return_value = {"name": "SOME OTHER FUND LLC", "filings": {"recent": {}}}
        r = superinvestors.build({}, fetch=True)
    assert r["managers"] == [] and "übersprungen" in r["errors"][0]["error"]


def test_13f_build_end_to_end(monkeypatch):
    from unittest import mock
    from sic import superinvestors
    (config.IMPORT_DIR / "superinvestors.csv").write_text(
        "cik,manager,fund,expected_name\n1067983,Warren Buffett,Berkshire Hathaway,BERKSHIRE\n")
    sub = {"name": "BERKSHIRE HATHAWAY INC", "filings": {"recent": {
        "form": ["13F-HR", "4", "13F-HR"], "accessionNumber": ["0001-26-000002", "x", "0001-26-000001"],
        "reportDate": ["2026-09-30", "", "2026-06-30"], "filingDate": ["2026-11-14", "", "2026-08-14"]}}}
    prev_xml = INFO_XML.replace("<sshPrnamt>9000</sshPrnamt>", "<sshPrnamt>3000</sshPrnamt>")

    def fake(url, **kw):
        m = mock.Mock()
        if "submissions" in url:
            m.json.return_value = sub
        elif url.endswith("index.json"):
            m.json.return_value = {"directory": {"item": [{"name": "primary_doc.xml"}, {"name": "info.xml"}]}}
        else:
            m.text = INFO_XML if "000126000002" in url else prev_xml
        return m
    monkeypatch.setattr(superinvestors, "map_cusips", lambda c, n, u: {"037833100": "AAPL", "674599105": "OXY"})
    with mock.patch.object(superinvestors, "http_get", side_effect=fake):
        r = superinvestors.build({"AAPL": {"name": "Apple Inc."}, "OXY": {"name": "Occidental"}}, fetch=True)
    m = r["managers"][0]
    assert m["report_date"] == "2026-09-30" and m["holdings"] == 2
    oxy = next(s for s in r["stocks"] if s["symbol"] == "OXY")
    assert oxy["buyers"] == 1 and oxy["managers"][0]["action"] == "increased"


# ---------------------------------------------------- Insider-Tagesindex ----
DAILY_IDX = """Description:           Daily Index of EDGAR Dissemination Feed by Form Type
Form Type   Company Name                                                  CIK         Date Filed  File Name
---------------------------------------------------------------------------------------------------------------------------------------------
3           SMITH JOHN                                                    1900001     20261030    edgar/data/1900001/0001-26-000001.txt
4           APPLE INC                                                     320193      20261030    edgar/data/320193/0001-26-000002.txt
4           COOK TIMOTHY D                                                1214156     20261030    edgar/data/320193/0001-26-000002.txt
4/A         APPLE INC                                                     320193      20261030    edgar/data/320193/0001-26-000003.txt
"""


def test_daily_index_parsing_and_xml_extraction():
    from sic.insider import _extract_xml, parse_daily_index
    rows = parse_daily_index(DAILY_IDX)
    assert [r["cik"] for r in rows] == [320193, 1214156] and all(r["form"] == "4" for r in rows)
    txt = f"<SEC-DOCUMENT>\n<DOCUMENT>\n<TYPE>4\n<TEXT>\n<XML>\n{FORM4}\n</XML>\n</TEXT>"
    assert "<ownershipDocument>" in _extract_xml(txt)


def test_cluster_buys():
    from sic.insider import cluster_buys
    mk = lambda who, kind="buy", om=True: {"symbol": "ACME", "insider": who, "transaction_kind": kind, "open_market": om,  # noqa: E731
                                           "transaction_date": "2026-10-28", "value": 1000.0, "role": "Director"}
    items = [mk("A"), mk("B"), mk("C", "option_exercise", False), {**mk("X"), "symbol": "SOLO"}]
    c = cluster_buys(items, now=NOW)
    assert [x["symbol"] for x in c] == ["ACME"] and c[0]["insiders"] == 2


def test_13f_prefixed_namespaces_and_thousands():
    from sic.superinvestors import _value_in_dollars, parse_info_table
    xml = ('<?xml version="1.0"?><ns1:informationTable xmlns:ns1="http://www.sec.gov/edgar/document/thirteenf/informationtable" '
           'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="x y"><ns1:infoTable>'
           '<ns1:nameOfIssuer>APPLE</ns1:nameOfIssuer><ns1:cusip>037833100</ns1:cusip><ns1:value>2000</ns1:value>'
           '<ns1:shrsOrPrnAmt><ns1:sshPrnamt>10000</ns1:sshPrnamt><ns1:sshPrnamtType>SH</ns1:sshPrnamtType></ns1:shrsOrPrnAmt>'
           '</ns1:infoTable></ns1:informationTable>')
    rows = parse_info_table(xml)
    assert rows[0]["shares"] == 10000
    _value_in_dollars(rows, "2026-06-30")       # 0,20 USD je Aktie -> Meldung in Tausend
    assert rows[0]["value"] == 2_000_000


def test_13f_stale_manager_excluded_from_rankings(monkeypatch):
    from sic import superinvestors
    rows = [{"cusip": "X", "issuer": "X", "title": "COM", "put_call": None, "shares": 10.0, "value": 100.0}]
    (config.IMPORT_DIR / "superinvestors.csv").write_text(
        "cik,manager,fund,expected_name\n1,A,A Fund,\n2,B,B Fund,\n")
    from sic.util import write_json_atomic
    write_json_atomic(config.STATE_DIR / "13f_index.json", {
        "1": {"name": "A", "filings": [{"accession": "a1", "report_date": "2026-06-30", "filed_at": "2026-08-14"}]},
        "2": {"name": "B", "filings": [{"accession": "b1", "report_date": "2023-12-31", "filed_at": "2024-02-14"}]}})
    for k in ("1-a1", "2-b1"):
        write_json_atomic(config.STATE_DIR / "13f" / f"{k}-v2.json", rows)
    r = superinvestors.build({}, fetch=False)
    assert [m["stale"] for m in r["managers"]] == [False, True]
    assert r["stocks"][0]["holders"] == 1


# --------------------------------------------------------- Politiker-Trades --
def test_house_index_and_ptr_text():
    from sic.congress import parse_house_index, parse_house_ptr_text
    xml = (b"<FinancialDisclosure><Member><Prefix>Hon.</Prefix><Last>Doe</Last><First>Jane</First><Suffix/>"
           b"<FilingType>P</FilingType><StateDst>CA11</StateDst><Year>2026</Year><FilingDate>10/27/2026</FilingDate>"
           b"<DocID>20031234</DocID></Member><Member><Last>X</Last><First>Y</First><FilingType>O</FilingType>"
           b"<DocID>1</DocID></Member></FinancialDisclosure>")
    idx = parse_house_index(xml)
    assert idx == [{"doc_id": "20031234", "name": "Jane Doe", "state_district": "CA11", "year": "2026", "filed": "2026-10-27"}]
    text = ("ID Owner Asset Transaction Type Date Notification Date Amount Cap. Gains > $200?\n"
            "SP NVIDIA Corporation - Common Stock (NVDA) [ST] P 10/01/2026 10/02/2026 $250,001 -\n$500,000\n"
            "F S : New\nApple Inc. (AAPL) [ST] S (partial) 09/15/2026 09/20/2026 $1,001 - $15,000\n"
            "US Treasury Bill (912797) [GS] P 09/15/2026 09/20/2026 $1,001 - $15,000")
    rows = parse_house_ptr_text(text)
    assert [(r["ticker"], r["tx"], r["owner"]) for r in rows] == [("NVDA", "purchase", "Ehepartner"), ("AAPL", "sale_partial", "Selbst")]
    assert rows[0]["amount_min"] == 250001 and rows[0]["amount_max"] == 500000


def test_senate_ptr_html():
    from sic.congress import parse_senate_ptr_html
    html = ("<table><thead><tr><th>#</th><th>Transaction Date</th><th>Owner</th><th>Ticker</th><th>Asset Name</th>"
            "<th>Asset Type</th><th>Type</th><th>Amount</th><th>Comment</th></tr></thead><tbody>"
            "<tr><td>1</td><td>10/03/2026</td><td>Spouse</td><td><a href='x'>MSFT</a></td><td>Microsoft Corp</td>"
            "<td>Stock</td><td>Purchase</td><td>$15,001 - $50,000</td><td>--</td></tr>"
            "<tr><td>2</td><td>10/03/2026</td><td>Self</td><td>--</td><td>Muni Bond</td><td>Municipal Security</td>"
            "<td>Purchase</td><td>$1,001 - $15,000</td><td>--</td></tr></tbody></table>")
    rows = parse_senate_ptr_html(html)
    assert len(rows) == 1 and rows[0]["ticker"] == "MSFT" and rows[0]["tx"] == "purchase" and rows[0]["owner"] == "Ehepartner"
    assert rows[0]["transaction_date"] == "2026-10-03"


# ------------------------------------------------------------- Termine -----
def test_nasdaq_calendars():
    from sic.corporate_events import parse_dividends, parse_earnings
    e = parse_earnings({"data": {"rows": [{"symbol": "AAPL", "time": "time-after-hours", "epsForecast": "$1.60",
                                           "noOfEsts": "12", "fiscalQuarterEnding": "Sep/2026"}]}}, "2026-11-05")
    assert e[0]["time"] == "nach Börsenschluss" and e[0]["eps_forecast"] == 1.6 and e[0]["date"] == "2026-11-05"
    v = parse_dividends({"data": {"calendar": {"rows": [{"symbol": "BRK.B", "dividend_Ex_Date": "11/07/2026",
                                                        "payment_Date": "11/20/2026", "dividend_Rate": 0.26}]}}})
    assert v[0]["symbol"] == "BRK-B" and v[0]["date"] == "2026-11-07" and v[0]["amount"] == 0.26


def test_corporate_events_window(monkeypatch):
    from sic import corporate_events
    from sic.util import write_json_atomic
    write_json_atomic(config.STATE_DIR / "corporate_events.json", {"days": {
        "2026-11-03": [{"symbol": "AAPL", "type": "earnings", "date": "2026-11-03"}],
        "2026-12-30": [{"symbol": "AAPL", "type": "earnings", "date": "2026-12-30"}]}})
    out = corporate_events.build({"AAPL", "SAP.DE"}, {"SAP.DE": {"data": {"next_earnings_ts": NOW.timestamp() + 86400 * 4}}},
                                 fetch=False, now=NOW)
    assert [x["date"] for x in out["AAPL"]] == ["2026-11-03"] and out["AAPL"][0]["days_until"] == 3
    assert out["SAP.DE"][0]["type"] == "earnings"


# -------------------------------------------------------------- Social -----
def test_symbol_resolver_avoids_common_words():
    from sic.social import symbol_resolver
    r = symbol_resolver({"NVDA", "AMD", "ALL", "IT", "ON", "SAP.DE", "GME"})
    assert r("YOLO on NVDA and $AMD, ALL IN, IT is time") == ["AMD", "NVDA"]
    assert r("SAP schlägt Erwartungen, $GME") == ["GME", "SAP.DE"]


def test_stocktwits_labels_drive_sentiment():
    from sic.social import analyze
    t = (NOW - timedelta(hours=2)).isoformat()
    posts = [{"id": str(i), "platform": "stocktwits", "author": f"u{i}", "posted_at": t, "url": "", "text": "x",
              "engagement": 1, "symbols": ["NVDA"], "sentiment_label": lab} for i, lab in enumerate(["Bullish", "Bullish", "Bearish", None])]
    a = analyze(posts, NOW)["NVDA"]
    assert a["bullish_7d"] == 2 and a["bearish_7d"] == 1 and a["sentiment_7d"] == 0.25


# ------------------------------------------------------- 13D/13G-Signale ----
def test_big_stakes_from_daily_index():
    from sic.insider import _collect_stakes, load_stakes, parse_daily_index, STAKE_FORMS
    idx = ("SC 13D/A     OCCIDENTAL PETROLEUM CORP      797468   20261028   edgar/data/797468/0001-26-000009.txt\n"
           "SC 13D/A     BERKSHIRE HATHAWAY INC         1067983  20261028   edgar/data/797468/0001-26-000009.txt\n"
           "SC 13G       OTHER CO                       555      20261028   edgar/data/555/0001-26-000010.txt\n")
    rows = parse_daily_index(idx, STAKE_FORMS)
    _collect_stakes(rows, {797468: "OXY"}, {1067983: "Warren Buffett"}, "2026-10-28")
    st = load_stakes(now=NOW)
    assert len(st) == 1 and st[0]["symbol"] == "OXY" and st[0]["activist"] and st[0]["amendment"]


# --------------------------------------------------------------- Swing -----
def _ohlc(closes, vol=2e6, last_vol=None):
    idx = pd.bdate_range(end="2026-10-30", periods=len(closes))
    c = pd.Series(closes, index=idx, dtype=float)
    o = c.shift(1).fillna(c.iloc[0])
    df = pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.01, "Low": np.minimum(o, c) * 0.99, "Close": c,
                       "Volume": [vol] * len(c)}, index=idx)
    if last_vol:
        df.iloc[-1, df.columns.get_loc("Volume")] = last_vol
    return df


def test_swing_breakout_and_plan():
    from sic.setups import ENTRY, evaluate
    closes = list(np.linspace(50, 100, 300)) + [98, 96, 95, 97, 100, 102.5]
    r = evaluate(_ohlc(closes, last_vol=4e6), market_cap=5e9)
    assert "S03" in r["hits"] and r["tech"]["rvol"] > 1.5
    p = r["plan"]
    assert abs(p["entry_max"] - p["trigger"] * 1.02) < 1e-6
    assert abs((p["trigger"] - p["stop"]) - ENTRY["stop_atr"] * r["tech"]["atr14"]) < 1e-6
    assert abs(p["target_1"] - (p["trigger"] + 2 * (p["trigger"] - p["stop"]))) < 1e-6


def test_swing_s01_needs_reversal_candle():
    from sic.setups import evaluate
    down = list(np.linspace(100, 60, 120))
    df = _ohlc(down)
    r = evaluate(df)
    assert r["criteria"]["S01"]["RSI zuletzt < 35"] and "S01" not in r["hits"]      # keine Umkehrkerze
    i = df.index[-1] + pd.offsets.BDay(1)
    df.loc[i] = {"Open": 59.0, "High": 61.5, "Low": 58.8, "Close": 61.2, "Volume": 3e6}
    df.iloc[-2, df.columns.get_loc("Open")] = 60.8   # Vortag rot und vom heutigen Körper umschlossen
    assert "S01" in evaluate(df)["hits"]


def test_s02_market_cap_rechecked_in_assembly():
    from sic.run import _swing
    sw = {"criteria": {"S02": {"Marktkap. > 1 Mrd.": True, "Kurs > 10": True}}, "hits": ["S02"]}
    assert _swing({"swing": sw}, 5e8)["hits"] == [] and _swing({"swing": sw}, 2e9)["hits"] == ["S02"]


# ------------------------------------------------------------- Alarme ------
def test_watchlist_newest_file_and_alert_dedup(monkeypatch):
    from sic import alerts
    d = config.IMPORT_DIR / "watchlist"
    d.mkdir()
    (d / "2026-10-01.csv").write_text("symbol\nOLD\n")
    (d / "2026-11-01-0700.csv").write_text("symbol\nNVDA\nmsft\n")
    wl, f = alerts.load_watchlist()
    assert wl == ["MSFT", "NVDA"] and f == "2026-11-01-0700.csv"
    stock = {"symbol": "NVDA", "status": "active", "market": {"price_date": "2026-10-30"},
             "events": [{"type": "earnings", "date": "2026-11-02", "days_until": 1, "source_url": "x"}],
             "swing": {"hits": ["S03"], "filter_pass": True, "tech": {"rvol": 2.0}, "plan": {"trigger": 100.0, "stop": 95.0}}}
    gen = alerts.generate(stocks=[stock], insiders=[], clusters=[], superinv={"managers": []}, stakes=[], pol_trades=[],
                          trump=[], social_stats={}, watchlist=wl, now=NOW)
    assert sorted(a["kind"] for a in gen) == ["earnings", "setup"]   # kein Digest: Zahlen in < 5 Tagen
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    r1 = alerts.process(gen, wl, f, now=NOW)
    r2 = alerts.process(gen, wl, f, now=NOW)
    assert r1["new_count"] == 2 and r2["new_count"] == 0 and len(r2["history"]) == 2


# ------------------------------------------------- Zusammenfluss/Bericht ----
def _stock(sym, **kw):
    base = {"symbol": sym, "name": sym, "status": "active", "sector": None, "indexes": [], "market": {"last_close": 10, "perf_20d": 1},
            "insider": {"open_market_buys": 0, "distinct_buyers": 0}, "superinvestors": None, "politicians": None,
            "quality": {"score": 50}, "swing": None, "social": None, "political": {"direction": "keine"},
            "risk": {"level": "moderat"}, "events": [], "market_cap": 1e10}
    base.update(kw)
    return base


def test_confluence_counts_independent_signals():
    from sic.report import confluence
    a = _stock("AAA", insider={"open_market_buys": 3, "distinct_buyers": 2}, quality={"score": 80},
               superinvestors={"buyers": 2, "new_buyers": 1, "sellers": 0, "holders": 3, "sold_out": 0})
    b = _stock("BBB", quality={"score": 90})                          # nur ein Signal -> nicht gelistet
    c = _stock("CCC", insider={"open_market_buys": 1, "distinct_buyers": 1}, politicians={"buys": 1, "sells": 0},
               risk={"level": "hoch"}, events=[{"type": "earnings", "days_until": 2, "date": "2026-11-02"}])
    rows = confluence([a, b, c])
    assert [r["symbol"] for r in rows] == ["AAA", "CCC"] and rows[0]["count"] == 3
    assert "Risiko hoch" in rows[1]["warnings"] and any("Zahlen" in w for w in rows[1]["warnings"])


def test_report_day_and_earnings():
    from sic.report import build_report
    s = _stock("AAPL", events=[{"type": "earnings", "date": "2026-11-02", "days_until": 1, "time": "nach Börsenschluss"}])
    evening = datetime(2026, 10, 30, 21, 45, tzinfo=timezone.utc)     # Freitagabend -> Bericht für Montag
    r = build_report(stocks=[s], candidates=[], alerts_history=[], market_events={"upcoming": []}, insiders_clusters=[],
                     superinv={"managers": []}, pol_trades=[], trump=[], social_stats={}, watchlist=["AAPL"], conf=[], now=evening)
    assert r["report_date"] == "2026-11-02" and r["weekday"] == "Montag"
    assert r["earnings"][0]["symbol"] == "AAPL" and r["earnings"][0]["watchlist"]


def test_single_word_or_generic_names_are_not_verified():
    from sic.politics import build_alias_index, link_entities
    secs = {"AIG": {"name": "American International Group, Inc."}, "REF": {"name": "Reformation"}}
    idx = build_alias_index(secs)
    hits = link_entities("Presidential Message on Reformation Day. American fishermen first.", idx, set(secs))
    assert all(not h["mapping_verified"] for h in hits) and "AIG" not in {h["symbol"] for h in hits}


def test_strategies_and_trend():
    from sic.setups import evaluate
    up = list(np.linspace(50, 100, 300))
    r = evaluate(_ohlc(up))
    assert r["tech"]["trend"] == "up" and {"DSM", "RSI2", "QM"} <= set(r["criteria"])
    # starker Rücksetzer im Aufwärtstrend -> RSI(2) sehr niedrig
    r2 = evaluate(_ohlc(up + [97, 93, 90]))
    assert r2["criteria"]["RSI2"]["RSI(2) < 10"] and r2["criteria"]["RSI2"]["über SMA 200"]
    assert "RSI2" in r2["hits"]
