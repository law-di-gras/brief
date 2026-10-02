"""The three trust rules. Anything the model can't back with a real source is dropped.

1. Real sources only: every source_id must be one of the items sent in that request.
2. Verbatim evidence: the evidence quote must appear word for word in a cited source.
3. No number without a source: every number, dollar amount and date in the text must
   appear in the cited source text after normalization.
"""
import re
from collections import Counter
from datetime import date

CATEGORIES = {"coverage", "liability", "injury", "treatment", "damages", "lien", "procedure",
              "discovery", "client_contact", "provider_request", "issue"}
AUDIENCES = {"internal", "shareable"}
HOLDER_WORDS = {"firm", "court", "unknown"}

# ---- text normalization ---------------------------------------------------------------

_TRANS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", "­": "",
})


def norm_text(s: str) -> str:
    s = (s or "").translate(_TRANS).lower()
    s = re.sub(r"-\s*\n\s*", "-", s)          # hyphenation across PDF line breaks
    return re.sub(r"\s+", " ", s).strip()


def evidence_in(evidence: str, source_texts: list[str]) -> bool:
    """True when the quote (or each part of a quote elided with '...') appears in one source."""
    ev = norm_text(evidence).strip(" \"'")
    if len(ev) < 8:
        return False
    parts = [p.strip(" \"'") for p in re.split(r"\.\.\.|…", ev)]
    parts = [p for p in parts if p]
    if not parts:
        return False
    for src in source_texts:
        s = norm_text(src)
        if all(p in s for p in parts):
            return True
    return False


# ---- numbers and dates ------------------------------------------------------------------

MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_ORD = r"(?:st|nd|rd|th)?"

DATE_PATTERNS = [
    ("ymd", re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})(?:t[\d:.]+z?)?\b")),
    ("mdy_slash", re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b")),
    ("mdy", re.compile(rf"\b{_MON}\s+(\d{{1,2}}){_ORD},?\s+(\d{{4}})\b")),
    ("dmy", re.compile(rf"\b(\d{{1,2}}){_ORD}\s+(?:of\s+)?{_MON},?\s+(\d{{4}})\b")),
    ("my", re.compile(rf"\b{_MON},?\s+(\d{{4}})\b")),
    ("md", re.compile(rf"\b{_MON}\s+(\d{{1,2}}){_ORD}\b(?!\s*,?\s*\d)")),
]

WORDS = {w: i for i, w in enumerate(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
     "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"])}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
# "one" and "zero" are too often not quantities ("the one thing", "no one"), so a fact
# using them is not held to a number check; sources still map them so "1" can match "one".
FACT_SKIP_WORDS = {"zero", "one"}

NUM_RE = re.compile(r"(?<![a-z\d.])\$?(\d[\d,]*(?:\.\d+)?)\s*(k|m|million|thousand)?\b(?![a-z\d])")
WORD_RE = re.compile(r"\b(" + "|".join(sorted(TENS, key=len, reverse=True)) + r")(?:[- ](" +
                     "|".join(k for k in WORDS if WORDS[k] < 10) + r"))?\b|\b(" +
                     "|".join(sorted(WORDS, key=len, reverse=True)) + r")\b")


def _num(s: str, suffix: str | None = None) -> str | None:
    try:
        v = float(s.replace(",", ""))
    except ValueError:
        return None
    if suffix in ("k", "thousand"):
        v *= 1000
    elif suffix in ("m", "million"):
        v *= 1_000_000
    return str(int(v)) if v == int(v) else f"{v:.4f}".rstrip("0").rstrip(".")


def _iso(y, m, d) -> str | None:
    try:
        y = int(y)
        if y < 100:
            y += 2000
        return date(y, int(m), int(d)).isoformat()
    except (ValueError, TypeError):
        return None


def extract_numbers(text: str, include_words=True, skip_words=frozenset()) -> tuple[set, set]:
    """Return (dates, numbers) found in text.

    dates are tokens 'YYYY-MM-DD', 'YYYY-MM' or 'MM-DD' (when the year is missing);
    numbers are normalized decimal strings.
    """
    t = norm_text(text)
    dates, numbers = set(), set()

    def take(m, kind):
        g = m.groups()
        if kind == "ymd":
            v = _iso(g[0], g[1], g[2])
        elif kind == "mdy_slash":
            v = _iso(g[2], g[0], g[1])
        elif kind == "mdy":
            v = _iso(g[2], MONTHS[g[0][:3]], g[1])
        elif kind == "dmy":
            v = _iso(g[2], MONTHS[g[1][:3]], g[0])
        elif kind == "my":
            v = f"{int(g[1]):04d}-{MONTHS[g[0][:3]]:02d}"
        else:  # md
            v = f"{MONTHS[g[0][:3]]:02d}-{int(g[1]):02d}" if 1 <= int(g[1]) <= 31 else None
        if v:
            dates.add(v)
        return " "

    for kind, pat in DATE_PATTERNS:
        t = pat.sub(lambda m, k=kind: take(m, k), t)

    for m in NUM_RE.finditer(t):
        v = _num(m.group(1), m.group(2))
        if v is not None:
            numbers.add(v)
    if include_words:
        for m in WORD_RE.finditer(t):
            if m.group(3):
                if m.group(3) in skip_words:
                    continue
                numbers.add(str(WORDS[m.group(3)]))
            else:
                numbers.add(str(TENS[m.group(1)] + (WORDS[m.group(2)] if m.group(2) else 0)))
    return dates, numbers


