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

// Two statements that cannot both be true, side by side, each with where it comes from.
function ConflictCard({ c, onCite }) {
  const [open, setOpen] = useState(false);
  const [a, b] = c.sides;
  const Side = ({ s, tag }) => (
    <div className="min-w-0 border border-rule bg-white p-3">
      <div className="flex items-baseline justify-between gap-2 text-xs text-stone-500">
        <span className="kicker">{tag}</span>
        <span className="truncate" title={s.label}>{s.label}</span>
      </div>
      <p className="mt-2 font-serif text-[15px] leading-snug">
        <span className="cite" onClick={() => onCite({ text: s.text, source_ids: s.source_ids, evidence: s.evidence })}>{s.text}</span>
      </p>
      {s.date && <div className="mt-1 text-xs text-stone-400">Recorded {fmtDate(s.date)}{s.more > 0 && ` · +${s.more} more in the same source`}</div>}
    </div>
  );
  return (
    <div className="border-b border-rule py-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="badge-red">Conflict</span>
        <span className="font-medium">{c.topic}</span>
        {c.affects && <span className="text-xs text-stone-500">· affects {c.affects}</span>}
      </div>
      {b ? (
        <div className="mt-3 grid items-stretch gap-2 md:grid-cols-[1fr_auto_1fr]">
          <Side s={a} tag="Says" />
          <div className="flex items-center justify-center text-xs font-semibold uppercase tracking-wide text-flag md:flex-col">vs</div>
          <Side s={b} tag="But" />
        </div>
      ) : null}
      {c.explanation && <p className="mt-2 text-sm text-stone-600">{c.explanation}</p>}
      {c.facts.length > 2 && <Toggle open={open} onClick={() => setOpen(!open)}>Show all {c.facts.length} statements</Toggle>}
      {open && (
        <ul className="mt-2 space-y-1 border-l-2 border-rule pl-3">
          {c.facts.map((f) => <li key={f.id} className="text-sm"><Cited s={f} onCite={onCite} /></li>)}
        </ul>
      )}
    </div>
  );
}

