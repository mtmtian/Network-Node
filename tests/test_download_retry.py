#!/usr/bin/env python3
import http.server
import os
import pathlib
import subprocess
import tempfile
import threading
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
DOWNLOAD_LIB = PROJECT_ROOT / "core" / "download.sh"


class FlakyDownloadHandler(http.server.BaseHTTPRequestHandler):
    attempts = 0

    def do_GET(self):
        type(self).attempts += 1
        if type(self).attempts < 3:
            self.send_response(503)
            self.end_headers()
            return
        body = b"download-ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


class DownloadRetryTest(unittest.TestCase):
    def test_retries_transient_http_failures(self):
        FlakyDownloadHandler.attempts = 0
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FlakyDownloadHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                destination = pathlib.Path(tmp) / "asset"
                url = f"http://127.0.0.1:{server.server_port}/asset"
                command = f'. "{DOWNLOAD_LIB}"; download_file "{destination}" "{url}"'
                result = subprocess.run(
                    ["bash", "-c", command],
                    text=True,
                    capture_output=True,
                    env=os.environ.copy(),
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(destination.read_bytes(), b"download-ok")
                self.assertEqual(FlakyDownloadHandler.attempts, 3)
        finally:
            server.shutdown()
            server.server_close()

    def test_print_first_line_does_not_sigpipe_multiline_command(self):
        command = (
            f'. "{DOWNLOAD_LIB}"; '
            "print_first_line bash -c 'printf \"first\\nsecond\\nthird\\n\"'"
        )
        result = subprocess.run(
            ["bash", "-o", "pipefail", "-c", command],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "first\n")


if __name__ == "__main__":
    unittest.main()
