async function req(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => null);
  if (!r.ok) throw new Error((body && body.detail) || `Request failed (${r.status})`);
  return body;
}
export const get = (p) => req(p);
export const post = (p, data) =>
  req(p, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(data ?? {}) });

export const fmtDate = (s) => {
  if (!s) return "";
  const d = new Date(s.length <= 10 ? s + "T12:00:00" : s);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
};
export const fmtShort = (s) => {
  if (!s) return "";
  const d = new Date(s.length <= 10 ? s + "T12:00:00" : s);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
};
export const fmtMoney = (n) =>
  n == null ? "n/a" : n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: n % 1 ? 2 : 0 });
