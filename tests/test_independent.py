from backend.pipeline.analyze import independent, origin


def item(item_id, clio_type, sender=None, doc_type=None):
    people = [{"id": sender, "role": "sender"}] if sender else []
    import json
    return {"item_id": item_id, "clio_type": clio_type, "people_json": json.dumps(people), "doc_type": doc_type}


ITEMS = {i["item_id"]: i for i in [
    item("doc:7:p3", "document", doc_type="pleading"), item("doc:7:p40", "document", doc_type="pleading"),
    item("doc:8:p1", "document", doc_type="pleading"), item("doc:9:p2", "document", doc_type="medical_bills_or_liens"),
    item("doc:10:p2", "document", doc_type="medical_bills_or_liens"),
    item("note:1", "note"), item("note:2", "note"), item("matter:9", "matter"),
    item("comm:1", "communication", "contact:5"), item("comm:2", "communication", "contact:5"),
    item("comm:3", "communication", "user:1"), item("task:1", "task"), item("task:2", "task"),
]}


def test_pages_of_one_document_are_one_origin():
    assert origin(ITEMS["doc:7:p3"]) == origin(ITEMS["doc:7:p40"])
    assert not independent({"doc:7:p3", "doc:7:p40"}, ITEMS)


def test_documents_count_only_when_their_types_differ():
    assert not independent({"doc:7:p3", "doc:8:p1"}, ITEMS)       # two pleadings
    assert not independent({"doc:9:p2", "doc:10:p2"}, ITEMS)      # two bills
    assert independent({"doc:7:p3", "doc:9:p2"}, ITEMS)           # pleading vs bill
    assert independent({"doc:7:p3", "note:1"}, ITEMS)


def test_two_notes_or_two_tasks_do_not_count():
    assert not independent({"note:1", "note:2"}, ITEMS)
    assert not independent({"task:1", "task:2"}, ITEMS)


def test_record_vs_note_counts():
    assert independent({"matter:9", "note:1"}, ITEMS)


def test_emails_count_only_with_different_senders():
    assert not independent({"comm:1", "comm:2"}, ITEMS)
    assert independent({"comm:1", "comm:3"}, ITEMS)
