from __future__ import annotations

import requests

from local_presence_miner.services.public_url_safety import Resolver, UnsafePublicUrlError, resolve_public_addresses, validate_public_url


class PageSpeedClient:
    def __init__(self, api_key: str = "", timeout_seconds: int = 30, *, resolver: Resolver = resolve_public_addresses) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.resolver = resolver

    def run(self, url: str) -> dict[str, int | str | None]:
        if not url:
            return {"pagespeed_status": "unavailable", "pagespeed_error": "No website URL was captured."}
        if not self.api_key:
            return {
                "pagespeed_status": "unavailable",
                "pagespeed_error": "Configuration required: add a PageSpeed API key in Settings.",
            }
        try:
            url = validate_public_url(url, resolver=self.resolver).url
        except UnsafePublicUrlError as exc:
            return {"pagespeed_status": "security_unavailable", "pagespeed_error": str(exc)}
        params = {"url": url, "strategy": "mobile", "category": ["performance", "accessibility", "best-practices", "seo"]}
        if self.api_key:
            params["key"] = self.api_key
        try:
            response = requests.get(
                "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                params=params,
                timeout=self.timeout_seconds,
                allow_redirects=False,
            )
            if 300 <= response.status_code < 400:
                return {"pagespeed_status": "failed", "pagespeed_error": "Unexpected PageSpeed API redirect was not followed."}
            if response.status_code == 429:
                return {"pagespeed_status": "failed", "pagespeed_error": "PageSpeed rate limit reached. Try again later."}
            response.raise_for_status()
            lighthouse = response.json().get("lighthouseResult", {})
        except requests.Timeout:
            return {"pagespeed_status": "failed", "pagespeed_error": "PageSpeed request timed out."}
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            return {"pagespeed_status": "failed", "pagespeed_error": f"PageSpeed API request failed (HTTP {status})."}
        except requests.RequestException:
            return {"pagespeed_status": "failed", "pagespeed_error": "PageSpeed network request failed."}
        except ValueError:
            return {"pagespeed_status": "failed", "pagespeed_error": "PageSpeed returned an invalid response."}
        categories = lighthouse.get("categories", {})
        return {
            "pagespeed_status": "successful",
            "performance": score(categories.get("performance")),
            "accessibility": score(categories.get("accessibility")),
            "best_practices": score(categories.get("best-practices")),
            "seo": score(categories.get("seo")),
        }


def score(category: dict | None) -> int | None:
    if not category or category.get("score") is None:
        return None
    return round(float(category["score"]) * 100)
