import { fmtShort } from "../api.js";

// Key dated facts from incident to today. Conflicts and open issues get a red marker.
export default function Timeline({ data, onCite }) {
  if (!data || !data.events.length) return null;
  return (
    <div className="overflow-x-auto border-y border-rule py-3">
      <ol className="flex min-w-max">
        {data.events.map((e) => (
          <li key={e.id} className="relative w-40 shrink-0 cursor-pointer pr-4 hover:bg-amber-50" onClick={() => onCite(e)} title={e.text}>
            <div className="kicker">{fmtShort(e.event_date)}</div>
            <div className="relative my-2 h-px bg-stone-400">
              <span className={`absolute -top-[5px] left-0 h-[11px] w-[11px] rounded-full border-2 border-white ${e.marker ? "bg-flag" : "bg-ink"}`} />
            </div>
            <p className={`text-xs leading-snug ${e.marker ? "text-flag" : "text-stone-700"}`} style={{ display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
              {e.text}
            </p>
            {e.marker && <span className="mt-1 inline-block text-[10px] font-semibold uppercase tracking-wide text-flag">{e.marker === "conflict" ? "Conflict" : "Open issue"}</span>}
          </li>
        ))}
        <li className="w-16 shrink-0">
          <div className="kicker">Today</div>
          <div className="relative my-2 h-px bg-stone-400"><span className="absolute -top-[5px] left-0 h-[11px] w-[11px] rounded-full border-2 border-ink bg-white" /></div>
        </li>
      </ol>
    </div>
  );
}
