import { fmtMoney, fmtShort } from "../api.js";

// Big numbers in place of status sentences. Each tile can open the section that explains it.
export function StatTiles({ tiles }) {
  return (
    <div className="grid grid-cols-2 gap-px border border-rule bg-rule md:grid-cols-4">
      {tiles.map((t) => (
        <button key={t.label} onClick={t.onClick} disabled={!t.onClick}
          className="bg-white p-3 text-left hover:bg-amber-50 disabled:cursor-default disabled:hover:bg-white">
          <div className={`font-serif text-3xl leading-none ${t.alert ? "text-flag" : "text-ink"}`}>{t.value ?? "–"}</div>
          <div className="mt-1 text-xs text-stone-500">{t.label}</div>
        </button>
      ))}
    </div>
  );
}

// The money in one picture: one series on one axis, with the coverage cap drawn across it,
// so "the case is worth more than the coverage behind it" is visible without reading.
export function MoneyBars({ kpis, onCite }) {
  const order = ["case_value", "specials", "coverage", "lien", "firm_spend"];
  const rows = order.map((slot) => kpis.find((k) => k.slot === slot)).filter((k) => k && k.amount != null);
  if (!rows.length) return null;
  const max = Math.max(...rows.map((k) => k.amount));
  const cap = kpis.find((k) => k.slot === "coverage")?.amount;
  const pct = (v) => `${Math.max((v / max) * 100, 0.6)}%`;
  return (
    <figure className="border border-rule bg-white p-4">
      <figcaption className="kicker">The money</figcaption>
      <div className="relative mt-3 space-y-2">
        {cap != null && (
          <div className="pointer-events-none absolute inset-y-0 z-10 border-l-2 border-dashed border-flag"
            style={{ left: `calc(8rem + (100% - 14.5rem) * ${cap / max})` }}>
            <span className="absolute -top-5 -translate-x-1/2 whitespace-nowrap bg-white px-1 text-[10px] font-semibold uppercase tracking-wide text-flag">
              coverage {fmtMoney(cap)}
            </span>
          </div>
        )}
        {rows.map((k) => (
          <div key={k.slot} className="group flex cursor-pointer items-center gap-2"
            title={`${k.label}: ${fmtMoney(k.amount)}${k.summary ? ` (${k.summary})` : ""}. Click for the source.`}
            onClick={() => k.source_ids?.length && onCite({ text: `${k.label}: ${k.field_name}`, source_ids: k.source_ids.slice(0, 5), evidence: String(k.value ?? "") })}>
            <div className="w-[7.5rem] shrink-0 text-right text-xs text-stone-600">{k.label}</div>
            <div className="relative h-4 flex-1">
              <div className="h-full rounded-r-[4px] bg-stone-700 group-hover:bg-ink" style={{ width: pct(k.amount) }} />
            </div>
            <div className="w-[6rem] shrink-0 text-sm tabular-nums text-ink">
              {fmtMoney(k.amount)}{k.conflict && <span className="ml-1 text-flag" title={k.conflict.explanation}>●</span>}
            </div>
          </div>
        ))}
      </div>
      {kpis.some((k) => k.conflict) && (
        <p className="mt-3 text-xs text-stone-500"><span className="text-flag">●</span> the file disagrees about this number</p>
      )}
    </figure>
  );
}

// Key events as dots on a time axis; red dots are where the file disagrees or a problem was flagged.
export function DotTimeline({ data, onCite }) {
  const events = data?.events || [];
  if (!events.length) return null;
  const t = (s) => new Date(`${s.slice(0, 10)}T12:00:00`).getTime();
  const start = Math.min(...events.map((e) => t(e.event_date)));
  const end = Math.max(t(data.today), ...events.map((e) => t(e.event_date)));
  const x = (s) => ((t(s) - start) / Math.max(end - start, 1)) * 100;
  const years = [];
  for (let y = new Date(start).getFullYear() + 1; y <= new Date(end).getFullYear(); y++) years.push(y);
  const lane = {};
  return (
    <figure className="border border-rule bg-white px-4 pb-3 pt-4">
      <figcaption className="flex items-baseline justify-between">
        <span className="kicker">Timeline</span>
        <span className="text-xs text-stone-500"><span className="text-ink">●</span> event · <span className="text-flag">●</span> disagreement or open issue</span>
      </figcaption>
      <div className="relative mx-2 mt-4 h-14">
        <div className="absolute inset-x-0 top-6 h-px bg-stone-300" />
        {years.map((y) => (
          <div key={y} className="absolute top-4 h-5 border-l border-stone-200" style={{ left: `${x(`${y}-01-01`)}%` }}>
            <span className="absolute top-6 -translate-x-1/2 text-[10px] text-stone-400">{y}</span>
          </div>
        ))}
        {events.map((e) => {
          const key = Math.round(x(e.event_date));
          const i = (lane[key] = (lane[key] ?? -1) + 1);
          return (
            <button key={e.id} title={`${fmtShort(e.event_date)} ${e.event_date.slice(0, 4)}: ${e.text}`}
              onClick={() => onCite(e)}
              className={`absolute h-3.5 w-3.5 -translate-x-1/2 rounded-full border-2 border-white hover:scale-125 ${e.marker ? "bg-flag" : "bg-ink"}`}
              style={{ left: `${x(e.event_date)}%`, top: `${19 - i * 10}px` }} />
          );
        })}
        <div className="absolute top-3 h-7 border-l-2 border-ink" style={{ left: "100%" }}>
          <span className="absolute -top-4 -translate-x-1/2 text-[10px] font-semibold uppercase text-ink">today</span>
        </div>
      </div>
    </figure>
  );
}
