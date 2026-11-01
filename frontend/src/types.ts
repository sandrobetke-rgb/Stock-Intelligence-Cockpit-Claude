// Typen der JSON-Endpunkte (Backend sic/run.py -> assemble)

export type Verification = "Verified" | "Partially Verified" | "Unverified" | "Disputed" | "False" | "Outdated";
export type Direction = "positive" | "negative" | "mixed" | "neutral" | "unclear" | "keine";

export interface Meta { generated_at: string; schema_version: string; mode: "live" | "demo" }

export interface IndexInfo {
  code: string; name: string; source: string; checked_at?: string; members: number;
  status: "ok" | "error"; message?: string | null; limitation?: string | null;
}

export interface Summary extends Meta {
  universe: {
    active: number; archived: number; index_positions: number; indexes: IndexInfo[];
    upcoming_changes: { index: string; symbol: string; action: string; effective_date: string; source: string; name?: string }[];
    built_at?: string;
  };
  coverage: { prices_pct: number; fundamentals_pct: number; quality_scored_pct: number; avg_quality_coverage_pct: number; data_errors: number };
  quality_distribution: Record<string, number>;
  freshness: { latest_price_date: string | null; signals_24h: number; trump_bonus_active: number; upcoming_events: number };
  verification_counts: Record<Verification, number>;
  sources: { area: string; source: string; status: string; limitation: string }[];
  steps: { step: string; status: "ok" | "error"; seconds: number; message?: string }[];
  errors: { step: string; message?: string }[];
  disclaimer: string;
}

export interface StockRow {
  symbol: string; name: string; region: string; currency: string; sector: string | null; industry: string | null;
  indexes: string[]; status: "active" | "archived"; status_reason: string | null;
  data_status: "ok" | "warning" | "error"; data_flags: string[];
  market: { last_close: number | null; price_date: string | null; perf_20d: number | null; perf_63d: number | null;
    adr20: number | null; rvol: number | null; ema10: number | null; ema21: number | null; sma50: number | null; sma200: number | null };
  market_cap: number | null; market_cap_currency: string | null;
  quality: { score: number | null; coverage_pct: number; model: string; dimensions: Record<string, number | null> };
  risk: { score: number | null; level: string; coverage_pct: number; top_factors: string[] };
  market_intelligence: { score: number | null; drivers: string[]; independent_7d: number; independent_24h: number };
  political: { relevance: number; trump_bonus: number; trump_bonus_active: boolean; direction: Direction;
    negative_signals_30d: number; positive_signals_30d: number };
  social: { mentions_7d: number; manipulation_risk: string } | null;
  superinvestors: { holders: number; buyers: number; new_buyers: number; sellers: number; sold_out: number } | null;
  insider: { open_market_buys: number; open_market_sells: number; buy_value: number; sell_value: number; distinct_buyers: number; other_transactions: number };
}

export interface Signal {
  id: string; symbols: string[]; category: string; signal_type: string; title: string; summary: string;
  source: string; source_domain: string; url: string; published_at: string | null; date_only: boolean;
  captured_at: string; fingerprint: string; primary_source: boolean; cluster_id: string;
  independence: "original" | "syndicated" | "copy"; verification: Verification; title_de?: string;
  fact_check?: { status: string; note: string; source: string };
}

export interface RadarRow {
  symbol: string; name: string; score: number; drivers: string[]; independent_24h: number; independent_7d: number;
  quality: number | null; risk: number | null; risk_level: string; political_direction: Direction; political: number; indexes: string[]; sector: string | null;
}

export interface TrumpMention {
  id: string; statement_id: string; quote: string; quote_de?: string; source_name: string; source_url: string; statement_at: string | null;
  date_only: boolean; timezone: string; captured_at: string; verification: Verification; direction: Direction;
  direction_basis: string; direction_cues: string[]; context: string; sectors: string[];
  symbol: string | null; mention_type: "direct" | "indirect" | "sector" | "general"; mapping_verified: boolean;
  matched: string | null; mapping_rationale: string | null;
  bonus: { active: boolean; value: number; reason: string; expires_at: string | null; age_days: number | null };
}

export interface MarketEvent {
  id: string; kind: "news" | "event"; title: string; summary: string; title_de?: string; summary_de?: string; time: string | null; local_time?: string;
  timezone: string; date_only: boolean; source: string; url: string; relevance: string; relevance_level: string;
  categories: string[]; markets: string[]; sectors: string[]; tickers: string[]; direction: Direction;
  verification: Verification; status: "planned" | "published" | "occurred" | "postponed" | "cancelled";
  captured_at: string; last_checked_at: string; changes: { changed_at: string; field: string; from: string | null; to: string | null }[];
}

