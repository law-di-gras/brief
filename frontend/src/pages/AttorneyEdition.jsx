import { useCallback, useEffect, useState } from "react";
import { get, post, fmtDate, fmtShort, fmtMoney } from "../api.js";
import Timeline from "../components/Timeline.jsx";
import BlockerCard from "../components/BlockerCard.jsx";
import SourceViewer from "../components/SourceViewer.jsx";
import ProviderPanel from "../components/ProviderPanel.jsx";

const Cited = ({ s, onCite, className = "" }) => (
  <span className={`cite ${className}`} onClick={() => onCite(s)}>{s.text}</span>
);

const times = (n) => (n === 1 ? "once" : `${n} times`);
const COMING_UP_SHOWN = 4;

function Toggle({ open, onClick, children }) {
  return (
    <button className="mt-1 text-xs font-medium text-stone-500 hover:text-ink" onClick={onClick}>
      {open ? "Hide" : children}
    </button>
  );
}

function Correction({ badge, red, title, sub, facts, onCite, dim }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`border-b border-rule py-3 ${dim ? "opacity-50" : ""}`}>
      <div className="flex items-baseline gap-2">
        <span className={red ? "badge-red" : "border border-stone-500 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"}>{badge}</span>
        <span className="font-medium">{title}</span>
      </div>
      {sub && <p className="mt-1 text-sm text-stone-600">{sub}</p>}
      {facts.length > 0 && <Toggle open={open} onClick={() => setOpen(!open)}>Show the {facts.length === 1 ? "source" : `${facts.length} sources`}</Toggle>}
      {open && (
        <ul className="mt-2 space-y-1 border-l-2 border-rule pl-3">
          {facts.map((f) => (
            <li key={f.id} className="text-sm">
              {f.event_date && <span className="text-stone-400">{fmtShort(f.event_date)} </span>}
              <Cited s={f} onCite={onCite} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Kpi({ k, onCite }) {
  const big = k.amount != null ? fmtMoney(k.amount) : null;
  return (
    <div className={`cursor-pointer bg-white p-3 hover:bg-amber-50 ${k.slot === "firm_spend" ? "col-span-2" : ""}`}
      title="Click to see the full field and where it came from"
      onClick={() => k.source_ids.length && onCite({ text: `${k.label}: ${k.field_name}`, source_ids: k.source_ids.slice(0, 5), evidence: String(k.value ?? "") })}>
      <div className="kicker">{k.label}</div>
      <div className={big ? "font-serif text-2xl" : "mt-1 text-sm text-stone-500"}>{big || (k.value != null ? "See field" : "Not on file")}</div>
      <div className="truncate text-xs text-stone-500" title={k.summary || k.field_name || ""}>{k.summary || k.field_name || ""}</div>
      {k.conflict && <div className="mt-1" title={k.conflict.explanation}><span className="badge-red">Conflict in file</span></div>}
    </div>
  );
}

export default function AttorneyEdition({ matterId }) {
  const [d, setD] = useState(null);
  const [cite, setCite] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [allComing, setAllComing] = useState(false);
  const [allOther, setAllOther] = useState(false);
  const base = `/matters/${matterId}`;

  const load = useCallback(async () => {
    try {
      const [edition, timeline, providers, replies, runs] = await Promise.all([
        get(`${base}/edition`), get(`${base}/timeline`), get(`${base}/providers`), get(`${base}/replies`), get(`${base}/runs`),
      ]);
      setD({ ...edition, timeline, providers, replies, runs });
    } catch (e) {
      setErr(e.message);
    }
  }, [base]);
  useEffect(() => { load(); }, [load]);

  const act = (fn) => async () => { setBusy(true); try { await fn(); await load(); } catch (e) { setErr(e.message); } setBusy(false); };

  if (err) return <p className="p-10 text-flag">{err}</p>;
  if (!d) return <p className="p-10 text-stone-500">Loading…</p>;
  const m = d.masthead;
  const run = d.runs[0];

  return (
    <div className="mx-auto max-w-6xl px-6 pb-16">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b-4 border-double border-ink py-5">
        <div className="flex items-center gap-4">
          {m.photo_url && <img src={m.photo_url} alt={m.client} className="h-16 w-16 shrink-0 border border-rule object-cover" />}
          <div>
            <div className="kicker">{m.display_number} · {m.stage || m.status}</div>
            <h1 className="font-serif text-4xl font-bold tracking-tight">{m.client}</h1>
            <div className="text-sm text-stone-600">{m.description}</div>
          </div>
        </div>
        <div className="text-right">
          <div className="text-sm">
            <b>{m.updates_since ?? 0}</b> {m.updates_since === 1 ? "update" : "updates"}{" "}
            {m.since_source === "default" ? `in the last ${m.since_days} days` : m.since_source === "visit" ? `since your last visit, ${fmtDate(m.since)}` : `since ${fmtDate(m.since)}`}
          </div>
          <div className="mt-2 flex justify-end gap-2">
            <button className="btn-ghost" disabled={busy} onClick={act(() => post(`${base}/sync`))}>Re-sync</button>
            <button className="btn-ghost" disabled={busy} onClick={act(() => post(`${base}/visit`))}>Mark as read</button>
            <a className="btn-ghost" href="#/full">Full file</a>
          </div>
        </div>
      </header>

      {m.changes.length > 0 && (
        <div className="border-b border-rule py-2 text-sm">
          <span className="kicker mr-2">New</span>
          {m.changes.slice(0, 5).map((c) => (
            <span key={c.item_id} className="cite mr-4" onClick={() => setCite({ text: c.title, source_ids: [c.item_id] })}>
              {fmtShort(c.date)} {c.title}
            </span>
          ))}
        </div>
      )}

      <section className="mt-4">
        <Timeline data={d.timeline} onCite={setCite} />
      </section>

      <div className="mt-6 grid gap-8 lg:grid-cols-3">
        <main className="space-y-6 lg:col-span-2">
          <article>
            {d.headline ? (
              <h2 className="font-serif text-3xl font-bold leading-tight"><Cited s={d.headline} onCite={setCite} /></h2>
            ) : (
              <h2 className="font-serif text-2xl text-stone-500">No headline yet. Run the pipeline.</h2>
            )}
            <p className="mt-3 font-serif text-lg leading-relaxed">
              {d.lead.map((s, i) => <span key={i}><Cited s={s} onCite={setCite} /> </span>)}
            </p>
            <p className="mt-1 text-xs text-stone-400">Click any sentence to see where it came from.</p>
          </article>

          <BlockerCard blocker={d.blocker} onCite={setCite} />

          <section>
            <div className="kicker border-b border-rule pb-1">Corrections: where the file disagrees with itself</div>
            {d.corrections.conflicts.map((c) => (
              <Correction key={`c${c.id}`} badge="Conflict" red title={c.topic} sub={c.explanation} facts={c.facts} onCite={setCite} />
            ))}
            {d.corrections.issues.map((i) => (
              <Correction key={`i${i.id}`} badge={i.resolved ? "Resolved" : "Open issue"} title={i.topic} dim={i.resolved}
                sub={`Open ${i.days_open} days · flagged ${fmtDate(i.first_flagged)}${i.mentions > 1 ? ` · mentioned ${i.mentions} times` : ""}`}
                facts={i.facts} onCite={setCite} />
            ))}
            {!d.corrections.conflicts.length && !d.corrections.issues.length && <p className="py-3 text-sm text-stone-500">Nothing flagged.</p>}
            {(d.corrections.other.conflicts.length + d.corrections.other.issues.length) > 0 && (
              <div className="py-2">
                <Toggle open={allOther} onClick={() => setAllOther(!allOther)}>
                  Show {d.corrections.other.conflicts.length} other discrepancies and {d.corrections.other.issues.length} other open issues
                </Toggle>
                {allOther && (
                  <div className="mt-1">
                    {d.corrections.other.conflicts.map((c) => (
                      <Correction key={`oc${c.id}`} badge="Discrepancy" title={c.topic} sub={c.explanation} facts={c.facts} onCite={setCite} />
                    ))}
                    {d.corrections.other.issues.map((i) => (
                      <Correction key={`oi${i.id}`} badge={i.resolved ? "Resolved" : "Open issue"} title={i.topic} dim={i.resolved}
                        sub={`Open ${i.days_open} days`} facts={i.facts} onCite={setCite} />
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>
        </main>

        <aside className="space-y-6">
          <div className="grid grid-cols-2 gap-px border border-rule bg-rule">
            {d.kpis.map((k) => <Kpi key={k.slot} k={k} onCite={setCite} />)}
          </div>

          <div className="card">
            <div className="kicker">Still waiting</div>
            <ul className="mt-2 divide-y divide-rule">
              {d.still_waiting.map((w) => (
                <li key={w.contact_id} className="py-2">
                  <div className="flex justify-between gap-2">
                    <span className="font-medium">{w.name}</span>
                    <span className="shrink-0 text-xs text-stone-500">{w.days_silent != null && `${w.days_silent} days silent`}</span>
                  </div>
                  {w.owes.map((o) => (
                    <div key={o.ref} className="text-sm">
                      <span className="cite" onClick={() => setCite({ text: o.what, source_ids: o.source_ids })}>{o.what}</span>
                      <span className="text-xs text-stone-500">{o.times_asked > 0 && ` · asked ${times(o.times_asked)}`}{o.first_asked && ` · since ${fmtShort(o.first_asked)}`}</span>
                    </div>
                  ))}
                </li>
              ))}
              {!d.still_waiting.length && <li className="py-2 text-sm text-stone-500">Nobody owes the firm anything.</li>}
            </ul>
          </div>

          <div className="card">
            <div className="kicker">Coming up, next 21 days</div>
            <ul className="mt-2 space-y-1.5">
              {(allComing ? d.coming_up : d.coming_up.filter((c, i) => c.overdue || i < d.coming_up.filter((x) => x.overdue).length + COMING_UP_SHOWN)).map((c) => (
                <li key={c.item_id} className="flex gap-2 text-sm">
                  <span className={`w-16 shrink-0 ${c.overdue ? "font-semibold text-flag" : "text-stone-500"}`}>{c.overdue ? "Overdue" : fmtShort(c.date)}</span>
                  <span className="cite" onClick={() => setCite({ text: c.title, source_ids: [c.item_id] })}>
                    {c.title}{c.overdue && <span className="text-stone-500"> (due {fmtShort(c.date)})</span>}
                  </span>
                </li>
              ))}
              {!d.coming_up.length && <li className="text-sm text-stone-500">Nothing scheduled.</li>}
            </ul>
            {d.coming_up.filter((c) => !c.overdue).length > COMING_UP_SHOWN && (
              <Toggle open={allComing} onClick={() => setAllComing(!allComing)}>Show all {d.coming_up.length}</Toggle>
            )}
          </div>

          <div className="card">
            <div className="kicker">Last client contact</div>
            {d.last_client_contact ? (
              <p className="mt-1 text-sm">
                <b>{d.last_client_contact.days_ago} days ago</b> · {fmtDate(d.last_client_contact.date)}<br />
                <Cited s={{ ...d.last_client_contact, text: d.last_client_contact.title }} onCite={setCite} />
              </p>
            ) : <p className="mt-1 text-sm text-stone-500">None on file.</p>}
          </div>

          <ProviderPanel providers={d.providers} replies={d.replies} onCite={setCite} onAck={act(() => post(`${base}/replies/ack`))} />
        </aside>
      </div>

      <footer className="mt-10 border-t border-rule pt-3 text-xs text-stone-400">
        {run
          ? `Last run ${fmtDate(run.started_at)}: ${run.items_changed} items changed, ${run.facts_kept} facts kept, ${run.facts_dropped} dropped, ${run.input_tokens} in / ${run.output_tokens} out tokens.`
          : "No pipeline runs recorded."}
        {!d.pipeline_live && " Pipeline not connected: showing fixture data."} Brief reads Clio and never writes to it.
      </footer>

      <SourceViewer cite={cite} onClose={() => setCite(null)} />
    </div>
  );
}
