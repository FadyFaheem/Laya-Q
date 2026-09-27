import io
import json
import unittest
from unittest.mock import patch

import board_worker
import laya_q


class FakeAgent:
    def predict(self, state, questions):
        return {"answers": {"echo": {"choice": state}}, "count": len(questions)}


class FakeStatus:
    def set(self, state):
        pass


class ProtocolTests(unittest.TestCase):
    def test_board_returns_one_response_per_request(self):
        input_lines = io.StringIO(
            '{"state":"hello","questions":{"q":{"type":"choice"}}}\n'
            '{"state":"world","questions":{"q":{"type":"choice"}}}\n'
        )
        output = io.StringIO()
        with patch.object(board_worker.sys, "stdout", output):
            board_worker.run(FakeAgent(), input_lines, FakeStatus())
        replies = [json.loads(line.removeprefix(board_worker.PREFIX))
                   for line in output.getvalue().splitlines()]
        self.assertEqual([r["result"]["answers"]["echo"]["choice"] for r in replies],
                         ["hello", "world"])

    def test_board_reports_bad_request_and_continues(self):
        output = io.StringIO()
        with patch.object(board_worker.sys, "stdout", output):
            board_worker.run(FakeAgent(), io.StringIO('not-json\n{"state":"ok","questions":{"q":{}}}\n'), FakeStatus())
        replies = [json.loads(line.removeprefix(board_worker.PREFIX))
                   for line in output.getvalue().splitlines()]
        self.assertEqual([r["ok"] for r in replies], [False, True])

    def test_example_request_is_valid(self):
        request = next(laya_q.requests_from_file("examples/triage.json", False))
        self.assertIn("department", request["questions"])


if __name__ == "__main__":
    unittest.main()
