from src.realtime.transcript import TranscriptStore


def test_get_or_create_assigns_incrementing_seq_once():
    store = TranscriptStore()

    first = store.get_or_create("item_A", "user")
    second = store.get_or_create("item_B", "assistant")
    again = store.get_or_create("item_A", "user")

    assert first["seq"] == 0
    assert first["role"] == "user"
    assert first["status"] == "in_progress"
    assert second["seq"] == 1
    assert again is first
    assert first["seq"] == 0
    assert list(store.items.keys()) == ["item_A", "item_B"]


def test_append_delta_accumulates_text():
    store = TranscriptStore()
    store.append_delta("item_A", "user", "Hel")
    store.append_delta("item_A", "user", "lo")
    assert store.items["item_A"]["text"] == "Hello"


def test_fill_if_empty_only_when_empty():
    store = TranscriptStore()
    store.append_delta("item_A", "user", "streamed")
    store.fill_if_empty("item_A", "user", "completed")
    assert store.items["item_A"]["text"] == "streamed"

    store.fill_if_empty("item_B", "user", "completed")
    assert store.items["item_B"]["text"] == "completed"


def test_mark_status_noop_when_missing():
    store = TranscriptStore()
    store.mark_status("ghost", "done")  # must not raise
    store.get_or_create("item_A", "assistant")
    store.mark_status("item_A", "done")
    assert store.items["item_A"]["status"] == "done"


def test_snapshot_and_reset():
    store = TranscriptStore()
    store.get_or_create("item_A", "user")
    assert store.snapshot() == list(store.items.items())
    store.reset()
    assert store.items == {}
    assert store.get_or_create("x", "user")["seq"] == 0
