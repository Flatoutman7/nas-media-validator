import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class RadarrClient:
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
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                if resp.status == 204:
                    return {"status": 204}
                return json.loads(resp.read().decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                body = ""
            return {"error": str(e), "status": e.code, "body": body}

    def find_movie_id(self, term: str) -> int | None:
        """
        Lookup movie by term and return the best-matching movie id.
        """

        term = (term or "").strip()
        if not term:
            return None

        results = self._get(f"/api/v3/movie/lookup?term={urllib.parse.quote(term)}")
        if not isinstance(results, list) or not results:
            return None

        term_lower = term.casefold()

        # Pick the best title match.
        best_id = None
        best_score = -1
        for item in results:
            if not isinstance(item, dict):
                continue

            movie_id = item.get("id")
            title = (item.get("title") or item.get("name") or "").strip()
            if movie_id is None or not title:
                continue

            t = title.casefold()
            score = 0
            if t == term_lower:
                score = 100
            elif term_lower in t:
                score = 60
            elif t in term_lower:
                score = 40

            if score > best_score:
                best_score = score
                best_id = int(movie_id)

        return best_id

    def missing_movie_search(self, movie_id: int) -> Any:
        """
        Trigger Radarr missing movie search.

        Radarr's command payload fields can vary by version, so we try a
        couple of common shapes.
        """

        candidates = [
            {"name": "missingMoviesSearch", "movieIds": [movie_id]},
            {"name": "missingMoviesSearch", "movieId": movie_id},
            {"name": "MissingMoviesSearch", "movieIds": [movie_id]},
            {"name": "MissingMoviesSearch", "movieId": movie_id},
        ]

        last_resp: Any = None
        for payload in candidates:
            last_resp = self._post("/api/v3/command", payload)
            # If we got a non-error response, stop.
            if isinstance(last_resp, dict) and "error" not in last_resp:
                return last_resp

        return last_resp
