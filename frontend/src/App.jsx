import { useEffect, useState } from "react";
import { get } from "./api.js";
import AttorneyEdition from "./pages/AttorneyEdition.jsx";
import FullFile from "./pages/FullFile.jsx";
import ProviderPage from "./pages/ProviderPage.jsx";
import ProviderReview from "./pages/ProviderReview.jsx";

// Hash routes: #/  #/full  #/review/<contact id>  #/p/<token>
function useRoute() {
  const read = () => window.location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  const [parts, setParts] = useState(read);
  useEffect(() => {
    const on = () => { setParts(read()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return parts;
}

export default function App() {
  const [page, arg] = useRoute();
  const [matterId, setMatterId] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (page === "p") return;
    get("/config").then((c) => setMatterId(c.matter_id)).catch((e) => setErr(e.message));
  }, [page]);

  if (page === "p") return <ProviderPage token={arg} />;
  if (err) return <p className="p-10 text-flag">Backend not reachable: {err}</p>;
  if (!matterId) return <p className="p-10 text-stone-500">No matter loaded yet. Run the sync or dev/load_seed.py.</p>;
  if (page === "full") return <FullFile matterId={matterId} />;
  if (page === "review") return <ProviderReview matterId={matterId} contactId={arg} />;
  return <AttorneyEdition matterId={matterId} />;
}
