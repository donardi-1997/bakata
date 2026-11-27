"""Real loopback TLS handshakes; ephemeral test certs, no provider."""
import asyncio
import hashlib
from pathlib import Path
import ssl
import subprocess
import tempfile
import time
import unittest
from unittest.mock import AsyncMock

from intelligence.research_proxy import PilotProxy
from intelligence.research_proxy_auth import authenticated_handler, server_context

GOOD = b"CONNECT api.dropi.co:443 HTTP/1.1\r\nHost: api.dropi.co:443\r\n\r\n"

class AuthTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.tmp.name)
        def openssl(*args):
            subprocess.run(["openssl", *args], cwd=cls.path, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        openssl("req","-x509","-newkey","rsa:2048","-nodes","-keyout","ca.key",
                "-out","ca.pem","-subj","/CN=fixture CA","-days","1")
        for name in ("server","worker","other"):
            openssl("req","-newkey","rsa:2048","-nodes","-keyout",name+".key",
                    "-out",name+".csr","-subj","/CN="+name)
            ext=cls.path/(name+".ext")
            ext.write_text("subjectAltName=DNS:proxy.fixture.invalid\nextendedKeyUsage=serverAuth\n"
                           if name=="server" else "extendedKeyUsage=clientAuth\n")
            openssl("x509","-req","-in",name+".csr","-CA","ca.pem","-CAkey","ca.key",
                    "-CAcreateserial","-out",name+".pem","-days","1","-extfile",name+".ext")
        cls.pin=hashlib.sha256(ssl.PEM_cert_to_DER_cert((cls.path/"worker.pem").read_text())).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    async def asyncSetUp(self):
        self.resolve=AsyncMock(return_value=["8.8.8.8"])
        self.dial=AsyncMock(side_effect=OSError("synthetic dial"))
        self.proxy=PilotProxy(until=int(time.time())+120,resolve=self.resolve,dial=self.dial)
        ctx=server_context(cert=str(self.path/"server.pem"),key=str(self.path/"server.key"),
                           ca=str(self.path/"ca.pem"))
        self.server=await asyncio.start_server(authenticated_handler(self.proxy,self.pin),"127.0.0.1",0,
                                                ssl=ctx,ssl_handshake_timeout=2)
        self.port=self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        await asyncio.sleep(.05)

    async def request(self,name=None,hostname="proxy.fixture.invalid"):
        ctx=ssl.create_default_context(cafile=str(self.path/"ca.pem"))
        if name:
            ctx.load_cert_chain(str(self.path/(name+".pem")),str(self.path/(name+".key")))
        writer=None
        try:
            reader,writer=await asyncio.open_connection("127.0.0.1",self.port,ssl=ctx,server_hostname=hostname)
            writer.write(GOOD)
            await writer.drain()
            await asyncio.wait_for(reader.read(),3)
        except (OSError,ssl.SSLError,ConnectionError):
            pass
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except (OSError,ssl.SSLError,ConnectionError):
                    pass

    async def test_only_pinned_client_reaches_proxy(self):
        await self.request("other")
        await self.request()
        await self.request("worker","wrong.fixture.invalid")
        self.resolve.assert_not_awaited()
        self.dial.assert_not_awaited()
        self.assertEqual(self.proxy.attempts,0)
        await self.request("worker")
        self.resolve.assert_awaited_once()
        self.dial.assert_awaited_once()
        self.assertEqual(self.proxy.attempts,1)

    async def test_invalid_pin_rejected(self):
        for pin in ("","x"*64,"a"*63,None):
            with self.assertRaises(ValueError):
                authenticated_handler(self.proxy,pin)

if __name__=="__main__":
    unittest.main()
