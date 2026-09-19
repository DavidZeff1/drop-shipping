"""JSON-file persistence.

One file, human-readable, greppable, and safe to commit to a private repo if
you want history. A solo operator running a few hundred orders a month will
never outgrow this; if you do, the shape maps cleanly onto SQLite.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Iterable, TypeVar

from .models import (
    AdTest,
    Config,
    LedgerEntry,
    Order,
    Product,
    Supplier,
    now_iso,
)

T = TypeVar("T")

DEFAULT_PATH = Path(os.environ.get("DROPSHIP_STORE", "data/store.json"))

_COLLECTIONS = {
    "suppliers": Supplier,
    "products": Product,
    "tests": AdTest,
    "orders": Order,
    "ledger": LedgerEntry,
}


class Store:
    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.path = Path(path)
        self.config = Config()
        self.suppliers: list[Supplier] = []
        self.products: list[Product] = []
        self.tests: list[AdTest] = []
        self.orders: list[Order] = []
        self.ledger: list[LedgerEntry] = []
        self._loaded = False

    # ------------------------------------------------------------- load/save

    @classmethod
    def load(cls, path: Path | str = DEFAULT_PATH) -> "Store":
        store = cls(path)
        if store.path.exists():
            raw = json.loads(store.path.read_text() or "{}")
            store.config = Config.from_dict(raw.get("config", {}))
            for key, model in _COLLECTIONS.items():
                setattr(store, key, [model.from_dict(d) for d in raw.get(key, [])])
        store._loaded = True
        return store

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "_schema": 1,
            "_saved": now_iso(),
            "config": self.config.to_dict(),
        }
        for key in _COLLECTIONS:
            payload[key] = [r.to_dict() for r in getattr(self, key)]

        # Keep one backup. Cheap insurance against a bad import wiping months
        # of order history.
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(".bak.json"))

        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=False))
        tmp.replace(self.path)
        return self.path

    # -------------------------------------------------------------- lookups

    @staticmethod
    def _find(items: Iterable[T], ident: str) -> T | None:
        """Match on id, then sku, then a unique case-insensitive name prefix."""
        ident = (ident or "").strip()
        if not ident:
            return None
        items = list(items)
        for item in items:
            if getattr(item, "id", None) == ident:
                return item
        for item in items:
            if getattr(item, "sku", None) and item.sku == ident:
                return item
        for item in items:
            if getattr(item, "external_id", None) and item.external_id == ident:
                return item
        low = ident.lower()
        matches = [i for i in items if getattr(i, "name", "").lower().startswith(low)]
        return matches[0] if len(matches) == 1 else None

    def product(self, ident: str) -> Product | None:
        return self._find(self.products, ident)

    def supplier(self, ident: str) -> Supplier | None:
        return self._find(self.suppliers, ident)

    def order(self, ident: str) -> Order | None:
        return self._find(self.orders, ident)

    def test(self, ident: str) -> AdTest | None:
        return self._find(self.tests, ident)

    def tests_for(self, product_id: str) -> list[AdTest]:
        return [t for t in self.tests if t.product_id == product_id]

    def orders_for(self, product_id: str) -> list[Order]:
        return [o for o in self.orders if o.product_id == product_id]

    def active_test(self, product_id: str) -> AdTest | None:
        """Most recent test with no end date."""
        live = [t for t in self.tests_for(product_id) if not t.ended]
        return sorted(live, key=lambda t: t.started)[-1] if live else None

    # ----------------------------------------------------------------- adds

    def add(self, record) -> Any:
        for key, model in _COLLECTIONS.items():
            if isinstance(record, model):
                getattr(self, key).append(record)
                return record
        raise TypeError(f"don't know where to put {type(record).__name__}")

    def remove(self, record) -> bool:
        for key, model in _COLLECTIONS.items():
            if isinstance(record, model):
                coll = getattr(self, key)
                if record in coll:
                    coll.remove(record)
                    return True
        return False
