import { fmtDate } from "../api.js";

export default function BlockerCard({ blocker, onCite }) {
  if (!blocker) return null;
  if (blocker.resolved)
    return (
      <div className="card border-l-4 border-l-emerald-600">
        <div className="kicker">Root blocker cleared</div>
        <p className="mt-1 font-serif text-xl capitalize">{blocker.label}</p>
      </div>
    );
  return (
    <div className="card border-l-4 border-l-flag">
      <div className="flex items-center gap-2">
        <span className="kicker">The one thing holding this case up</span>
        {blocker.disputed && <span className="badge-red">Disputed</span>}
      </div>
      <p className="mt-1 font-serif text-2xl capitalize">{blocker.label}</p>
      {blocker.dependents?.length > 0 && (
        <p className="mt-2 text-sm text-stone-600">
          <span className="capitalize">{blocker.label}</span>
          {blocker.dependents.slice().reverse().map((d) => <span key={d}> → {d}</span>)}
        </p>
      )}
      <p className="mt-1 text-xs text-stone-500">
        {blocker.dependents?.length || 0} things wait on this · asked {blocker.requests_sent ?? 0} times
      </p>
      {blocker.reply_received && (
        <p className="mt-3 bg-amber-100 px-2 py-1 text-sm">A provider answered this. Re-sync to run it through the pipeline.</p>
      )}
      {blocker.disputed && <p className="mt-4 text-sm font-medium">The file names different people as the one holding it:</p>}
      <ul className="mt-2 space-y-3">
        {blocker.holders.map((h, i) => (
          <li key={i} className="border-l-2 border-rule pl-3">
            <div className="text-xs text-stone-500">Waiting on <b className="text-ink">{h.name}</b>{h.date && ` · ${fmtDate(h.date)}`}</div>
            <q className="cite font-serif" onClick={() => onCite({ text: `Waiting on ${h.name}`, source_ids: h.source_ids, evidence: h.quote })}>{h.quote}</q>
          </li>
        ))}
      </ul>
    </div>
  );
}
