from .core import GateError, Journal, fingerprint, utc_now


def validate_catalogue(products):
    if not isinstance(products, list):
        raise GateError("products.json must be an array")
    ids = [p.get("id") for p in products if isinstance(p, dict)]
    if len(ids) != len(products) or any(type(n) is not int or n < 1 for n in ids) or len(ids) != len(set(ids)):
        raise GateError("Catalog IDs must be unique positive integers; history is not reset")
    return products


class Ledger(Journal):
    def pending(self):
        return next((e for e in self.data["episodes"].values() if e["status"] not in ("published", "rejected")), None)

    def next_number(self, products):
        ids = [p["id"] for p in validate_catalogue(products)]
        ids += [e["catalogue_id"] for e in self.data["episodes"].values() if e["status"] != "rejected"]
        return max([14] + ids) + 1

    def seen(self, product, products):
        from .core import normalize
        return (any(e["product"]["product_id"] == product["product_id"] and e["status"] != "rejected"
                    for e in self.data["episodes"].values()) or
                any(p.get("verified") is True and (str(p.get("coupang_product_id")) == product["product_id"]
                    or normalize(p.get("title", "")) == normalize(product["title"])) for p in products))

    def reserve(self, product, number):
        eid = fingerprint({"product_id": product["product_id"], "version": 1})[:24]
        existing = self.data["episodes"].get(eid)
        if existing and existing["status"] != "rejected":
            return existing
        entry = {"id": eid, "format": "shorts", "topic": product["title"], "mode": "shopping",
                 "catalogue_id": number, "product": product, "status": "reserved", "created_at": utc_now()}
        self.data["episodes"][eid] = entry
        self.save()
        return entry