def source_tokens(source_texts: list[str], item_dates: list[str] = ()) -> tuple[set, set]:
    """Every date and number a set of sources can vouch for, including date components."""
    dates, numbers = set(), set()
    for s in source_texts:
        d, n = extract_numbers(s)
        dates |= d
        numbers |= n
    dates |= {d for d in item_dates if d}
    for d in list(dates):
        parts = d.split("-")
        if len(parts) == 3:
            dates.add(f"{parts[0]}-{parts[1]}")
            dates.add(f"{parts[1]}-{parts[2]}")
        for p in parts:
            numbers.add(str(int(p)))
    return dates, numbers


def unsourced_numbers(text: str, source_texts: list[str], item_dates: list[str] = ()) -> list[str]:
    """Dates and numbers in `text` that the sources do not contain."""
    f_dates, f_nums = extract_numbers(text, skip_words=FACT_SKIP_WORDS)
    s_dates, s_nums = source_tokens(source_texts, item_dates)
    return sorted([d for d in f_dates if d not in s_dates] + [n for n in f_nums if n not in s_nums])


def check_sentence(text: str, source_texts: list[str], item_dates: list[str] = ()) -> bool:
    return not unsourced_numbers(text, source_texts, item_dates)


# ---- fact and dependency validation -----------------------------------------------------

def _valid_iso(d) -> str | None:
    if not d or not isinstance(d, str):
        return None
    try:
        return date.fromisoformat(d[:10]).isoformat()
    except ValueError:
        return None


def validate_facts(facts: list[dict], sent: dict[str, dict], roster_ids: set[str]) -> tuple[list[dict], Counter]:
    """sent maps item_id -> item row (needs 'text' and 'item_date'). Returns (kept, drop_counts)."""
    kept, drops = [], Counter()
    for f in facts:
        text = (f.get("text") or "").strip()
        category = (f.get("category") or "").strip().lower()
        sids = [s for s in (f.get("source_ids") or []) if isinstance(s, str)]
        if not text or category not in CATEGORIES:
            drops["malformed"] += 1
            continue
        if not sids or any(s not in sent for s in sids):
            drops["fake_source"] += 1
            continue
        texts = [sent[s]["text"] for s in sids]
        item_dates = [sent[s].get("item_date") for s in sids]
        if not evidence_in(f.get("evidence") or "", texts):
            drops["evidence_not_verbatim"] += 1
            continue
        if unsourced_numbers(text, texts, item_dates):
            drops["unsourced_number"] += 1
            continue
        ev_date = _valid_iso(f.get("event_date"))
        if ev_date:
            s_dates, _ = source_tokens(texts, item_dates)
            if ev_date not in s_dates:
                drops["event_date_cleared"] += 1   # repaired, not dropped
                ev_date = None
        try:
            importance = min(5, max(1, int(f.get("importance") or 3)))
        except (TypeError, ValueError):
            importance = 3
        kept.append({
            "text": text,
            "category": category,
            "event_date": ev_date,
            "entities": [e for e in (f.get("entities") or []) if e in roster_ids],
            "source_ids": list(dict.fromkeys(sids)),
            "evidence": f["evidence"].strip(),
            "audience": f.get("audience") if f.get("audience") in AUDIENCES else "internal",
            "importance": importance,
            "is_open_issue": bool(f.get("is_open_issue")),
        })
    return kept, drops


def validate_dependencies(deps: list[dict], sent: dict[str, dict], roster_ids: set[str]) -> tuple[list[dict], Counter]:
    kept, drops = [], Counter()
    for d in deps:
        blocked, waiting = (d.get("blocked") or "").strip(), (d.get("waiting_on") or "").strip()
        sids = [s for s in (d.get("source_ids") or []) if isinstance(s, str)]
        if not blocked or not waiting:
            drops["dep_malformed"] += 1
            continue
        if not sids or any(s not in sent for s in sids):
            drops["dep_fake_source"] += 1
            continue
        if not evidence_in(d.get("evidence") or "", [sent[s]["text"] for s in sids]):
            drops["dep_evidence_not_verbatim"] += 1
            continue
        holder = d.get("holder") or "unknown"
        if holder not in roster_ids and holder not in HOLDER_WORDS:
            holder = "unknown"
        kept.append({"blocked": blocked, "waiting_on": waiting, "holder": holder,
                     "source_ids": list(dict.fromkeys(sids)), "evidence": d["evidence"].strip()})
    return kept, drops
