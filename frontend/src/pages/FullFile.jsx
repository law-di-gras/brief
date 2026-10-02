import { useEffect, useMemo, useState } from "react";
import { get, fmtDate } from "../api.js";
import SourceViewer from "../components/SourceViewer.jsx";

export default function FullFile({ matterId }) {
  const [rows, setRows] = useState([]);
  const [type, setType] = useState("all");
  const [text, setText] = useState("");
  const [cite, setCite] = useState(null);
  useEffect(() => { get(`/matters/${matterId}/items`).then(setRows); }, [matterId]);
  const types = useMemo(() => ["all", ...new Set(rows.map((r) => r.type))], [rows]);
  const shown = rows.filter((r) => (type === "all" || r.type === type) && (r.title + " " + r.text).toLowerCase().includes(text.toLowerCase()));
  return (
    <div className="mx-auto max-w-5xl px-6 py-6">
      <a href="#/" className="text-sm underline">Back to the front page</a>
      <h1 className="mt-2 font-serif text-3xl font-bold">Full file</h1>
      <div className="mt-4 flex flex-wrap gap-2">
        <select className="input w-48" value={type} onChange={(e) => setType(e.target.value)}>
          {types.map((t) => <option key={t} value={t}>{t.replace("_", " ")}</option>)}
        </select>
        <input className="input w-64" placeholder="Filter text" value={text} onChange={(e) => setText(e.target.value)} />
        <span className="self-center text-sm text-stone-500">{shown.length} of {rows.length} items</span>
      </div>
      <table className="mt-4 w-full border-t border-rule text-sm">
        <tbody>
          {shown.map((r) => (
            <tr key={r.item_id} className="cursor-pointer border-b border-rule align-top hover:bg-amber-50" onClick={() => setCite({ text: r.title, source_ids: [r.item_id] })}>
              <td className="w-28 py-2 text-stone-500">{fmtDate(r.date)}</td>
              <td className="w-32 py-2"><span className="kicker">{r.type.replace("_", " ")}</span></td>
              <td className="py-2"><div className="font-medium">{r.title}</div><div className="text-stone-600">{r.text}</div></td>
            </tr>
          ))}
        </tbody>
      </table>
      <SourceViewer cite={cite} onClose={() => setCite(null)} />
    </div>
  );
}
