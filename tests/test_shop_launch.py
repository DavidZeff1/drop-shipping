"""Regression coverage for rebuilding and exporting customer-facing shop pages."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from dropship import cli, shop_content, storefront, ui
from dropship.models import Product
from dropship.store import Store


class TestShopLaunch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "store.json")
        self.product = Product(
            name="Test product", sku="TEST-1", status="approved", price=49.99,
            cogs=8, ship_cost=2, pay_url="https://checkout.example.com/item",
            photos=["https://images.example.com/item.jpg"])
        self.store.add(self.product)
        self.store.save()
        self.content_path = shop_content.default_path(self.store.path)

    def run_cli(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = cli.main(["--store", str(self.store.path), *map(str, args)])
        self.assertEqual(code, 0)
        return output.getvalue()

    def fill_template(self):
        self.run_cli("site", "--content-template", self.content_path)
        data = json.loads(self.content_path.read_text())
        # Synthetic answers exercise the renderer; they are never launch facts.
        for key in data["shared"]:
            data["shared"][key] = "Test policy & details"
        for answers in data["products"].values():
            for key in answers:
                answers[key] = "Test product detail"
        data["shared"]["your support email"] = "support@example.com"
        self.content_path.write_text(json.dumps(data))
        return shop_content.Content.load(self.content_path)

    def test_saved_content_completes_every_page_and_survives_rebuilding(self):
        content = self.fill_template()
        first = storefront.build_site(self.store.products, self.store.config, content)
        self.assertEqual(first.issues, [])
        self.assertTrue(first.publishable)
        self.assertEqual(first.total_slots, 0)
        self.assertNotIn('<mark class="slot">', "".join(first.files.values()))
        rebuilt = storefront.build_site(
            Store.load(self.store.path).products, self.store.config,
            shop_content.Content.load(self.content_path))
        self.assertEqual(first.files, rebuilt.files)
        for page in ("test-1.html", "refunds.html", "contact.html", "thanks.html"):
            self.assertIn("support@example.com", rebuilt.files[page])

    def test_template_keeps_unapproved_candidates_available_to_prepare(self):
        self.product.status = "candidate"
        self.store.save()
        self.run_cli("site", "--content-template", self.content_path)
        data = json.loads(self.content_path.read_text())
        self.assertIn(self.product.id, data["products"])
        self.assertTrue(all(value == "" for value in data["shared"].values()))
        self.assertNotIn("test-1.html", storefront.build_site(
            self.store.products, self.store.config).files)

    def test_template_never_overwrites_existing_answers(self):
        self.fill_template()
        before = self.content_path.read_bytes()
        with self.assertRaises(SystemExit):
            self.run_cli("site", "--content-template", self.content_path)
        self.assertEqual(before, self.content_path.read_bytes())

    def test_blank_answers_remain_blockers(self):
        self.run_cli("site", "--content-template", self.content_path)
        site = storefront.build_site(self.store.products, self.store.config,
                                     shop_content.Content.load(self.content_path))
        self.assertFalse(site.publishable)
        self.assertGreater(site.total_slots, 0)

    def test_replacement_escapes_text_and_attributes_without_changing_css(self):
        page = '<style>.x {color:red}</style><title>{title}</title><p><mark class="slot">{body}</mark></p>'
        result = shop_content.fill(page, {"title": '\"><script>bad</script>',
                                          "body": "A & B", "color:red": "bad"})
        self.assertNotIn("<script>", result)
        self.assertIn("&quot;&gt;&lt;script&gt;", result)
        self.assertIn("<p>A &amp; B</p>", result)
        self.assertIn("<style>.x {color:red}</style>", result)

    def test_product_answers_are_scoped_by_id(self):
        other = Product(name="Other")
        content = shop_content.Content(shared={"title": "Shared"},
                                       products={self.product.id: {"title": "Specific"}})
        self.assertEqual(content.for_product(self.product)["title"], "Specific")
        self.assertEqual(content.for_product(other)["title"], "Shared")

    def test_invalid_content_is_reported_before_writing(self):
        for bad in ([], {"shared": {"email": 1}}, {"products": {"id": []}}, {"typo": {}}):
            with self.subTest(bad=bad):
                self.content_path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    shop_content.Content.load(self.content_path)
                with self.assertRaises(SystemExit):
                    self.run_cli("site", "--out", self.root / "site")
                self.assertFalse((self.root / "site").exists())

    def test_ui_preview_uses_the_same_saved_answers(self):
        self.fill_template()
        result = ui.App(self.store.path).handle("GET", "/shop", {"id": self.product.id}, {})
        self.assertEqual(result.status, 200)
        self.assertIn("support@example.com", result.body)
        self.assertNotIn('<mark class="slot">', result.body)
        self.content_path.write_text("not json")
        result = ui.App(self.store.path).handle("GET", "/shop", {"id": self.product.id}, {})
        self.assertEqual(result.status, 400)
        self.assertIn("Cannot read shop content", result.body)

    def test_failed_release_preserves_existing_output_and_store(self):
        output = self.root / "site"
        output.mkdir()
        (output / "index.html").write_text("Existing published shop")
        before = self.store.path.read_bytes()
        with self.assertRaises(SystemExit) as caught:
            self.run_cli("site", "--ready", "--out", output)
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual((output / "index.html").read_text(), "Existing published shop")
        self.assertEqual(list(output.iterdir()), [output / "index.html"])
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertFalse((self.root / "site.notes.md").exists())

    def test_successful_check_is_read_only_and_release_exports(self):
        self.fill_template()
        output = self.root / "site"
        self.run_cli("site", "--check", "--out", output)
        self.assertFalse(output.exists())
        self.run_cli("site", "--ready", "--out", output)
        self.assertTrue((output / "test-1.html").exists())
        self.assertNotIn(".json", " ".join(p.name for p in output.iterdir()))

    def test_export_refuses_to_leave_old_product_pages_available(self):
        self.fill_template()
        output = self.root / "site"
        output.mkdir()
        (output / "killed-product.html").write_text("Old buy button")
        with self.assertRaisesRegex(SystemExit, "fresh --out folder"):
            self.run_cli("site", "--ready", "--out", output)
        self.assertEqual(list(output.iterdir()), [output / "killed-product.html"])

    def test_storefront_check_does_not_persist_proposed_changes(self):
        self.fill_template()
        before = self.store.path.read_bytes()
        output = self.root / "product.html"
        self.run_cli("storefront", self.product.id, "--check", "--pay",
                     "https://checkout.example.com/new", "--out", output)
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertFalse(output.exists())
        with self.assertRaises(SystemExit):
            self.run_cli("storefront", self.product.id, "--ready", "--pay",
                         "javascript:alert(1)", "--out", output)
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertFalse(output.exists())

    def test_invalid_payment_links_never_become_clickable(self):
        for url in ("javascript:alert(1)", "https://", "https://user:pass@example.com", "https://bad host/x"):
            with self.subTest(url=url):
                self.product.pay_url = url
                self.product.bundle_price = 80
                self.product.bundle_pay_url = url
                page = storefront.build(self.product, self.store.config)
                self.assertNotIn('href="' + url + '"', page.html)
                self.assertTrue(any("payment link" in issue for issue in page.issues))

    def test_duplicate_and_reserved_product_filenames_fail(self):
        for sku in ("TEST-1", "index", "refunds", "thanks"):
            other = Product(name="Other", sku=sku, status="approved")
            with self.subTest(sku=sku), self.assertRaisesRegex(ValueError, "filename"):
                storefront.build_site([self.product, other], self.store.config)

    def test_shekel_prices_are_unambiguous(self):
        self.store.config.currency = "ILS"
        page = storefront.build(self.product, self.store.config)
        self.assertIn("₪49.99", page.html)

    def test_unverified_confirmation_and_empty_reviews_are_absent(self):
        site = storefront.build_site(self.store.products, self.store.config)
        self.assertNotIn("your order is confirmed", site.files["thanks.html"])
        self.assertIn("cannot verify payment", site.files["thanks.html"])
        self.assertNotIn("<h2>Reviews</h2>", site.files["test-1.html"])

    def test_unknown_price_and_delivery_are_not_customer_promises(self):
        self.product.price = 0
        self.product.delivery_days = 0
        page = storefront.build(self.product, self.store.config)
        self.assertIn("Price not set", page.html)
        self.assertNotIn("$0.00", page.html)
        self.assertNotIn("about 0 days", page.html)
        self.assertNotIn('href="https://checkout.example.com/item"', page.html)
        self.assertTrue(any("delivery_days" in issue for issue in page.issues))
        self.assertFalse(page.publishable)

    def test_empty_store_has_no_invented_delivery_estimate(self):
        site = storefront.build_site([], self.store.config)
        for name in ("shipping.html", "thanks.html"):
            self.assertNotIn("14 days", site.files[name])
            self.assertTrue(shop_content.slots(site.files[name]))


if __name__ == "__main__":
    unittest.main()
