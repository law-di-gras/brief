"""Small Haiku classification helper for the product side.

Used twice: mapping custom field names to KPI slots, and classifying
relationship descriptions into roles. Both run once per process and are cached.
Without ANTHROPIC_API_KEY (or on any error) a keyword fallback is used, so the
product side runs offline against fixtures.

TODO(A): route through pipeline/llm.py so these tokens land in `runs`.
"""
import json
import os

HAIKU = "claude-haiku-4-5-20251001"
_cache = {}


def classify(labels, options, instruction, fallback):
    """Return {label: option}. `fallback(label)` is the keyword rule."""
    labels = [l for l in dict.fromkeys(labels) if l]
    key = (instruction, tuple(labels))
    if key in _cache:
        return _cache[key]
    out = None
    if labels and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            msg = anthropic.Anthropic().messages.create(
                model=HAIKU, max_tokens=600,
                messages=[{"role": "user", "content": (
                    f"{instruction}\nAllowed values: {json.dumps(options)}.\n"
                    f"Labels: {json.dumps(labels)}\n"
                    "Reply with one JSON object mapping every label to exactly one allowed value. JSON only.")}])
            text = msg.content[0].text
            got = json.loads(text[text.index("{"): text.rindex("}") + 1])
            out = {l: got.get(l) if got.get(l) in options else fallback(l) for l in labels}
        except Exception:
            out = None
    if out is None:
        out = {l: fallback(l) for l in labels}
    _cache[key] = out
    return out


KPI_SLOTS = ["case_value", "coverage", "specials", "lien", "none"]
ROLES = ["treating_provider", "insurer", "opposing_counsel", "expert", "witness", "other"]


def _kw(rules, default):
    def f(label):
        s = label.lower()
        for words, val in rules:
            if any(w in s for w in words):
                return val
        return default
    return f


def map_kpi_fields(names):
    return classify(
        names, KPI_SLOTS,
        "These are custom field names on a law firm's matter record. Map each to the dashboard slot it fills: "
        "case_value (estimated value or demand), coverage (insurance policy limits), specials (medical bills to "
        "date), lien, or none.",
        _kw([(("lien",), "lien"), (("polic", "coverage", "limit"), "coverage"),
             (("special", "medical bill", "meds"), "specials"), (("value", "demand", "settlement"), "case_value")],
            "none"))


def classify_roles(descriptions):
    return classify(
        descriptions, ROLES,
        "These describe how a contact relates to a legal matter. Classify each. treating_provider means a doctor, "
        "clinic, therapist or hospital treating the client.",
        _kw([(("expert",), "expert"), (("opposing", "defense counsel"), "opposing_counsel"),
             (("insur", "adjuster", "carrier"), "insurer"),
             (("provider", "treat", "physician", "doctor", "clinic", "therap", "surgeon", "chiropract", "hospital",
               "medical"), "treating_provider"),
             (("witness",), "witness")], "other"))
