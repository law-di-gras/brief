import { useEffect, useState } from "react";
import { get, fmtDate } from "../api.js";

function Highlighted({ text, evidence }) {
  if (!text) return <em className="text-stone-500">No text on this item.</em>;
  const i = evidence ? text.toLowerCase().indexOf(evidence.toLowerCase()) : -1;
  if (i < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, i)}
      <mark className="bg-amber-200 px-0.5">{text.slice(i, i + evidence.length)}</mark>
      {text.slice(i + evidence.length)}
    </>
  );
}

// Side drawer showing the Clio items behind a sentence, with the evidence quote highlighted.
export default function SourceViewer({ cite, onClose }) {
  const [items, setItems] = useState([]);
  useEffect(() => {
    if (!cite) return;
    setItems([]);
    Promise.all(
      cite.source_ids.map((id) => get(`/items/${encodeURIComponent(id)}`).catch(() => ({ item_id: id, missing: true })))
    ).then(setItems);
  }, [cite]);
  if (!cite) return null;
  return (
    <div className="fixed inset-0 z-20 flex justify-end bg-black/30" onClick={onClose}>
      <aside className="h-full w-full max-w-md overflow-y-auto bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <span className="kicker">Source</span>
          <button className="text-sm text-stone-500 hover:text-ink" onClick={onClose}>Close</button>
        </div>
        {cite.text && <p className="mt-3 font-serif text-lg leading-snug">{cite.text}</p>}
        {items.map((it) => (
          <div key={it.item_id} className="mt-5 border-t border-rule pt-4">
            {it.missing ? (
              <p className="text-sm text-stone-500">{it.item_id} is not in the database yet.</p>
            ) : (
              <>
                <div className="kicker">{it.type.replace("_", " ")} · {fmtDate(it.date)}{it.source === "portal" && " · provider reply"}</div>
                <div className="mt-1 font-medium">{it.title}</div>
                <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-stone-700">
                  <Highlighted text={it.text} evidence={cite.evidence} />
                </p>
                {it.clio_url && (
                  <a className="mt-2 inline-block text-sm underline" href={it.clio_url} target="_blank" rel="noreferrer">Open in Clio</a>
                )}
                <div className="mt-1 text-xs text-stone-400">{it.item_id}</div>
              </>
            )}
          </div>
        ))}
      </aside>
    </div>
  );
}
