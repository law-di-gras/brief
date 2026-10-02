import { useEffect, useState } from "react";
import { get, post } from "./api.js";
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

function SignIn({ me, onDone }) {
  const [err, setErr] = useState(null);
  return (
    <div className="mx-auto mt-24 max-w-sm px-6 text-center">
      <div className="kicker">Brief</div>
      <h1 className="mt-1 font-serif text-3xl font-bold">Sign in to read the file</h1>
      <p className="mt-2 text-sm text-stone-600">Brief uses your Clio login. It reads Clio and never writes to it.</p>
      <a className="btn mt-6 w-full justify-center" href="/auth/clio/login">Sign in with Clio</a>
      {me.fixture_mode && (
        <button className="btn-ghost mt-2 w-full justify-center" onClick={() => post("/auth/dev/login").then(onDone).catch((e) => setErr(e.message))}>
          Continue with the seed file (no Clio)
        </button>
      )}
      {err && <p className="mt-3 text-sm text-flag">{err}</p>}
    </div>
  );
}

function SessionBar({ me, onChange }) {
  if (!me.auth_required || !me.user) return null;
  const others = me.sessions.filter((s) => !s.current).length;
  return (
    <div className="mx-auto flex max-w-6xl items-center justify-end gap-3 px-6 pt-2 text-xs text-stone-500">
      <span>Signed in as <b className="text-ink">{me.user.name || me.user.id}</b></span>
      {others > 0 && (
        <button className="underline" onClick={() => post("/auth/logout?everywhere_else=true").then(onChange)}>
          Sign out {others} other {others === 1 ? "session" : "sessions"}
        </button>
      )}
      <button className="underline" onClick={() => post("/auth/logout").then(onChange)}>Sign out</button>
    </div>
  );
}

export default function App() {
  const [page, arg] = useRoute();
  const [me, setMe] = useState(null);
  const [matterId, setMatterId] = useState(null);
  const [err, setErr] = useState(null);

  const loadMe = () => get("/auth/me").then(setMe).catch((e) => setErr(e.message));
  useEffect(() => {
    if (page === "p") return;
    loadMe();
    window.addEventListener("brief:signed-out", loadMe);
    return () => window.removeEventListener("brief:signed-out", loadMe);
  }, [page === "p"]);
  useEffect(() => {
    if (page === "p" || !me?.authenticated) return;
    get("/config").then((c) => setMatterId(c.matter_id)).catch((e) => setErr(e.message));
  }, [page, me?.authenticated]);

  if (page === "p") return <ProviderPage token={arg} />;
  if (!me && !err) return <p className="p-10 text-stone-500">Loading…</p>;
  if (me && !me.authenticated) return <SignIn me={me} onDone={loadMe} />;
  if (err) return <p className="p-10 text-flag">Backend not reachable: {err}</p>;
  if (!matterId) return <p className="p-10 text-stone-500">No matter loaded yet. Run the sync or dev/load_seed.py.</p>;
  const view =
    page === "full" ? <FullFile matterId={matterId} />
    : page === "review" ? <ProviderReview matterId={matterId} contactId={arg} />
    : <AttorneyEdition matterId={matterId} />;
  return <><SessionBar me={me} onChange={loadMe} />{view}</>;
}
