import json
import threading
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal


class WebPortalTests(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock(serial="test-board")
        self.connection.request.side_effect = lambda endpoint, *args, **kwargs: (
            {"ready": True} if endpoint == "health" else {"answers": {"q": {"choice": "billing"}}})
        self.factory = patch.object(web_portal, "AppLabConnection", return_value=self.connection)
        self.factory.start()
        self.server = web_portal.PortalServer(("127.0.0.1", 0), web_portal.PortalState())
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.factory.stop()

    def post(self, path, value, headers=None):
        request = Request(self.base + path, data=json.dumps(value).encode(),
                          headers={"Content-Type": "application/json", **(headers or {})})
        with urlopen(request) as response:
            return json.load(response)

    def test_connect_predict_disconnect_and_static_page(self):
        with urlopen(self.base) as response:
            self.assertIn(b"Try a decision.", response.read())
        self.assertEqual(self.post("/api/connect", {"serial": "test-board"})["serial"], "test-board")
        request = {"state": "refund", "questions": {"q": {"type": "choice"}}}
        response = self.post("/api/predict", request)
        self.assertEqual(response["result"]["answers"]["q"]["choice"], "billing")
        self.connection.request.assert_called_with("predict", request)
        self.post("/api/disconnect", {})
        self.connection.close.assert_called_once()

    def test_cross_origin_and_invalid_requests_cannot_access_board(self):
        for headers, value, code in (({"Origin": "https://foreign.example"}, {"serial": "test-board"}, 403),
                                     ({}, {"serial": ["bad"]}, 400)):
            with self.assertRaises(HTTPError) as failure:
                self.post("/api/connect", value, headers)
            self.assertEqual(failure.exception.code, code)
            failure.exception.close()
        self.connection.request.assert_not_called()
        with self.assertRaises(HTTPError) as failure:
            self.post("/api/predict", {"state": "hello", "questions": {}})
        self.assertEqual(failure.exception.code, 400)
        failure.exception.close()

    def test_failed_health_check_closes_usb_forward(self):
        self.connection.request.side_effect = web_portal.ToolError("App unavailable")
        with self.assertRaises(HTTPError) as failure:
            self.post("/api/connect", {"serial": "test-board"})
        self.assertEqual(failure.exception.code, 400)
        failure.exception.close()
        self.connection.close.assert_called_once()
        self.assertIsNone(self.server.state.connection)