// A collapsed section with its count in the summary, so what is hidden is still visible at a glance.
function Section({ title, count, note, red, children }) {
  return (
    <details className="group border-b border-rule">
      <summary className="flex cursor-pointer list-none items-baseline justify-between gap-3 py-3 hover:bg-amber-50">
        <span className="flex items-baseline gap-2">
          <span className="text-stone-400 transition-transform group-open:rotate-90">▸</span>
          <span className="font-medium">{title}</span>
          {count != null && <span className={`text-sm ${red ? "font-semibold text-flag" : "text-stone-500"}`}>({count})</span>}
        </span>
        {note && <span className={`text-xs ${red ? "text-flag" : "text-stone-500"}`}>{note}</span>}
      </summary>
      <div className="pb-4">{children}</div>
    </details>
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
  const kpis = d.kpis.filter((k) => k.slot !== "firm_spend");
  const spend = d.kpis.find((k) => k.slot === "firm_spend");
  const nConflicts = d.corrections.conflicts.length;
  const nIssues = d.corrections.issues.length;
  const nOther = d.corrections.other.conflicts.length + d.corrections.other.issues.length;
  const overdue = d.coming_up.filter((c) => c.overdue).length;
  const owed = d.still_waiting.reduce((n, w) => n + w.owes.length, 0);
  const newReplies = (d.replies || []).filter((r) => r.status === "new").length;
  const shared = (d.providers || []).filter((p) => p.share).length;
  const lc = d.last_client_contact;

  return (
    <div className="mx-auto max-w-4xl px-6 pb-16">
      {/* ---------- first view: who, what changed, the story, the blocker, the numbers ---------- */}
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
          {m.changes.slice(0, 4).map((c) => (
            <span key={c.item_id} className="cite mr-4" onClick={() => setCite({ text: c.title, source_ids: [c.item_id] })}>
              {fmtShort(c.date)} {c.title}
            </span>
          ))}
        </div>
      )}

      <article className="mt-6">
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

      <div className="mt-6"><BlockerCard blocker={d.blocker} onCite={setCite} /></div>

      <div className="mt-6 grid grid-cols-2 gap-px border border-rule bg-rule md:grid-cols-4">
        {kpis.map((k) => <Kpi key={k.slot} k={k} onCite={setCite} />)}
      </div>

      <p className="mt-3 text-sm text-stone-600">
        {lc ? (
          <>Last talked to the client <b>{lc.days_ago} days ago</b>:{" "}
            <Cited s={{ ...lc, text: lc.title }} onCite={setCite} /></>
        ) : "No client contact on file."}
        {spend && <> · Firm has spent <span className="cite" onClick={() => spend.source_ids.length && setCite({ text: `Firm spend: ${spend.field_name}`, source_ids: spend.source_ids.slice(0, 5) })}><b>{fmtMoney(spend.amount)}</b></span> ({spend.field_name})</>}
      </p>

      {/* ---------- everything else: one click away, with a count so nothing hides ---------- */}
      <div className="mt-8 border-t border-ink">
        <Section title="Where the file disagrees with itself" count={nConflicts + nIssues}
          note={`${nConflicts} ${nConflicts === 1 ? "conflict" : "conflicts"} · ${nIssues} open ${nIssues === 1 ? "issue" : "issues"}`} red={nConflicts > 0}>
          {d.corrections.conflicts.map((c) => (
            c.sides?.length > 1
              ? <ConflictCard key={`c${c.id}`} c={c} onCite={setCite} />
              : <Correction key={`c${c.id}`} badge="Conflict" red title={c.topic} sub={c.explanation} facts={c.facts} onCite={setCite} />
          ))}
          {d.corrections.issues.map((i) => (
            <Correction key={`i${i.id}`} badge={i.resolved ? "Resolved" : "Open issue"} title={i.topic} dim={i.resolved}
              sub={`Open ${i.days_open} days · flagged ${fmtDate(i.first_flagged)}${i.mentions > 1 ? ` · mentioned ${i.mentions} times` : ""}`}
              facts={i.facts} onCite={setCite} />
          ))}
          {!nConflicts && !nIssues && <p className="py-3 text-sm text-stone-500">Nothing flagged.</p>}
          {nOther > 0 && (
            <div className="py-2">
              <Toggle open={allOther} onClick={() => setAllOther(!allOther)}>
                Show {d.corrections.other.conflicts.length} other discrepancies and {d.corrections.other.issues.length} other open issues
              </Toggle>
              {allOther && (
                <div className="mt-1">
                  {d.corrections.other.conflicts.map((c) => (
                    c.sides?.length > 1
                      ? <ConflictCard key={`oc${c.id}`} c={c} onCite={setCite} />
                      : <Correction key={`oc${c.id}`} badge="Discrepancy" title={c.topic} sub={c.explanation} facts={c.facts} onCite={setCite} />
                  ))}
                  {d.corrections.other.issues.map((i) => (
                    <Correction key={`oi${i.id}`} badge={i.resolved ? "Resolved" : "Open issue"} title={i.topic} dim={i.resolved}
                      sub={`Open ${i.days_open} days`} facts={i.facts} onCite={setCite} />
                  ))}
                </div>
              )}
            </div>
          )}
        </Section>

        <Section title="Still waiting on others" count={owed}
          note={`${owed} ${owed === 1 ? "request" : "requests"} with ${d.still_waiting.length} ${d.still_waiting.length === 1 ? "party" : "parties"}`}>
          <ul className="divide-y divide-rule">
            {d.still_waiting.map((w) => (
              <li key={w.contact_id} className="py-2">
                <div className="flex justify-between gap-2">
                  <span className="font-medium">{w.name}</span>
                  <span className="shrink-0 text-xs text-stone-500">{w.days_silent != null && `${w.days_silent} days silent`}</span>
                </div>
                {w.owes.map((o) => (
                  <div key={o.ref} className="mt-1 text-sm">
                    <span className="mr-1.5 inline-block border border-stone-400 px-1 text-[10px] font-semibold uppercase tracking-wide text-stone-600">{o.kind_label}</span>
                    <span className="cite" onClick={() => setCite({ text: o.what, source_ids: o.source_ids })}>{o.what !== o.kind_label ? o.what : "see source"}</span>
                    <span className="text-xs text-stone-500">{o.times_asked > 0 && ` · asked ${times(o.times_asked)}`}{o.first_asked && ` · since ${fmtShort(o.first_asked)}`}</span>
                  </div>
                ))}
              </li>
            ))}
            {!d.still_waiting.length && <li className="py-2 text-sm text-stone-500">Nobody owes the firm anything.</li>}
          </ul>
        </Section>

        <Section title="Coming up, next 21 days" count={d.coming_up.length}
          note={overdue ? `${overdue} overdue` : `${d.coming_up.length} scheduled`} red={overdue > 0}>
          <ul className="space-y-1.5">
            {(allComing ? d.coming_up : d.coming_up.filter((c, i) => c.overdue || i < overdue + COMING_UP_SHOWN)).map((c) => (
              <li key={c.item_id} className="flex gap-2 text-sm">
                <span className={`w-16 shrink-0 ${c.overdue ? "font-semibold text-flag" : "text-stone-500"}`}>{c.overdue ? "Overdue" : fmtShort(c.date)}</span>
                <span className="cite" onClick={() => setCite({ text: c.title, source_ids: [c.item_id] })}>
                  {c.title}{c.overdue && <span className="text-stone-500"> (due {fmtShort(c.date)})</span>}
                </span>
              </li>
            ))}
            {!d.coming_up.length && <li className="text-sm text-stone-500">Nothing scheduled.</li>}
          </ul>
          {d.coming_up.length - overdue > COMING_UP_SHOWN && (
            <Toggle open={allComing} onClick={() => setAllComing(!allComing)}>Show all {d.coming_up.length}</Toggle>
          )}
        </Section>

        <Section title="Timeline" count={d.timeline?.events?.length || 0} note="key dated events, incident to today">
          <Timeline data={d.timeline} onCite={setCite} />
        </Section>

        <Section title="Providers and replies" count={(d.providers || []).length}
          note={`${shared} shared${newReplies ? ` · ${newReplies} new ${newReplies === 1 ? "reply" : "replies"}` : ""}`} red={newReplies > 0}>
          <ProviderPanel providers={d.providers} replies={d.replies} onCite={setCite} onAck={act(() => post(`${base}/replies/ack`))} />
        </Section>

        <Section title="How this page was made" note={run ? `last run ${fmtDate(run.started_at)}` : "no runs yet"}>
          <p className="text-sm text-stone-600">
            {run
              ? `Last run ${fmtDate(run.started_at)}: ${run.items_changed} items changed, ${run.facts_kept} facts kept, ${run.facts_dropped} dropped by the source checks, ${run.input_tokens} in / ${run.output_tokens} out tokens.`
              : "No pipeline runs recorded."}
            {run?.status === "partial" && ` ${run.error}`}
            {!d.pipeline_live && " Pipeline not connected: showing fixture data."}
          </p>
          <p className="mt-1 text-sm text-stone-600">Brief reads Clio and never writes to it. Every sentence opens the item it came from.</p>
        </Section>
      </div>

      <SourceViewer cite={cite} onClose={() => setCite(null)} />
    </div>
  );
}
