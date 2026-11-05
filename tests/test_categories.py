from __future__ import annotations

from local_presence_miner.domain.categories import all_categories, category_from_label, grouped_category_labels


def test_category_catalog_is_large_and_grouped() -> None:
    assert len(all_categories()) >= 100
    assert any("roofers" in label for label in grouped_category_labels())
    assert category_from_label("Home Services / plumbers") == "plumbers"
