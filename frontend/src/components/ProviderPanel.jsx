import { fmtShort } from "../api.js";

// Per provider: share status, opens, last opened, new replies, updates waiting to be shared.
export default function ProviderPanel({ providers, replies, onCite, onAck }) {
  const fresh = replies.filter((r) => r.status === "new");
  return (
    <div className="card">
      <div className="kicker">Providers</div>
      <ul className="mt-2 divide-y divide-rule">
        {providers.map((p) => {
          const s = p.share;
          return (
            <li key={p.contact_id} className="py-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-medium">{p.name}</div>
                  <div className="text-xs text-stone-500">{p.specialty}</div>
                </div>
                <a className="btn-ghost shrink-0" href={`#/review/${encodeURIComponent(p.contact_id)}`}>{s?.live ? "Review share" : "Share"}</a>
              </div>
              <div className="mt-1 text-sm text-stone-700">
                {!s && "Not shared yet."}
                {s && !s.live && (s.revoked ? "Share revoked." : "Share expired.")}
                {s?.live && (s.opens ? `Opened ${s.opens} ${s.opens === 1 ? "time" : "times"}, last ${fmtShort(s.last_opened)}.` : "Shared, not opened yet.")}
              </div>
              <div className="mt-1 flex flex-wrap gap-2">
                {p.new_replies > 0 && <span className="badge-red">{p.new_replies} new {p.new_replies === 1 ? "reply" : "replies"}</span>}
                {s?.live && s.pending_updates > 0 && (
                  <span className="border border-amber-600 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700">
                    {s.pending_updates} {s.pending_updates === 1 ? "update" : "updates"} to share
                  </span>
                )}
              </div>
            </li>
          );
        })}
        {!providers.length && <li className="py-3 text-sm text-stone-500">No treating providers on this matter.</li>}
      </ul>

      <div className="mt-2 flex items-center justify-between border-t border-rule pt-3">
        <span className="kicker">Reply inbox</span>
        {fresh.length > 0 && <button className="text-xs underline" onClick={onAck}>Mark read</button>}
      </div>
      <ul className="mt-2 space-y-2">
        {replies.slice(0, 6).map((r) => (
          <li key={r.id} className={`text-sm ${r.status === "new" ? "" : "text-stone-500"}`}>
            <span className="cite" onClick={() => onCite({ text: `${r.provider} replied`, source_ids: [r.source_id], evidence: r.value })}>
              <b>{r.provider}</b> replied on <i>{r.request || "a request"}</i>: {r.field !== "note" && `${r.field.replace("_", " ")} `}<b>{r.value}</b>
            </span>
            {r.note && <div className="text-xs text-stone-500">“{r.note}”</div>}
            <div className="text-xs text-stone-400">{fmtShort(r.created_at)} · enter this in Clio by hand, Brief never writes to Clio</div>
          </li>
        ))}
        {!replies.length && <li className="text-sm text-stone-500">No replies yet.</li>}
      </ul>
    </div>
  );
}
