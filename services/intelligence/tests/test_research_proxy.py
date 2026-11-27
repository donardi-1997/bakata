import asyncio
import time
import unittest
from unittest.mock import AsyncMock

from intelligence.research_proxy import PilotProxy,parse_connect,HEADER_LIMIT,MAX_ATTEMPTS

GOOD=b"CONNECT api.dropi.co:443 HTTP/1.1\r\nHost: api.dropi.co:443\r\n\r\n"


class ParserTests(unittest.TestCase):
    def test_exact_authority(self):
        parse_connect(GOOD)
        for raw in [GOOD.replace(b"CONNECT",b"GET"),GOOD.replace(b":443",b":80"),
                    GOOD.replace(b"Host:",b"X-Host:"),GOOD.replace(b"Host:",b"Host: other\r\nHost:"),
                    GOOD[:-2]+b"Content-Length: 1\r\n\r\n",
                    GOOD[:-2]+b"Proxy-Authorization: x\r\n\r\n",
                    GOOD.replace(b"Host: ",b"Host: \t"),GOOD+b"body",b"x"*HEADER_LIMIT]:
            with self.assertRaises(ValueError):
                parse_connect(raw)


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async def echo(reader,writer):
            try:
                data=await reader.read(1024)
                writer.write(data)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        self.remote=await asyncio.start_server(echo,"127.0.0.1",0)
        port=self.remote.sockets[0].getsockname()[1]
        async def local_dial(ip):
            self.assertEqual(ip,"8.8.8.8")
            return await asyncio.open_connection("127.0.0.1",port)
        self.resolve=AsyncMock(return_value=["8.8.8.8"])
        self.dial=AsyncMock(side_effect=local_dial)
        self.proxy=PilotProxy(until=int(time.time())+120,resolve=self.resolve,dial=self.dial)
        self.server=await asyncio.start_server(self.proxy.handle,"127.0.0.1",0,limit=HEADER_LIMIT)
        self.port=self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        for server in (self.server,self.remote):
            server.close()
            await server.wait_closed()
        await asyncio.sleep(.05)

    async def connect(self,raw=GOOD):
        reader,writer=await asyncio.open_connection("127.0.0.1",self.port)
        writer.write(raw)
        await writer.drain()
        return reader,writer

    async def finish(self,writer):
        writer.close()
        await writer.wait_closed()
        for _ in range(100):
            if not self.proxy.active:
                return
            await asyncio.sleep(.01)

    async def test_loopback_relay_and_budget(self):
        for _ in range(MAX_ATTEMPTS):
            r,w=await self.connect()
            self.assertIn(b"200",await asyncio.wait_for(r.readuntil(b"\r\n\r\n"),2))
            w.write(b"opaque synthetic TLS bytes")
            await w.drain()
            self.assertEqual(await asyncio.wait_for(r.readexactly(26),2),b"opaque synthetic TLS bytes")
            await self.finish(w)
        r,w=await self.connect()
        self.assertEqual(await asyncio.wait_for(r.readuntil(b"\r\n\r\n"),2),
                         b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        await self.finish(w)
        self.assertEqual(self.dial.await_count,MAX_ATTEMPTS)

    async def test_mixed_dns_denied_and_consumed(self):
        self.resolve.return_value=["8.8.8.8","127.0.0.1"]
        r,w=await self.connect()
        self.assertEqual(await asyncio.wait_for(r.read(),2),b"")
        await self.finish(w)
        self.assertEqual(self.proxy.attempts,1)
        self.dial.assert_not_awaited()

    async def test_bad_target_never_resolves(self):
        r,w=await self.connect(GOOD.replace(b"api.dropi.co",b"example.invalid"))
        self.assertEqual(await asyncio.wait_for(r.read(),2),b"")
        await self.finish(w)
        self.resolve.assert_not_awaited()

    async def test_parallel_tunnel_denied(self):
        r,w=await self.connect()
        await asyncio.wait_for(r.readuntil(b"\r\n\r\n"),2)
        other,other_w=await self.connect()
        self.assertEqual(await asyncio.wait_for(other.readuntil(b"\r\n\r\n"),2),
                         b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        other_w.close()
        await other_w.wait_closed()
        await self.finish(w)
        self.assertEqual(self.dial.await_count,1)

    async def test_rejected_header_cannot_become_authorized(self):
        r,w=await self.connect()
        await asyncio.wait_for(r.readuntil(b"\r\n\r\n"),2)
        denied,denied_w=await asyncio.open_connection("127.0.0.1",self.port)
        try:
            for _ in range(100):
                if self.proxy.rejecting:
                    break
                await asyncio.sleep(.005)
            self.assertTrue(self.proxy.rejecting)
            await self.finish(w)
            self.assertFalse(self.proxy.active)
            denied_w.write(GOOD)
            await denied_w.drain()
            self.assertIn(b"503 Service Unavailable",await asyncio.wait_for(denied.readuntil(b"\r\n\r\n"),2))
            self.assertEqual(self.dial.await_count,1)
            self.assertEqual(self.proxy.attempts,1)
        finally:
            denied_w.close()
            await denied_w.wait_closed()
            await self.finish(w)

    async def test_failed_dial_no_retry(self):
        self.dial.side_effect=OSError("synthetic failure")
        r,w=await self.connect()
        self.assertEqual(await asyncio.wait_for(r.read(),2),b"")
        await self.finish(w)
        self.assertEqual(self.dial.await_count,1)
        self.assertEqual(self.proxy.attempts,1)


if __name__=="__main__":
    unittest.main()
