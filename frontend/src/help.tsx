import type { ReactNode } from "react";

/** Aufklappbare Kurz-Erklärung je Seite („So liest du diese Seite“). Schlüssel = Seitentitel bzw. dessen Anfang. */
const MARKS = <li><b>Kennzeichen an jeder Aktie:</b> ☆ = Watchlist, Buchstabe A–E = Qualitätsnote (A sehr gut … E schwach, ? = zu wenig Daten),
  Pfeil = Trend (↗ aufwärts, ↘ abwärts, → seitwärts), schwarzes Kürzel = erfülltes Swing-Setup, blaues Kästchen = Termin (Zahlen, Ex-Dividende).</li>;

export const HELP: Record<string, ReactNode> = {
  Tagesbericht: <ul>
    <li>Zusammenfassung für den Handelstag, kommt jeden Morgen auch als Push aufs Handy.</li>
    <li>Reihenfolge nach Wichtigkeit: Insiderkäufe → Politiker-Käufe → Trump-Nennungen → Social Media → Termine → deine Watchlist → Signal-Zusammenfluss → Swing-Kandidaten → Superinvestoren.</li>
    <li>Jeder Eintrag ist ein Hinweis zum Selbstprüfen, keine Kaufempfehlung. Klick auf das Kürzel öffnet die Aktienseite.</li>
    {MARKS}
  </ul>,
  Dashboard: <ul>
    <li>Gesamtüberblick: wie viele Aktien erfasst sind, wie gut die Daten abgedeckt sind und wie sich die Qualitätsnoten verteilen.</li>
    <li><b>Quellenstatus:</b> zeigt, ob jede Datenquelle im letzten Lauf funktioniert hat (ok / Fehler / abgeschaltet).</li>
    <li>Unten links steht immer der Datenstand. Ist er älter als 30 Stunden, erscheint oben ein gelber Hinweis.</li>
  </ul>,
  "Watchlist & Alarme": <ul>
    <li>Aktien mit ☆ markieren und hier auf <b>Speichern</b> klicken – erst dann kennt der nächtliche Lauf deine Watchlist.</li>
    <li>Zu Watchlist-Aktien kommt ein Push bei: Insiderkauf, Superinvestor, Großbeteiligung, Politiker-Trade, Trump-Nennung, Zahlen in ≤ 2 Tagen, neues Setup, Social-Media- oder Wikipedia-Spitze.</li>
    <li>Jedes Ereignis wird nur einmal gemeldet. Der Alarmverlauf unten zeigt alles der letzten Zeit.</li>
  </ul>,
  "Swing-Setups": <ul>
    <li>Deine Screener S01–S04 und Strategien (Daily Swing Master, Überdehnter Rücksetzer, Qullamaggie) auf Tagesbasis nach US-Börsenschluss.</li>
    <li><b>Abendfilter</b> (Haken): grüne Kerze, RelVol ≥ 1,2, RSI ≤ 65, ATR% 1,5–5, über EMA 200. Er siebt stark – 0 Kandidaten ist ein gültiges Ergebnis. Haken weg = alle Treffer.</li>
    <li><b>Auslöser</b> = Kurs, über dem die 1H-Kerze schließen muss; <b>bis</b> = höchstens 2 % darüber einsteigen. <b>Stopp</b> = Auslöser − 1,5 × ATR, <b>Ziel 1</b> = 2 : 1.</li>
    <li>Kapital eintragen → Stückzahl bei 1 % Risiko (höchstens Kapital ÷ 3). Das Kapital bleibt nur in deinem Browser.</li>
    <li>Strategien sind Annäherungen an deine Pine-Skripte – immer im Chart gegenprüfen. Freitags keine neuen Trades.</li>
  </ul>,
  "Signal-Zusammenfluss": <ul>
    <li>Aktien, bei denen <b>mindestens zwei unabhängige</b> positive Signale zusammenkommen: Insiderkauf, Superinvestoren kaufen, Politiker kaufen, Qualität ≥ 70, Swing-Setup, positive Social-Media-Stimmung ohne Hype, positive Politik.</li>
    <li>Es wird nur gezählt, kein Gesamtscore gebildet. Je mehr Signale, desto weiter oben.</li>
    <li><b>Warnungen</b> stehen rot daneben (Zahlen in ≤ 5 Tagen, hohes Risiko, Superinvestoren verkaufen, Hype, negative Politik) – die wiegen schwer.</li>
  </ul>,
  "Opportunity Radar": <ul>
    <li>Welche Aktien gerade in vielen <b>unabhängigen</b> Quellen auftauchen (News, Social Media, Insider, Politik).</li>
    <li><b>Market Intelligence</b> 0–100 = Stärke dieser Aufmerksamkeit. Kopien derselben Agenturmeldung zählen nur einmal.</li>
    <li>Aufmerksamkeit ist kein Qualitätsmerkmal – immer Qualitätsnote und Risiko mit ansehen.</li>
  </ul>,
  "Trump Mention Radar": <ul>
    <li>Nur Aktien, die Trump bzw. das Weiße Haus <b>gesichert</b> genannt hat. Allgemeine Aussagen und Wortzufälle sind ausgeblendet.</li>
    <li><b>Bonus</b>: direkte Nennung +30, eindeutig indirekt +15 – gilt nur 5 Tage ab der Originalaussage, danach „verfallen“.</li>
    <li><b>Richtung</b> positiv/negativ/gemischt: wie die Aussage für das Unternehmen klingt. Negative Nennungen sind kein Kaufsignal.</li>
  </ul>,
  "Markt- & Wirtschaftsticker": <ul>
    <li>Laufband oben und diese Seite: Meldungen von Fed, EZB und US-Arbeitsmarktstatistik sowie geplante Termine (Zinsentscheide, Inflationsdaten).</li>
    <li><b>Geplant</b> = Termin steht im Kalender; „nur Datum“ = Uhrzeit noch unbekannt. Hohe Relevanz ist farbig markiert.</li>
    <li>An wichtigen Terminen schwanken die Märkte oft stärker – gut für die Einstiegsplanung.</li>
  </ul>,
  "Quality Stocks": <ul>
    <li>Fundamentale Qualität 0–100 aus Wachstum, Margen, Bilanz, Cashflow, Marktposition, Potenzial und Kapitalallokation – unabhängig von News oder Kurs.</li>
    <li><b>Note:</b> A ≥ 80, B 65–79, C 50–64, D 35–49, E &lt; 35. <b>Abdeckung</b> = Anteil der Kennzahlen, die vorlagen; unter 40 % gibt es keine Note („?“).</li>
    <li>Klick auf eine Zeile klappt die Einzelwerte auf.</li>
  </ul>,
  Superinvestoren: <ul>
    <li>Quartalsdepots (13F) von 29 bekannten Investoren, verglichen mit dem Vorquartal: <b>Meistgekauft</b>, <b>Meistverkauft</b>, <b>Am häufigsten gehalten</b>.</li>
    <li><b>Q2/26</b> am Namen = Quartal, in dem gekauft/verkauft wurde; das genaue Datum nennt die 13F-Meldung nicht. <b>Gemeldet</b> = wann die Meldung bei der SEC einging (bis 45 Tage nach Quartalsende).</li>
    <li><b>Nächste Zahlen</b> = Termin der nächsten Quartalszahlen (orange = innerhalb 7 Tagen).</li>
    <li>Schneller und taggenau: Großbeteiligungen über 5 % (13D/13G) und Form-4-Käufe weiter unten.</li>
  </ul>,
  "Politiker-Trades": <ul>
    <li>Aktiengeschäfte von Abgeordneten des US-Repräsentantenhauses aus den amtlichen Meldungen (Senat derzeit gesperrt).</li>
    <li>Betrag nur als Spanne (z. B. 1.001–15.000 USD). <b>Meldeverzug</b> = Tage zwischen Geschäft und Meldung – oft mehrere Wochen.</li>
    <li>Interessant sind vor allem Käufe mehrerer Politiker in derselben Aktie.</li>
  </ul>,
  "Insider & Institutionen": <ul>
    <li><b>Cluster-Käufe</b> oben: mindestens zwei verschiedene Insider derselben Firma kaufen innerhalb von 14 Tagen – das stärkste Insider-Signal.</li>
    <li><b>Art:</b> voreingestellt „nur Käufe“. Insider verkaufen aus vielen Gründen (Steuern, Diversifikation), kaufen aber meist nur aus Überzeugung.</li>
    <li><b>10b5-1-Plan</b> = Geschäft wurde Monate vorher festgelegt und sagt wenig über die aktuelle Einschätzung aus – per Haken ausblendbar.</li>
    <li><b>Verzug</b> = Tage zwischen Geschäft und Meldung (gesetzlich max. 2 Werktage).</li>
  </ul>,
  "Social Media": <ul>
    <li><b>StockTwits-Trends</b> oben: worüber dort gerade am meisten gesprochen wird (auch Krypto/ETFs ohne Kennzeichen).</li>
    <li><b>vs. Basis</b> = Beiträge der letzten 24 Std. gegenüber dem Tagesschnitt der Vorwoche (+87 % ≈ fast doppelt so viel).</li>
    <li><b>Stimmung</b> −1 … +1; <b>Bullish/Bearish</b> = Markierung durch die Verfasser selbst (207/71 ≈ 3 : 1 optimistisch).</li>
    <li><b>Manipulation</b> warnt vor Pump-Mustern (gleiche Texte, wenige Accounts, plötzliche Explosion). Spannend: starker Anstieg + positive Stimmung + „unauffällig“.</li>
    <li><b>Wikipedia-Aufmerksamkeit</b> unten: Aufrufe des Firmenartikels gegenüber dem Schnitt – zeigt breites Interesse, Ursache kann gut oder schlecht sein.</li>
  </ul>,
  "Fact-Checking": <ul>
    <li>Wie gut jede Meldung belegt ist: <b>Verified</b> = Primärquelle (z. B. SEC, Unternehmen), <b>Partially Verified</b> = mindestens zwei unabhängige Medien, <b>Unverified</b> = nur eine Quelle.</li>
    <li><b>Outdated</b> = älter als 30 Tage ohne Primärquelle; <b>Disputed/False</b> = widerlegt.</li>
    <li>Je besser belegt, desto mehr Gewicht hat ein Signal.</li>
  </ul>,
  "Risk Overview": <ul>
    <li><b>Risk Score</b> 0–100 (hoch = riskanter) aus Verschuldung, Liquidität, Zinsdeckung, Cashflow, Margen, Verwässerung, Volatilität, Handelsvolumen, Bewertung und negativer Politik.</li>
    <li><b>Stufen:</b> niedrig &lt; 25, moderat 25–44, erhöht 45–64, hoch ≥ 65.</li>
    <li><b>Hohe Aufmerksamkeit bei erhöhtem Risiko:</b> Aktien, über die viel geredet wird, die aber finanziell wackeln – hier besonders vorsichtig sein.</li>
    <li><b>Haupttreiber</b> = die Kennzahlen, die das Risiko am stärksten nach oben ziehen. <b>Abdeckung</b> = Anteil vorhandener Daten.</li>
    <li><b>Achsen</b> Q/M/P/R = Qualität, Market Intelligence (Aufmerksamkeit), Politik, Risiko auf einen Blick.</li>
  </ul>,
  company: <ul>
    <li>Alles zu einer Aktie: die vier Achsen (Qualität, Aufmerksamkeit, Politik, Risiko), Kurs und Trend, Termine, Setups, Social Media, Insider, Superinvestoren, Politiker und Recherche-Links.</li>
    <li>Jede Achse ist getrennt bewertet – eine hohe Aufmerksamkeit macht ein Unternehmen nicht besser.</li>
    {MARKS}
  </ul>,
};

export function helpFor(title: string, key?: string): ReactNode | undefined {
  if (key) return HELP[key];
  return HELP[title] ?? Object.entries(HELP).find(([k]) => title.startsWith(k))?.[1];
}

export function PageHelp({ content }: { content: ReactNode }) {
  return (
    <details className="page-help">
      <summary>So liest du diese Seite</summary>
      {content}
    </details>
  );
}
