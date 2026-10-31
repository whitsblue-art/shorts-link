"""Affiliate product search and deeplinks. Keys are never included in diagnostics."""
from datetime import datetime, timezone
import hashlib
import hmac
import os
import re
from urllib.parse import urlencode, urlparse, parse_qs

import requests

from .core import GateError

API_ROOT = "https://api-gateway.coupang.com"
PREFIX = "/v2/providers/affiliate_open_api/apis/openapi"


def authorization(method, path, query, access, secret, now=None):
    now = now or datetime.now(timezone.utc)
    stamp = now.astimezone(timezone.utc).strftime("%y%m%dT%H%M%SZ")
    message = stamp + method.upper() + path + query
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"CEA algorithm=HmacSHA256, access-key={access}, signed-date={stamp}, signature={signature}"


def coupang_url(value):
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and not parsed.username and parsed.port in (None, 443) and (
        host == "coupang.com" or host.endswith(".coupang.com"))


def normalize_product(item):
    pid = str(item.get("productId", ""))
    name, image, url = item.get("productName"), item.get("productImage"), item.get("productUrl")
    if not re.fullmatch(r"[1-9]\d{0,19}", pid) or not all(isinstance(v, str) and v.strip() for v in (name, image, url)):
        raise GateError("Affiliate API returned incomplete product identity")
    if not coupang_url(url) or urlparse(image).scheme != "https":
        raise GateError("Affiliate API returned an invalid product/image URL")
    query = parse_qs(urlparse(url).query)
    page_key = query.get("pageKey", [None])[0]
    if page_key and page_key != pid:
        raise GateError("Product URL and product ID do not match")
    options = {k: query[k][0] for k in ("itemId", "vendorItemId") if k in query}
    canonical = f"https://www.coupang.com/vp/products/{pid}"
    if options:
        canonical += "?" + urlencode(options)
    return {"product_id": pid, "title": name.strip(), "reference_image": image,
            "source_url": url, "canonical_url": canonical, "price": item.get("productPrice"),
            "category": item.get("categoryName", ""), "is_rocket": item.get("isRocket", False)}


class Coupang:
    def __init__(self, access=None, secret=None):
        self.access = access or os.getenv("COUPANG_ACCESS_KEY", "").strip()
        self.secret = secret or os.getenv("COUPANG_SECRET_KEY", "").strip()
        if not self.access or not self.secret:
            raise GateError("Set COUPANG_ACCESS_KEY and COUPANG_SECRET_KEY in this repository's Actions Secrets")
        self.search_path = os.getenv("COUPANG_SEARCH_PATH", PREFIX + "/products/search")
        self.deeplink_path = os.getenv("COUPANG_DEEPLINK_PATH", PREFIX + "/v1/deeplink")

    def request(self, method, path, params=None, body=None):
        if not path.startswith(PREFIX + "/") or "?" in path:
            raise GateError("Invalid affiliate API path")
        query = urlencode(params or {})
        url = API_ROOT + path + ("?" + query if query else "")
        header = authorization(method, path, query, self.access, self.secret)
        try:
            response = requests.request(method, url, headers={"Authorization": header,
                "Content-Type": "application/json;charset=UTF-8"}, json=body, timeout=(15, 45))
        except requests.RequestException:
            raise GateError("Affiliate API network failure") from None
        if response.status_code >= 400:
            raise GateError(f"Affiliate API HTTP {response.status_code}; check key type/permissions/endpoint")
        try:
            result = response.json()
        except ValueError:
            raise GateError("Affiliate API returned invalid JSON") from None
        if str(result.get("rCode")) != "0":
            code = re.sub(r"[^A-Za-z0-9_-]", "", str(result.get("rCode", "unknown")))[:30]
            raise GateError(f"Affiliate API did not approve request (rCode={code})")
        return result.get("data")

    def search(self, keyword, limit=10):
        limit = max(1, min(int(limit), 10))
        data = self.request("GET", self.search_path, {"keyword": keyword, "limit": limit})
        items = data.get("productData", []) if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise GateError("Affiliate product search schema is invalid")
        products = []
        for item in items:
            try:
                products.append(normalize_product(item))
            except (GateError, TypeError, AttributeError):
                continue
        if not products:
            raise GateError("Affiliate API returned no usable products")
        return products

    def deeplink(self, product):
        original = product["canonical_url"]
        data = self.request("POST", self.deeplink_path, body={"coupangUrls": [original]})
        if not isinstance(data, list):
            raise GateError("Affiliate deeplink response schema is invalid")
        entry = next((row for row in data if row.get("originalUrl") == original), None)
        link = entry.get("shortenUrl") if entry else None
        if not isinstance(link, str) or not coupang_url(link) or urlparse(link).hostname != "link.coupang.com":
            raise GateError("Exact product deeplink could not be verified; search links are not substituted")
        return link
