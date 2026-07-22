class TranscriptStore:
    """Insertion-ordered store of transcript rows keyed by Realtime item_id.

    Each row is ``{"role", "text", "seq", "status"}``. ``seq`` is assigned
    once, monotonically, when an item is first seen, and defines the row
    order shown to the client.
    """

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self._next_seq = 0

    def get_or_create(self, item_id: str, role: str) -> dict:
        """Return the row for ``item_id``, creating it (with a fresh seq) if new."""
        item = self.items.get(item_id)
        if item is None:
            item = dict(
                role=role, text='', seq=self._next_seq,
                status='in_progress',
            )
            self.items[item_id] = item
            self._next_seq += 1
        return item

    def append_delta(self, item_id: str, role: str, delta: str) -> None:
        """Append streamed transcript text to a row (creating it if new)."""
        self.get_or_create(item_id, role)['text'] += delta

    def fill_if_empty(self, item_id: str, role: str, text: str | None) -> None:
        """Set a row's text from a completed transcript, only if still empty.

        Append-only: models that stream deltas first must not have their
        text doubled by the terminal 'completed' event.
        """
        item = self.get_or_create(item_id, role)
        if text and not item['text']:
            item['text'] = text

    def mark_status(self, item_id: str, status: str) -> None:
        """Set a row's status, if the row exists."""
        item = self.items.get(item_id)
        if item is not None:
            item['status'] = status

    def snapshot(self) -> list[tuple[str, dict]]:
        """Return (item_id, row) pairs in creation order for forwarding."""
        return list(self.items.items())

    def reset(self) -> None:
        """Clear all rows and reset the seq counter."""
        self.items = {}
        self._next_seq = 0
