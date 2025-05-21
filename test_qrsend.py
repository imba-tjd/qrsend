import unittest
import qrsend # The module to test
import tempfile
import os
import threading
import requests # For making HTTP requests
import time
import urllib.parse # For URL encoding filenames
from http.server import HTTPStatus # For status codes


class TestQRSend(unittest.TestCase):
    SERVER_PORT = 8091 # Using a potentially less common port for testing
    SERVER_IP = "127.0.0.1"
    SERVER_URL_BASE = f"http://{SERVER_IP}:{SERVER_PORT}"
    
    DEFAULT_FILE_CONTENT = b"This is a test file for qrsend."
    LARGE_FILE_CONTENT = b"0123456789abcdefghijklmnopqrstuvwxyz" * 1000 # 36k content
    DEFAULT_TEST_FILE_NAME = "test_file.txt"
    LARGE_TEST_FILE_NAME = "large_test_file.bin"

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="qrsend_test_")
        
        self.default_temp_file_path = os.path.join(self.temp_dir, self.DEFAULT_TEST_FILE_NAME)
        with open(self.default_temp_file_path, 'wb') as f:
            f.write(self.DEFAULT_FILE_CONTENT)

        self.large_temp_file_path = os.path.join(self.temp_dir, self.LARGE_TEST_FILE_NAME)
        with open(self.large_temp_file_path, 'wb') as f:
            f.write(self.LARGE_FILE_CONTENT)

        self.server_thread = None
        self.httpd_instance = None # To store httpd for shutdown
        self._original_http_server = qrsend.ThreadingHTTPServer # Store original for restoration

        # Suppress terminal output from qrsend unless debugging tests
        self._original_print = qrsend.print
        qrsend.print = lambda *args, **kwargs: None
        self._original_qr_print = qrsend.print_qr_code
        qrsend.print_qr_code = lambda *args, **kwargs: None
        self._original_cursor = qrsend.cursor
        qrsend.cursor = lambda *args, **kwargs: None


    def tearDown(self):
        qrsend.print = self._original_print # Restore print
        qrsend.print_qr_code = self._original_qr_print # Restore qr_print
        qrsend.cursor = self._original_cursor # Restore cursor


        if self.httpd_instance:
            try:
                self.httpd_instance.shutdown()
                self.httpd_instance.server_close()
            except Exception as e:
                # self._original_print(f"Error shutting down httpd: {e}") # Use original print for test debugging
                pass # Ignore errors during shutdown, as server might be down
        
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2.0)
            if self.server_thread.is_alive():
                # self._original_print("Warning: Server thread did not terminate.") # Use original print
                pass

        qrsend.ThreadingHTTPServer = self._original_http_server # Restore original server class

        # Clean up temporary files and directory
        if os.path.exists(self.default_temp_file_path):
            os.remove(self.default_temp_file_path)
        if os.path.exists(self.large_temp_file_path):
            os.remove(self.large_temp_file_path)
        if os.path.isdir(self.temp_dir):
            os.rmdir(self.temp_dir)

    def _mock_http_server_creator(self, *args, **kwargs):
        """Captures the httpd instance for later shutdown."""
        # args[0] is server_address, args[1] is RequestHandlerClass
        # We need to pass these to the original ThreadingHTTPServer
        self.httpd_instance = self._original_http_server(*args, **kwargs)
        return self.httpd_instance

    def _start_server(self, file_path_to_serve, port, no_force_download=False, debug=False, ip_addr=SERVER_IP):
        # Monkeypatch ThreadingHTTPServer to capture the instance
        qrsend.ThreadingHTTPServer = self._mock_http_server_creator

        quoted_file_name = urllib.parse.quote(os.path.basename(file_path_to_serve))
        
        # Target for the server thread
        self.server_thread = threading.Thread(
            target=qrsend.start_download_server,
            args=(file_path_to_serve,),
            kwargs={
                'custom_port': str(port),
                'ip_addr': ip_addr,
                'no_force_download': no_force_download,
                'debug': debug  # Set to True if debugging server-side issues
            },
            daemon=True # Daemon threads are abruptly stopped at shutdown if not joined
        )
        self.server_thread.start()
        
        # Wait for server to be ready, polls for httpd_instance
        # Increased timeout for slower systems/CI
        start_time = time.monotonic()
        while not self.httpd_instance and (time.monotonic() - start_time) < 5.0: # 5 sec timeout
            time.sleep(0.05) # Short sleep to yield execution

        if not self.httpd_instance:
            # Restore original server class even if server failed to start
            qrsend.ThreadingHTTPServer = self._original_http_server
            # Restore print for this error message
            qrsend.print = self._original_print
            qrsend.print("Error: HTTP server instance was not captured in time.")
            qrsend.print = lambda *args, **kwargs: None # Suppress again
            raise ConnectionError("Server did not start or instance not captured.")
        
        # httpd_instance is now captured, original server class can be restored for other threads/tests.
        # However, it's safer to restore it in tearDown or after the thread completes.
        # For now, we assume one server per test instance.

        return f"{self.SERVER_URL_BASE}/{quoted_file_name}"

    # --- Test Cases ---

    def test_full_download_force_on(self):
        file_url = self._start_server(self.default_temp_file_path, self.SERVER_PORT)
        response = requests.get(file_url, timeout=5)
        
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response.headers['Content-Type'], 'application/octet-stream')
        self.assertEqual(int(response.headers['Content-Length']), len(self.DEFAULT_FILE_CONTENT))
        self.assertEqual(response.content, self.DEFAULT_FILE_CONTENT)
        self.assertEqual(response.headers.get('Accept-Ranges'), 'bytes')

    def test_full_download_force_off_txt(self):
        file_url = self._start_server(self.default_temp_file_path, self.SERVER_PORT, no_force_download=True)
        response = requests.get(file_url, timeout=5)

        self.assertEqual(response.status_code, HTTPStatus.OK)
        # The guessed type can vary. For .txt, it's usually text/plain.
        # SimpleHTTPRequestHandler.guess_type might return application/octet-stream if a more specific type isn't found
        # or if the OS mimetypes database is minimal. Forcing to text/plain for this test.
        self.assertTrue(response.headers['Content-Type'].startswith('text/plain')) # More robust check
        self.assertEqual(int(response.headers['Content-Length']), len(self.DEFAULT_FILE_CONTENT))
        self.assertEqual(response.content, self.DEFAULT_FILE_CONTENT)

    def test_range_request_valid_start_end(self):
        file_url = self._start_server(self.large_temp_file_path, self.SERVER_PORT)
        headers = {'Range': 'bytes=10-29'} # Request 20 bytes (10 to 29 inclusive)
        expected_content = self.LARGE_FILE_CONTENT[10:30]
        
        response = requests.get(file_url, headers=headers, timeout=5)
        
        self.assertEqual(response.status_code, HTTPStatus.PARTIAL_CONTENT)
        self.assertEqual(int(response.headers['Content-Length']), 20)
        self.assertEqual(response.headers['Content-Range'], f'bytes 10-29/{len(self.LARGE_FILE_CONTENT)}')
        self.assertEqual(response.content, expected_content)

    def test_range_request_valid_start_only(self):
        file_url = self._start_server(self.large_temp_file_path, self.SERVER_PORT)
        start_byte = 50
        headers = {'Range': f'bytes={start_byte}-'}
        expected_content = self.LARGE_FILE_CONTENT[start_byte:]
        
        response = requests.get(file_url, headers=headers, timeout=5)
        
        self.assertEqual(response.status_code, HTTPStatus.PARTIAL_CONTENT)
        self.assertEqual(int(response.headers['Content-Length']), len(self.LARGE_FILE_CONTENT) - start_byte)
        self.assertEqual(response.headers['Content-Range'], f'bytes {start_byte}-{len(self.LARGE_FILE_CONTENT)-1}/{len(self.LARGE_FILE_CONTENT)}')
        self.assertEqual(response.content, expected_content)

    def test_range_request_exceeding_file_size_capped(self):
        file_url = self._start_server(self.large_temp_file_path, self.SERVER_PORT)
        file_size = len(self.LARGE_FILE_CONTENT)
        headers = {'Range': f'bytes=0-{file_size + 100}'} # Request range larger than file
        
        response = requests.get(file_url, headers=headers, timeout=5)
        
        self.assertEqual(response.status_code, HTTPStatus.PARTIAL_CONTENT)
        self.assertEqual(int(response.headers['Content-Length']), file_size) # Should serve whole file
        self.assertEqual(response.headers['Content-Range'], f'bytes 0-{file_size-1}/{file_size}')
        self.assertEqual(response.content, self.LARGE_FILE_CONTENT)

    def test_range_request_start_at_end_exceeding_capped(self):
        file_url = self._start_server(self.large_temp_file_path, self.SERVER_PORT)
        file_size = len(self.LARGE_FILE_CONTENT)
        # Request range starting at last byte, but asking for more
        headers = {'Range': f'bytes={file_size-1}-{file_size + 100}'} 
        
        response = requests.get(file_url, headers=headers, timeout=5)
        
        self.assertEqual(response.status_code, HTTPStatus.PARTIAL_CONTENT)
        self.assertEqual(int(response.headers['Content-Length']), 1) # Should serve only the last byte
        self.assertEqual(response.headers['Content-Range'], f'bytes {file_size-1}-{file_size-1}/{file_size}')
        self.assertEqual(response.content, self.LARGE_FILE_CONTENT[file_size-1:])

    def test_error_accessing_disallowed_path(self):
        # Serve default_temp_file_path (whose basename is DEFAULT_TEST_FILE_NAME)
        self._start_server(self.default_temp_file_path, self.SERVER_PORT)
        
        # Try to access a different file name
        disallowed_url = f"{self.SERVER_URL_BASE}/other_file.txt"
        response = requests.get(disallowed_url, timeout=5)
        self.assertEqual(response.status_code, HTTPStatus.FORBIDDEN)

    def test_error_range_syntactically_incorrect(self):
        file_url = self._start_server(self.default_temp_file_path, self.SERVER_PORT)
        headers = {'Range': 'bytes=abc-def'} # Syntactically incorrect
        response = requests.get(file_url, headers=headers, timeout=5)
        # The server should reject this as a bad range format
        self.assertEqual(response.status_code, HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)

    def test_error_range_start_greater_than_end(self):
        file_url = self._start_server(self.default_temp_file_path, self.SERVER_PORT)
        headers = {'Range': 'bytes=100-50'} # Start > end
        response = requests.get(file_url, headers=headers, timeout=5)
        self.assertEqual(response.status_code, HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
        self.assertEqual(response.headers.get('Content-Range'), f'bytes */{len(self.DEFAULT_FILE_CONTENT)}')

    def test_error_range_start_beyond_eof(self):
        file_url = self._start_server(self.default_temp_file_path, self.SERVER_PORT)
        file_size = len(self.DEFAULT_FILE_CONTENT)
        headers = {'Range': f'bytes={file_size}-'} # Start at EOF
        
        response = requests.get(file_url, headers=headers, timeout=5)
        self.assertEqual(response.status_code, HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
        self.assertEqual(response.headers.get('Content-Range'), f'bytes */{file_size}')


if __name__ == '__main__':
    # Add requests to your project's test dependencies, e.g., in requirements_dev.txt
    # Example: pip install requests
    print("Reminder: Ensure 'requests' library is installed for running these tests.")
    unittest.main()
