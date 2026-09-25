"""Persistent, plain-text answers to the shop's copy and policy placeholders.

Keep this file beside the private store, not in the published shop folder.
Empty answers remain visible placeholders; this module never invents policies.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import Product

_SLOT = re.compile(r"\{([^{}]{1,200})\}")
_TOKEN = re.compile(
    r'(<style>.*?</style>)|<mark class="slot">(\{[^{}]{1,200}\})</mark>'
    r'|(\{[^{}]{1,200}\})', re.S)


def default_path(store_path: Path | str) -> Path:
    return Path(store_path).with_suffix(".content.json")


def slots(page: str) -> set[str]:
    page = re.sub(r"<style>.*?</style>", "", page, flags=re.S)
    return {html.unescape(m.group(1)) for m in _SLOT.finditer(page)}


def fill(page: str, answers: dict[str, str]) -> str:
    """Fill once, escaping answers in both text and attribute contexts."""
    def replace(match: re.Match) -> str:
        if match.group(1):
            return match.group(0)  # Stylesheet braces are not copy.
        token = match.group(2) or match.group(3)
        answer = answers.get(html.unescape(token[1:-1]), "")
        return html.escape(answer, quote=True) if answer.strip() else match.group(0)

    return _TOKEN.sub(replace, page)


@dataclass
class Content:
    shared: dict[str, str] = field(default_factory=dict)
    products: dict[str, dict[str, str]] = field(default_factory=dict)

    def for_product(self, product: Product) -> dict[str, str]:
        return {**self.shared, **self.products.get(product.id, {})}

    @classmethod
    def load(cls, path: Path | str, *, optional: bool = False) -> "Content":
        path = Path(path)
        if optional and not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Cannot read shop content {path}: {exc}") from exc
        if not isinstance(data, dict) or set(data) - {"shared", "products"}:
            raise ValueError("Shop content must contain only 'shared' and 'products' objects.")
        shared, products = data.get("shared", {}), data.get("products", {})

        def answers(value) -> bool:
            return isinstance(value, dict) and all(
                isinstance(k, str) and isinstance(v, str) for k, v in value.items())

        if not answers(shared) or not isinstance(products, dict) or not all(
                isinstance(key, str) and answers(value) for key, value in products.items()):
            raise ValueError("Shop content answers must be text; products must be keyed by product ID.")
        return cls(shared=shared, products=products)

    def write_template(self, path: Path | str, shared_pages: list[str],
                       product_pages: dict[str, str]) -> Path:
        """Create a new answer sheet without overwriting an existing one."""
        shared = set().union(*(slots(page) for page in shared_pages))
        data = {
            "shared": {key: self.shared.get(key, "") for key in sorted(shared)},
            "products": {
                ident: {key: self.products.get(ident, {}).get(key, "")
                        for key in sorted(slots(page) - shared)}
                for ident, page in product_pages.items()
            },
        }
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        return target
