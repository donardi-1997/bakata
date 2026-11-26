import json
import sqlite3
from .adapters import FixtureAdapter
from .repository import ObservationStore


def main():
    with sqlite3.connect(":memory:") as db:
        store = ObservationStore(db)
        batch = FixtureAdapter().collect()
        first = store.ingest(batch)
        replay = store.ingest(batch)
        print(json.dumps({"mode": "fixture", "inserted": first, "replayed": replay, "observations": store.count()}))


if __name__ == "__main__":
    main()
