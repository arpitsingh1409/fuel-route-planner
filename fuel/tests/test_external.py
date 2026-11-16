from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase

from fuel.exceptions import UpstreamUnavailable
from fuel.services import external


def response(status, json=None, error=None):
    return Mock(status_code=status, json=Mock(return_value=json, side_effect=error))


@patch("fuel.services.external._session.get")
class GetJsonTests(SimpleTestCase):
    def test_outages_raise_upstream_unavailable(self, get):
        for case in [
            requests.Timeout(),
            response(502),
            response(429),
            response(200, error=requests.JSONDecodeError("Expecting value", "<html>", 0)),
        ]:
            with self.subTest(case=case):
                get.side_effect, get.return_value = (case, None) if isinstance(case, Exception) else (None, case)
                with self.assertRaises(UpstreamUnavailable):
                    external.get_json("https://example.test")

    def test_client_error_body_is_returned_as_is(self, get):
        get.return_value = response(400, json={"code": "NoRoute"})
        self.assertEqual(external.get_json("https://example.test"), {"code": "NoRoute"})
