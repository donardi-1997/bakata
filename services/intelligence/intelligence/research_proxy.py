"""Bounded CONNECT relay for the isolated research pilot.

Not deployed or connected to WordPress. No TLS termination, credentials or
provider HTTP implementation. Run only behind a dedicated private SG.
"""
import asyncio
import ipaddress
import os
import socket
import time

from .research_egress import AUTHORITY, HOST, approved_destination

HEADER_LIMIT=2048
CONNECT_TIMEOUT=5
TUNNEL_TIMEOUT=25
IDLE_TIMEOUT=8
MAX_BYTES=2*1024*1024
MAX_ATTEMPTS=3


def parse_connect(raw):
    if not isinstance(raw,bytes) or len(raw)>HEADER_LIMIT or not raw.endswith(b"\r\n\r\n"):
        raise ValueError("Invalid CONNECT request")
    lines=raw[:-4].split(b"\r\n")
    if not lines or lines[0] not in (b"CONNECT api.dropi.co:443 HTTP/1.1",b"CONNECT api.dropi.co:443 HTTP/1.0"):
        raise ValueError("Denied CONNECT target")
    seen=set()
    for line in lines[1:]:
        name,sep,value=line.partition(b":")
        name=name.lower()
        if not sep or name in seen or name not in (b"host",b"proxy-connection",b"connection",b"user-agent"):
            raise ValueError("Denied CONNECT header")
        seen.add(name)
        value=value.strip(b" ")
        if not value or any(c<32 or c>126 for c in value):
            raise ValueError("Invalid CONNECT header")
        if name==b"host" and value!=AUTHORITY.encode():
            raise ValueError("Mismatched CONNECT host")
        if name in (b"connection",b"proxy-connection") and value.lower() not in (b"close",b"keep-alive"):
            raise ValueError("Denied connection option")
    if lines[0].endswith(b"1.1") and b"host" not in seen:
        raise ValueError("Missing Host header")


async def resolve_provider():
    loop=asyncio.get_running_loop()
    # Resolve once, inspect every returned address, then dial numeric IPv4 only.
    answers=await loop.getaddrinfo(HOST,443,family=socket.AF_INET,type=socket.SOCK_STREAM,proto=socket.IPPROTO_TCP)
    return list(dict.fromkeys(x[4][0] for x in answers))


async def dial_numeric(address):
    return await asyncio.open_connection(address,443,family=socket.AF_INET,flags=socket.AI_NUMERICHOST,limit=65536)


async def close(writer):
    if writer is None:
        return
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(),1)
    except (Exception,asyncio.CancelledError):
        transport=writer.transport
        if transport is not None:
            transport.abort()


class PilotProxy:
    def __init__(self,*,until,resolve=resolve_provider,dial=dial_numeric,clock=time.time):
        if type(until) is not int or not clock()<until<=clock()+1800:
            raise ValueError("Explicit current pilot expiry required")
        self.until=until
        self.resolve=resolve
        self.dial=dial
        self.clock=clock
        self.active=False
        self.attempts=0

    async def handle(self,reader,writer):
        upstream=None
        tasks=[]
        acquired=False
        try:
            # No waiting queue or concurrent tunnels. The counter is per process,
            # not a replacement for durable per-page reservations.
            if self.active or self.attempts>=MAX_ATTEMPTS or self.clock()>=self.until:
                writer.write(b"HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n\r\n")
                await asyncio.wait_for(writer.drain(),1)
                return
            self.active=True
            acquired=True
            raw=await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"),CONNECT_TIMEOUT)
            parse_connect(raw)
            if self.clock()>=self.until:
                raise ValueError("Pilot expired")
            self.attempts+=1
            addresses=await asyncio.wait_for(self.resolve(),CONNECT_TIMEOUT)
            ip=approved_destination("CONNECT",AUTHORITY,addresses)[0]
            if self.clock()>=self.until:
                raise ValueError("Pilot expired")
            # Exactly one dial; failure consumes the attempt.
            remote,upstream=await asyncio.wait_for(self.dial(ip),CONNECT_TIMEOUT)
            if self.clock()>=self.until:
                raise ValueError("Pilot expired")
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await asyncio.wait_for(writer.drain(),1)
            total=0

            async def pump(source,target):
                nonlocal total
                while True:
                    data=await asyncio.wait_for(source.read(16384),IDLE_TIMEOUT)
                    if not data:
                        if target.can_write_eof():
                            target.write_eof()
                            await asyncio.wait_for(target.drain(),IDLE_TIMEOUT)
                        return
                    total+=len(data)
                    if total>MAX_BYTES:
                        raise ValueError("Tunnel byte budget exceeded")
                    target.write(data)
                    await asyncio.wait_for(target.drain(),IDLE_TIMEOUT)

            tasks=[asyncio.create_task(pump(reader,upstream)),asyncio.create_task(pump(remote,writer))]
            await asyncio.wait_for(asyncio.gather(*tasks),min(TUNNEL_TIMEOUT,max(0,self.until-self.clock())))
        except (Exception,asyncio.CancelledError):
            # Never log request headers, payloads, exceptions or provider data.
            pass
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks,return_exceptions=True)
            await close(upstream)
            await close(writer)
            if acquired:
                self.active=False


async def main():
    if os.environ.get("BAKATA_RESEARCH_PROXY_ENABLED")!="1":
        raise ValueError("Proxy disabled")
    # Deployment must explicitly provide a private bind address and SG.
    host=os.environ["BAKATA_RESEARCH_PROXY_BIND"]
    ip=ipaddress.ip_address(host)
    if ip.version!=4 or not any(ip in ipaddress.ip_network(net) for net in ("10.0.0.0/8","172.16.0.0/12","192.168.0.0/16")):
        raise ValueError("Private IPv4 bind required")
    proxy=PilotProxy(until=int(os.environ["BAKATA_RESEARCH_UNTIL"]))
    server=await asyncio.start_server(proxy.handle,host,8443,limit=HEADER_LIMIT,backlog=2)
    async with server:
        await asyncio.sleep(max(0,proxy.until-time.time()))


if __name__=="__main__":
    try:
        asyncio.run(main())
    except Exception:
        raise SystemExit("Research proxy disabled or blocked") from None
