import { useState } from "react";
import { fmtDate } from "../api.js";

// The blocker as a picture: the stuck step, then what it holds up, left to right.
// Who holds it and how long it has waited are pills; the quotes are one click away.
export default function BlockerCard({ blocker, onCite }) {
  const [quotes, setQuotes] = useState(false);
  if (!blocker) return null;
  if (blocker.resolved)
    return (
      <div className="card border-l-4 border-l-emerald-600">
        <div className="kicker">Root blocker cleared</div>
        <p className="mt-1 font-serif text-xl first-letter:uppercase">{blocker.label}</p>
      </div>
    );
  const holders = [...new Map(blocker.holders.map((h) => [h.holder, h])).values()];
  const chain = [blocker.label, ...(blocker.dependents || [])];
  return (
    <div className="card">
      <div className="flex flex-wrap items-center gap-2">
        <span className="kicker">The one thing holding this case up</span>
        {blocker.disputed && <span className="badge-red">Disputed</span>}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {chain.map((step, i) => (
          <div key={i} className="flex items-center gap-1.5">
            {i > 0 && <span className="text-stone-400" aria-hidden>→</span>}
            <span className={i === 0
              ? "border-2 border-flag bg-red-50 px-2.5 py-1.5 font-serif text-lg font-semibold first-letter:uppercase"
              : "border border-rule bg-paper px-2 py-1 text-sm text-stone-600 first-letter:uppercase"}>
              {step}
            </span>
          </div>
        ))}
      </div>
      {chain.length > 1 && <p className="mt-1 text-xs text-stone-500">Left to right: the stuck step, then what it holds up.</p>}

      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-stone-500">Waiting on</span>
        {holders.map((h) => (
          <span key={h.holder} className="border border-ink px-2 py-0.5 text-sm font-medium">{h.name}</span>
        ))}
        {blocker.requests_sent > 0 && (
          <span className="flex items-center gap-1 text-stone-600" title={`Asked ${blocker.requests_sent} times`}>
            {Array.from({ length: Math.min(blocker.requests_sent, 8) }).map((_, i) => <span key={i} className="h-2 w-2 rounded-full bg-stone-500" />)}
            <span className="ml-0.5 text-xs">asked {blocker.requests_sent}×</span>
          </span>
        )}
        {blocker.days_waiting != null && <span className="text-xs text-stone-600">· {blocker.days_waiting} days</span>}
      </div>

      {blocker.reply_received && (
        <p className="mt-3 bg-amber-100 px-2 py-1 text-sm">A provider answered this. Re-sync to run it through the pipeline.</p>
      )}

      <button className="mt-3 text-xs font-medium text-stone-500 hover:text-ink" onClick={() => setQuotes(!quotes)}>
        {quotes ? "Hide" : blocker.disputed ? "Why disputed: what the file says" : "What the file says"}
      </button>
      {quotes && (
        <ul className="mt-2 space-y-2">
          {blocker.holders.map((h, i) => (
            <li key={i} className="border-l-2 border-rule pl-3">
              <div className="text-xs text-stone-500">Waiting on <b className="text-ink">{h.name}</b>{h.date && ` · ${fmtDate(h.date)}`}</div>
              <q className="cite font-serif" onClick={() => onCite({ text: `Waiting on ${h.name}`, source_ids: h.source_ids, evidence: h.quote })}>{h.quote}</q>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