export interface Insider {
  id: string; symbol: string; insider: string; role: string; transaction_kind: string; transaction_label: string;
  open_market: boolean; rule_10b5_1_plan: boolean; transaction_date: string | null; filed_at: string | null;
  reporting_delay_days: number | null; shares: number | null; price: number | null; value: number | null; currency: string;
  source: string; source_url: string;
}
export interface Institution {
  id: string; institution: string; symbol: string; report_period: string; filed_at: string; publication_delay_days: number | null;
  shares: number | null; shares_change: number | null; value_usd: number | null; position_status: string; pct_outstanding: number | null;
  source_url: string; note: string;
}
export interface PoliticalTrade {
  id: string; politician: string; chamber: string; party: string; symbol: string; transaction_type: string;
  transaction_date: string | null; disclosure_date: string | null; reporting_delay_days: number | null;
  amount_range: [number | null, number | null]; source_url: string; note: string;
}
export interface PoliticalEvent {
  id: string; event_at: string | null; date_only: boolean; title: string; title_de?: string; category: string; symbols: string[];
  sectors: string[]; direction: Direction; source_url: string; verification: Verification; note: string;
}

export interface SocialStat {
  mentions_24h: number; mentions_7d: number; mentions_30d: number; change_vs_baseline_pct: number | null;
  engagement_7d: number; sentiment_7d: number | null; sentiment_basis: string; platforms: string[];
  manipulation_flags: string[]; manipulation_risk: string;
  top_posts: { platform: string; author: string; posted_at: string; url: string; text: string; engagement: number }[];
}

export interface QualityDim {
  key: string; label: string; weight: number; score: number | null; basis: string; coverage: number | null;
  metrics: { key: string; label: string; unit: string; value: number | null; points: number | null; status: string }[];
}
export interface RiskFactor {
  key: string; label: string; value: number | null; unit: string; severity: number | null; weight: number; status: string;
  description?: string; source?: string;
}

export interface CompanyDetail extends Meta {
  profile: StockRow & { first_seen: string; archived_at: string | null; country: string | null };
  memberships: { index: string; since: string; until: string | null; date_basis?: string; exit_basis?: string }[];
  market_detail: (StockRow["market"] & { flags: string[]; volatility_ann: number | null; move_zscore?: number | null }) | null;
  quality_detail: { score: number | null; status: string; coverage_pct: number; model: string; dimensions: QualityDim[];
    source: string; source_url: string | null; as_of: string | null; fiscal_year_end: string | null; currency: string | null; note: string };
  risk_detail: { score: number | null; level: string; coverage_pct: number; factors: RiskFactor[]; top_factors: string[]; unknown_factors: string[] };
  intelligence_detail: { score: number | null; components: Record<string, number | null>;
    windows: Record<string, { signals: number; independent: number; duplicates: number; sources: number; primary: number; analyst_changes: number; verified: number }>;
    drivers: string[]; note: string };
  political_detail: StockRow["political"] & { mentions_total: number; events_30d: number; next_expiry: string | null };
  trump_mentions: TrumpMention[]; political_events: PoliticalEvent[]; signals: Signal[];
  insiders: Insider[]; institutions: Institution[]; political_trades: PoliticalTrade[]; superinvestors: SiHolder[];
  social_detail: SocialStat | null;
  history: { date: string; symbol: string; from: string; to: string; reason: string | null }[];
}

export interface SiPosition {
  cusip: string; issuer: string; title: string; put_call: string | null; shares: number; value: number;
  weight_pct: number; action: "new" | "increased" | "reduced" | "unchanged" | "sold_out" | "unknown";
  shares_change_pct: number | null; prev_shares: number; symbol: string | null; in_universe: boolean;
}
export interface SiManager {
  cik: number; manager: string; fund: string; sec_name: string; report_date: string; filed_at: string; filing_url: string;
  portfolio_value: number; holdings: number; new: number; sold_out: number; positions: SiPosition[];
}
export interface SiHolder { manager: string; fund: string; action: SiPosition["action"]; weight_pct: number; shares_change_pct: number | null; value: number; report_date: string }
export interface SiStock {
  symbol: string | null; cusip: string; issuer: string; in_universe: boolean; holders: number; buyers: number;
  new_buyers: number; sellers: number; sold_out: number; value: number; managers: SiHolder[];
}
export interface ClusterBuy { symbol: string; insiders: number; transactions: number; value: number; roles: string[]; first: string; last: string }
