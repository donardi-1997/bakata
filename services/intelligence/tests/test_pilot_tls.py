"""Run on CI host with OpenSSL; no external requests, no test key committed."""
import http.server
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch

from intelligence.transport import https_get


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body=b"[]"
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self,*args):
        pass


class PilotTLSTests(unittest.TestCase):
    def test_real_tls_hostname_and_pinned_socket(self):
        if not shutil.which("openssl"):
            if os.environ.get("BAKATA_REQUIRE_TLS_TEST")=="1":
                self.fail("OpenSSL executable required")
            self.skipTest("OpenSSL CLI absent in slim offline container; CI host runs this test")
        with TemporaryDirectory() as temp:
            cert,key=Path(temp)/"cert.pem",Path(temp)/"key.pem"
            subprocess.run(["openssl","req","-x509","-newkey","rsa:2048","-nodes","-days","1",
                            "-subj","/CN=pilot.example.com","-addext","subjectAltName=DNS:pilot.example.com",
                            "-keyout",str(key),"-out",str(cert)],check=True,capture_output=True,timeout=15)
            server=http.server.HTTPServer(("127.0.0.1",0),Handler)
            server_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_context.load_cert_chain(cert,key)
            server.socket=server_context.wrap_socket(server.socket,server_side=True)
            thread=Thread(target=server.serve_forever,daemon=True)
            thread.start()
            create=socket.create_connection
            context=ssl.create_default_context(cafile=str(cert))
            calls=[]
            def local_socket(address,timeout=None):
                calls.append(address)
                return create(("127.0.0.1",server.server_port),timeout=timeout)
            try:
                with patch("intelligence.transport.public_ip",return_value="8.8.8.8"), \
                     patch("intelligence.transport.socket.create_connection",side_effect=local_socket), \
                     patch("intelligence.transport.ssl.create_default_context",return_value=context):
                    response=https_get("https://pilot.example.com/products","pilot.example.com",3,1024,
                                       accept="application/json",expected_ip="8.8.8.8")
                    self.assertEqual(response.body,b"[]")
                    with self.assertRaises(ssl.SSLCertVerificationError):
                        https_get("https://wrong.example.com/products","wrong.example.com",3,1024,
                                  accept="application/json",expected_ip="8.8.8.8")
                self.assertEqual(calls,[("8.8.8.8",443),("8.8.8.8",443)])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
