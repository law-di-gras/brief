import { useCallback, useEffect, useState } from "react";
import { get, fmtDate } from "../api.js";
import ProviderSections from "../components/ProviderSections.jsx";

// Public page behind a share token. Everything shown comes from the approved snapshot.
export default function ProviderPage({ token }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const load = useCallback(() => get(`/p/${token}`).then(setD).catch((e) => setErr(e.message)), [token]);
  useEffect(() => { load(); }, [load]);

  if (err) return <div className="mx-auto max-w-xl p-10"><h1 className="font-serif text-2xl">{err}</h1><p className="mt-2 text-sm text-stone-600">Ask the firm for a new link.</p></div>;
  if (!d) return <p className="p-10 text-stone-500">Loading…</p>;
  return (
    <div className="mx-auto max-w-2xl px-6 pb-16">
      <header className="border-b-4 border-double border-ink py-5">
        <div className="kicker">Case update for {d.provider_name}</div>
        <h1 className="font-serif text-3xl font-bold">Your patient: {d.patient}</h1>
        <p className="mt-1 text-sm text-stone-600">
          Approved by the firm on {fmtDate(d.refreshed_at)}.
          {d.new_updates != null && <> <b>{d.new_updates}</b> {d.new_updates === 1 ? "update" : "updates"} since {d.last_view ? "your last view" : "this was shared"}.</>}
        </p>
      </header>
      <ProviderSections sections={d.sections} token={token} replies={d.my_replies} onSent={load} />
      <section className="border-t border-rule py-5">
        <div className="kicker">Not shared</div>
        <p className="mt-2 text-sm text-stone-500">{d.not_shared.map((n) => `🔒 ${n}`).join("   ")}</p>
        <p className="mt-2 text-xs text-stone-400">The firm keeps these internal. This link expires {fmtDate(d.expires_at)}.</p>
      </section>
    </div>
  );
}
