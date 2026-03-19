import json
import urllib.parse
import urllib.request
from typing import Any


class SonarrClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _get(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        url = f"{url}?apikey={urllib.parse.quote(self.api_key)}"

        req = urllib.request.Request(url, method="GET")
        req.add_header("X-Api-Key", self.api_key)
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        url = f"{url}?apikey={urllib.parse.quote(self.api_key)}"

        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "X-Api-Key": self.api_key,
        }

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status == 204:
                return {"status": 204}
            return json.loads(resp.read().decode("utf-8", errors="ignore"))

    def find_series_id(self, term: str) -> int | None:
        """
        Lookup series by term and return the best-matching series id.
        """

        term = (term or "").strip()
        if not term:
            return None

        results = self._get(f"/api/v3/series/lookup?term={urllib.parse.quote(term)}")

        if not isinstance(results, list):
            return None

        term_lower = term.casefold()
        best = None
        best_score = -1

        for item in results:
            if not isinstance(item, dict):
                continue

            series_id = item.get("id")
            if series_id is None:
                continue

            title = (item.get("title") or item.get("name") or "").strip()
            title_lower = title.casefold()

            score = 0
            if title_lower == term_lower:
                score = 100
            elif title_lower and term_lower in title_lower:
                score = 50
            elif title_lower and title_lower in term_lower:
                score = 40

            if score > best_score:
                best_score = score
                best = int(series_id)

        return best

    def missing_episode_search(self, series_id: int) -> Any:
        """
        Trigger Sonarr's MissingEpisodeSearch command for a series.
        """

        payload = {"name": "MissingEpisodeSearch", "seriesId": series_id}
        return self._post("/api/v3/command", payload)
