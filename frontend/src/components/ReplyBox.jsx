import { useState } from "react";
import { post } from "../api.js";

// Fields come from the request itself (see request_fields in deterministic.py).
export default function ReplyBox({ token, request, onSent }) {
  const [vals, setVals] = useState({});
  const [state, setState] = useState({ busy: false, err: null });
  const set = (k) => (e) => setVals({ ...vals, [k]: e.target.value });
  const empty = !Object.values(vals).some((v) => v && v.trim());

  async function send(e) {
    e.preventDefault();
    setState({ busy: true, err: null });
    try {
      const { note, ...fields } = vals;
      await post(`/p/${token}/reply`, { request_ref: request.ref, fields, note: note || "" });
      setVals({});
      setState({ busy: false, err: null });
      onSent();
    } catch (x) {
      setState({ busy: false, err: x.message });
    }
  }

  return (
    <form onSubmit={send} className="mt-3 grid gap-2 sm:grid-cols-2">
      {request.fields.map((f) => (
        <label key={f.name} className={`text-xs text-stone-600 ${f.type === "text" ? "sm:col-span-2" : ""}`}>
          {f.label}
          {f.type === "date" ? (
            <input type="date" className="input mt-1" value={vals[f.name] || ""} onChange={set(f.name)} />
          ) : (
            <textarea rows={2} maxLength={500} className="input mt-1" value={vals[f.name] || ""} onChange={set(f.name)} />
          )}
        </label>
      ))}
      <div className="flex items-center gap-3 sm:col-span-2">
        <button className="btn" disabled={state.busy || empty}>{state.busy ? "Sending" : "Send to the firm"}</button>
        {state.err && <span className="text-sm text-flag">{state.err}</span>}
      </div>
    </form>
  );
}
