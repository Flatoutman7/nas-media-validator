import json
from urllib.parse import parse_qs, urlsplit
from unittest.mock import MagicMock

import pytest

from nas_checker.arr.radarr_client import RadarrClient
from nas_checker.arr.sonarr_client import SonarrClient


@pytest.mark.parametrize('client_type,method', [
    (SonarrClient, 'find_series_id'), (RadarrClient, 'find_movie_id')])
def test_lookup_preserves_query_and_authenticates_with_header(monkeypatch, client_type, method):
    requests = []
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps([
        {'id': 42, 'title': 'Movie & Show'}]).encode()

    def urlopen(request, timeout):
        requests.append(request)
        return response

    monkeypatch.setattr('urllib.request.urlopen', urlopen)
    client = client_type('http://example.invalid', 'test-secret')
    assert getattr(client, method)('Movie & Show') == 42
    request = requests[0]
    assert parse_qs(urlsplit(request.full_url).query) == {'term': ['Movie & Show']}
    assert request.get_header('X-api-key') == 'test-secret'
    assert 'test-secret' not in request.full_url
