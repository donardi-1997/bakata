"""Loopback TLS with ephemeral certs. X509 strict is enabled on the client only."""
import asyncio
import hashlib
import hmac
from pathlib import Path
import ssl
import subprocess
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

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
                "-out","ca.pem","-subj","/CN=fixture CA","-days","1",
                "-addext","keyUsage=critical,keyCertSign,cRLSign")
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
        self.server_ctx=ctx
        self.assertEqual(ctx.verify_mode,ssl.CERT_REQUIRED)
        self.handled=asyncio.Event()
        self.peer_pin=None
        handler=authenticated_handler(self.proxy,self.pin)
        async def observed(reader,writer):
            peer=writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
            self.peer_pin=hashlib.sha256(peer).hexdigest()
            self.handled.set()
            await handler(reader,writer)
        self.server=await asyncio.start_server(observed,"127.0.0.1",0,
                                                ssl=ctx,ssl_handshake_timeout=2)
        self.port=self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        await asyncio.sleep(.05)

    def client_context(self,name=None,*,tls12=False):
        ctx=ssl.create_default_context(cafile=str(self.path/"ca.pem"))
        ctx.verify_flags |= ssl.VERIFY_X509_STRICT
        if tls12:
            ctx.maximum_version=ssl.TLSVersion.TLSv1_2
        if name:
            ctx.load_cert_chain(str(self.path/(name+".pem")),str(self.path/(name+".key")))
        return ctx

    async def request(self,name,hostname="proxy.fixture.invalid"):
        ctx=self.client_context(name)
        writer=None
        stage="handshake"
        try:
            reader,writer=await asyncio.open_connection("127.0.0.1",self.port,ssl=ctx,server_hostname=hostname)
            stage="request"
            writer.write(GOOD)
            await writer.drain()
            await asyncio.wait_for(reader.read(),3)
        except (OSError,ssl.SSLError,ConnectionError) as exc:
            code=getattr(exc,"verify_code",None)
            raise self.failureException(
                f"Positive TLS {stage} failed: {type(exc).__name__}, verify_code={code}"
            ) from None
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except (OSError,ssl.SSLError,ConnectionError):
                    pass

    def assert_no_proxy_activity(self):
        self.resolve.assert_not_awaited()
        self.dial.assert_not_awaited()
        self.assertEqual(self.proxy.attempts,0)

    async def test_wrong_hostname_is_certificate_verification_failure(self):
        with self.assertRaises(ssl.SSLCertVerificationError) as error:
            await asyncio.open_connection("127.0.0.1",self.port,
                ssl=self.client_context("worker"),server_hostname="wrong.fixture.invalid")
        self.assertEqual(error.exception.verify_code,62)  # OpenSSL hostname mismatch
        self.assert_no_proxy_activity()

    async def test_missing_client_certificate_fails_tls(self):
        # Memory BIOs expose the server error reliably even when asyncio resets
        # the client connection without surfacing the TLS alert.
        ci,co,si,so=(ssl.MemoryBIO() for _ in range(4))
        client=self.client_context(tls12=True).wrap_bio(ci,co,server_hostname="proxy.fixture.invalid")
        server=self.server_ctx.wrap_bio(si,so,server_side=True)
        reason=None
        for _ in range(20):
            try:
                client.do_handshake()
            except ssl.SSLWantReadError:
                pass
            except ssl.SSLError:
                break
            si.write(co.read())
            try:
                server.do_handshake()
            except ssl.SSLWantReadError:
                pass
            except ssl.SSLError as exc:
                reason=exc.reason
                break
            ci.write(so.read())
        self.assertEqual(reason,"PEER_DID_NOT_RETURN_A_CERTIFICATE")
        # TLS 1.2 makes rejection occur before open_connection returns.
        with self.assertRaises((ConnectionResetError,ssl.SSLError)):
            await asyncio.open_connection("127.0.0.1",self.port,
                ssl=self.client_context(tls12=True),server_hostname="proxy.fixture.invalid")
        self.assertFalse(self.handled.is_set())
        self.assert_no_proxy_activity()

    async def test_valid_but_unpinned_client_reaches_auth_not_proxy(self):
        compare_digest=hmac.compare_digest
        results=[]
        def observe_comparison(actual,authorized):
            result=compare_digest(actual,authorized)
            results.append(result)
            return result
        with patch("intelligence.research_proxy_auth.hmac.compare_digest",
                   side_effect=observe_comparison) as comparison:
            reader,writer=await asyncio.open_connection("127.0.0.1",self.port,
                ssl=self.client_context("other"),server_hostname="proxy.fixture.invalid")
            try:
                await asyncio.wait_for(self.handled.wait(),3)
                other=ssl.PEM_cert_to_DER_cert((self.path/"other.pem").read_text())
                other_pin=hashlib.sha256(other).hexdigest()
                self.assertEqual(self.peer_pin,other_pin)
                self.assertNotEqual(self.peer_pin,self.pin)
                self.assertEqual(await asyncio.wait_for(reader.read(),3),b"")
                comparison.assert_called_once_with(other_pin,self.pin)
                self.assertEqual(results,[False])
                self.assert_no_proxy_activity()
            finally:
                writer.close()
                await writer.wait_closed()

    async def test_pinned_client_reaches_proxy(self):
        compare_digest=hmac.compare_digest
        results=[]
        def observe_comparison(actual,authorized):
            result=compare_digest(actual,authorized)
            results.append(result)
            return result
        with patch("intelligence.research_proxy_auth.hmac.compare_digest",
                   side_effect=observe_comparison) as comparison:
            await self.request("worker")
        comparison.assert_called_once_with(self.pin,self.pin)
        self.assertEqual(results,[True])
        self.assertTrue(self.handled.is_set())
        self.resolve.assert_awaited_once()
        self.dial.assert_awaited_once()
        self.assertEqual(self.proxy.attempts,1)

    async def test_invalid_pin_rejected(self):
        for pin in ("","x"*64,"a"*63,None):
            with self.assertRaises(ValueError):
                authenticated_handler(self.proxy,pin)

if __name__=="__main__":
    unittest.main()
