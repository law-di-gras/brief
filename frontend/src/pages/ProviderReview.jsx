import { useCallback, useEffect, useState } from "react";
import { get, post, fmtDate } from "../api.js";
import ProviderSections from "../components/ProviderSections.jsx";

// Attorney review screen: one toggle per section. Nothing reaches a provider without a click here.
export default function ProviderReview({ matterId, contactId }) {
  const [d, setD] = useState(null);
  const [sel, setSel] = useState({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [copied, setCopied] = useState(false);
  const cid = encodeURIComponent(contactId);

  const load = useCallback(
    () => get(`/matters/${matterId}/providers/${cid}/review`).then((r) => { setD(r); setSel(r.selected); }).catch((e) => setErr(e.message)),
    [matterId, cid]
  );
  useEffect(() => { load(); }, [load]);

  const act = (fn) => async () => { setBusy(true); setErr(null); try { await fn(); await load(); } catch (e) { setErr(e.message); } setBusy(false); };
  if (err && !d) return <p className="p-10 text-flag">{err}</p>;
  if (!d) return <p className="p-10 text-stone-500">Loading…</p>;

  const share = d.share?.live ? d.share : null;
  const link = share && `${window.location.origin}${window.location.pathname}#/p/${share.token}`;
  const shown = Object.fromEntries(Object.entries(d.preview).filter(([k]) => sel[k]));
  const covHeld = d.preview.coverage.held;

  return (
    <div className="mx-auto max-w-5xl px-6 py-6">
      <a href="#/" className="text-sm underline">Back to the front page</a>
      <h1 className="mt-2 font-serif text-3xl font-bold">Share with {d.preview.provider_name}</h1>
      <div className="mt-6 grid gap-8 md:grid-cols-5">
        <div className="md:col-span-2">
          <div className="kicker">Sections</div>
          <ul className="mt-2 divide-y divide-rule border-y border-rule">
            {d.sections.map((s) => (
              <li key={s.key}>
                <label className="flex cursor-pointer items-start gap-3 py-2.5">
                  <input type="checkbox" className="mt-1 h-4 w-4 accent-black" checked={!!sel[s.key]} onChange={(e) => setSel({ ...sel, [s.key]: e.target.checked })} />
                  <span>
                    <span className="text-sm font-medium">{s.label}</span>
                    {s.key === "coverage" && covHeld && <span className="block text-xs text-flag">Held back automatically while a coverage conflict is open.</span>}
                    {s.key === "patient_told_us" && !d.preview.patient_told_us.length && <span className="block text-xs text-stone-500">Nothing to show: this provider is not on a disputed blocker.</span>}
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-stone-500">Never shared: {d.not_shared.join(", ")}.</p>

          <div className="mt-5 space-y-2">
            {!share && <button className="btn" disabled={busy} onClick={act(() => post(`/matters/${matterId}/shares`, { provider_contact_id: contactId, sections: sel }))}>Create share link</button>}
            {share && (
              <>
                <div className="flex gap-2">
                  <button className="btn" disabled={busy} onClick={act(() => post(`/shares/${share.token}/refresh`, { sections: sel }))}>
                    Refresh share{share.pending_updates > 0 && ` (${share.pending_updates} new)`}
                  </button>
                  <button className="btn-ghost text-flag" disabled={busy} onClick={act(() => post(`/shares/${share.token}/revoke`))}>Revoke</button>
                </div>
                <div className="card break-all text-xs">
                  <a className="underline" href={link} target="_blank" rel="noreferrer">{link}</a>
                  <button className="ml-2 underline" onClick={() => { navigator.clipboard?.writeText(link); setCopied(true); }}>{copied ? "Copied" : "Copy"}</button>
                </div>
                <p className="text-xs text-stone-500">
                  Approved {fmtDate(share.refreshed_at)} · expires {fmtDate(share.expires_at)} · opened {share.opens} {share.opens === 1 ? "time" : "times"}
                  {share.last_opened && `, last ${fmtDate(share.last_opened)}`}
                </p>
                <p className="text-xs text-stone-500">The provider sees the version you last approved. Toggles take effect when you refresh.</p>
              </>
            )}
            {d.share && !d.share.live && <p className="text-xs text-stone-500">Previous link is {d.share.revoked ? "revoked" : "expired"}.</p>}
            {err && <p className="text-sm text-flag">{err}</p>}
          </div>
        </div>

        <div className="border border-rule bg-white px-5 md:col-span-3">
          <div className="kicker pt-4">Preview of what the provider will see</div>
          <ProviderSections sections={shown} />
        </div>
      </div>
    </div>
  );
}
