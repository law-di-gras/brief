import { fmtDate } from "../api.js";
import ReplyBox from "./ReplyBox.jsx";

const H = ({ q, children }) => (
  <section className="border-t border-rule py-5">
    <div className="kicker">{q}</div>
    <div className="mt-2">{children}</div>
  </section>
);

// Renders approved sections. Used by the provider page (snapshot) and the review screen (preview).
export default function ProviderSections({ sections: s, token, replies = {}, onSent }) {
  return (
    <>
      {s.status && (
        <H q="Is this case still active?">
          <p className="font-serif text-xl">{s.status.status === "Open" ? "Yes, the case is open." : `Case status: ${s.status.status}`}</p>
          <p className="text-sm text-stone-600">{s.status.stage && `Stage: ${s.status.stage}. `}Last activity on the file: {fmtDate(s.status.last_activity)}.</p>
        </H>
      )}
      {s.coverage && (
        <H q="Is there coverage behind the case?">
          {s.coverage.held
            ? <p className="text-sm text-stone-600">The firm is not sharing coverage details yet.</p>
            : <p className="font-serif text-xl capitalize">Coverage {s.coverage.state}.</p>}
        </H>
      )}
      {s.requests && (
        <H q="What the firm needs from your office">
          {!s.requests.length && <p className="text-sm text-stone-600">Nothing right now.</p>}
          <ul className="space-y-4">
            {s.requests.map((r) => {
              const mine = replies[r.ref] || [];
              return (
                <li key={r.ref} className="card">
                  <div className="font-serif text-lg">{r.what}</div>
                  <div className="text-xs text-stone-500">
                    {r.first_asked && `First asked ${fmtDate(r.first_asked)}`}{r.times_asked > 1 && ` · asked ${r.times_asked} times`}
                  </div>
                  {mine.map((m, i) => (
                    <p key={i} className="mt-2 bg-emerald-50 px-2 py-1 text-sm">
                      You answered on {fmtDate(m.created_at)}: {m.field !== "note" && `${m.field.replace("_", " ")} `}<b>{m.value}</b>{m.note && ` (${m.note})`}
                    </p>
                  ))}
                  {token && <ReplyBox token={token} request={r} onSent={onSent} />}
                </li>
              );
            })}
          </ul>
        </H>
      )}
      {s.treatment && (
        <H q="Your patient's treatment on file">
          {s.treatment.last_reported
            ? <p className="text-sm">Last reported: {s.treatment.last_reported.text} <span className="text-stone-500">({fmtDate(s.treatment.last_reported.date)})</span></p>
            : <p className="text-sm text-stone-600">No attendance reported to the firm yet.</p>}
          {s.treatment.upcoming.map((u, i) => <p key={i} className="text-sm">Upcoming: {u.title}, {fmtDate(u.date)}</p>)}
        </H>
      )}
      {s.other_treatment && (
        <H q="Other treatment on file">
          {s.other_treatment.length
            ? s.other_treatment.map((o) => <p key={o.name} className="text-sm">{o.name} <span className="text-stone-500">· {o.specialty}</span></p>)
            : <p className="text-sm text-stone-600">No other treating providers on file.</p>}
        </H>
      )}
      {s.patient_told_us?.length > 0 && (
        <H q="What your patient told us">
          {s.patient_told_us.map((t, i) => (
            <blockquote key={i} className="border-l-2 border-ink pl-3 font-serif text-lg">
              “{t.quote}” <span className="block font-sans text-xs text-stone-500">{fmtDate(t.date)} · about the {t.about}</span>
            </blockquote>
          ))}
        </H>
      )}
      {s.updates && (
        <H q="Recent updates">
          <ul className="space-y-1.5">
            {s.updates.map((u) => <li key={u.id} className="text-sm"><span className="text-stone-500">{fmtDate(u.date)} · </span>{u.text}</li>)}
            {!s.updates.length && <li className="text-sm text-stone-600">No updates yet.</li>}
          </ul>
        </H>
      )}
    </>
  );
}
