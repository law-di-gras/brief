"""Offline stand-in for ClioReadOnly, served from the seed JSON (CLIO_SOURCE=fixture).

It answers the same GET paths sync.py uses, shaped like Clio v4 responses, so the
whole pipeline can be exercised without a Clio account. Read-only like the real one.
"""
import os
import re
from pathlib import Path
import json

PLACEHOLDER = re.compile(r"\{\{([^}:]+)(?::([^}]+))?\}\}")


def seed_path() -> Path:
    return Path(os.environ.get("SEED_PATH", "../doc/sapini-clio-data.json"))


class FixtureClio:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or seed_path())
        self.seed = json.loads(self.path.read_text())
        self.matter_id = int(os.environ.get("MATTER_ID", "1") or 1)
        self.user = {"id": 1, "name": "Firm User", "type": "User"}
        self.contacts = {}
        for i, c in enumerate(self.seed["contacts"]["items"]):
            b = c["body"]
            name = b.get("name") or " ".join(x for x in [b.get("first_name"), b.get("last_name")] if x)
            self.contacts[c["ref"]] = {"id": 1000 + i, "name": name, "type": b.get("type", "Person")}
        self.field_ids = {}
        for i, f in enumerate(self.seed["custom_fields"]["items"]):
            self.field_ids[f["body"]["name"]] = 500 + i
        self.folders = {}
        for i, f in enumerate(self.seed.get("folders", {}).get("items", [])):
            self.folders[f["body"]["name"]] = 800 + i

    # -- placeholder resolution -------------------------------------------------
    def _ref(self, kind, arg):
        if kind == "contact":
            return self.contacts[arg]
        if kind == "user_id":
            return self.user
        if kind == "matter_id":
            return {"id": self.matter_id}
        if kind == "field":
            return {"id": self.field_ids.get(arg), "name": arg}
        if kind == "stage":
            return {"id": 700, "name": arg}
        if kind == "practice_area_id":
            return {"id": 600, "name": "Personal Injury"}
        if kind == "folder":
            return {"id": self.folders.get(arg, 899), "name": arg}
        if kind == "calendar_id":
            return {"id": 1, "name": "Firm User"}
        return {"id": None}

    def _resolve(self, obj):
        """Replace {"id": "{{contact:x}}"} style references with id + name, like Clio's nested records."""
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if k == "id" and isinstance(v, str) and (m := PLACEHOLDER.fullmatch(v)):
                    ref = self._ref(m.group(1), m.group(2))
                    out.update({kk: vv for kk, vv in ref.items()})
                else:
                    out[k] = self._resolve(v)
            return out
        if isinstance(obj, list):
            return [self._resolve(x) for x in obj]
        if isinstance(obj, str) and (m := PLACEHOLDER.fullmatch(obj)):
            return self._ref(m.group(1), m.group(2)).get("id")
        return obj

    def _list(self, section, id_base):
        out = []
        for i, it in enumerate(self.seed[section]["items"]):
            rec = self._resolve(it["body"])
            rec["id"] = id_base + i
            rec.setdefault("created_at", "2026-10-01T00:00:00Z")
            rec.setdefault("updated_at", "2026-10-01T00:00:00Z")
            out.append(rec)
        return out

    # -- the one public method ----------------------------------------------------
    def get(self, path: str, params: dict | None = None, raw: bool = False):
        if path == "/users/who_am_i.json":
            return {"data": self.user}
        if re.fullmatch(r"/matters/\d+\.json", path):
            m = self._resolve(self.seed["matter"]["body"])
            m["id"] = self.matter_id
            m["display_number"] = f"{self.matter_id:05d}-Sapini"
            cfv = []
            for i, v in enumerate(self.seed["matter"]["body"].get("custom_field_values", [])):
                name = PLACEHOLDER.fullmatch(v["custom_field"]["id"]).group(2)
                cfv.append({"id": f"cfv{i}", "field_name": name, "value": v["value"],
                            "custom_field": {"id": self.field_ids.get(name)}})
            m["custom_field_values"] = cfv
            return {"data": m}
        if path == "/relationships.json":
            return {"data": self._list("relationships", 100)}
        if path == "/notes.json":
            return {"data": self._list("notes", 2000)}
        if path == "/communications.json":
            return {"data": self._list("communications", 3000)}
        if path == "/tasks.json":
            return {"data": self._list("tasks", 4000)}
        if path == "/calendar_entries.json":
            return {"data": self._list("calendar_entries", 5000)}
        if path == "/activities.json":
            out = self._list("expenses", 6000)
            for r in out:
                r["total"] = float(r.get("price", 0)) * float(r.get("quantity", 1))
            return {"data": out}
        if path == "/documents.json":
            out = []
            for i, it in enumerate(self.seed["documents"]["items"]):
                rec = self._resolve(it["body"])
                rec.update(id=7000 + i, content_type="application/pdf",
                           latest_document_version={"uuid": it.get("sha256", "")[:16], "size": it.get("bytes")})
                out.append(rec)
            return {"data": out}
        if m := re.fullmatch(r"/documents/(\d+)/download", path):
            item = self.seed["documents"]["items"][int(m.group(1)) - 7000]
            return (self.path.parent / item["local_path"]).read_bytes()
        raise KeyError(f"fixture has no route for {path}")
