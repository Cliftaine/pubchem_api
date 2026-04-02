import pickle
from collections import OrderedDict
from pathlib import Path

from app.models import ProductResult

CACHE_PATH = Path(__file__).resolve().parent.parent / "cache.pickle"
MAX_SIZE = 100


class HazardCache:
    """In-memory LRU cache backed by a pickle file.

    Stores up to MAX_SIZE ProductResult entries keyed by product name
    (lowercased). On startup, loads previous state from disk. On every
    write, persists to disk so the cache survives restarts.
    """

    def __init__(self) -> None:
        self._data: OrderedDict[str, ProductResult] = OrderedDict()
        self._load()

    def get(self, name: str) -> ProductResult | None:
        key = name.lower()
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        return None

    def put(self, name: str, result: ProductResult) -> None:
        key = name.lower()
        self._data[key] = result
        self._data.move_to_end(key)
        if len(self._data) > MAX_SIZE:
            self._data.popitem(last=False)
        self._save()

    def _load(self) -> None:
        if not CACHE_PATH.exists():
            return
        try:
            with open(CACHE_PATH, "rb") as f:
                data = pickle.load(f)
            if isinstance(data, OrderedDict):
                self._data = data
        except Exception:
            self._data = OrderedDict()

    def _save(self) -> None:
        try:
            with open(CACHE_PATH, "wb") as f:
                pickle.dump(self._data, f)
        except Exception:
            pass
