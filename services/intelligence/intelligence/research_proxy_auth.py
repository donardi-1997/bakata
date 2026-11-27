"""Mutual TLS transport; a trusted CA alone is insufficient."""
import hashlib
import hmac
import re
import ssl

from .research_proxy import close


def server_context(*, cert, key, ca):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_cert_chain(certfile=cert, keyfile=key)
    ctx.load_verify_locations(cafile=ca)
    return ctx


def authenticated_handler(proxy, pin):
    if not isinstance(pin, str) or not re.fullmatch(r"[0-9a-f]{64}", pin):
        raise ValueError("Pinned fixture client certificate required")

    async def handle(reader, writer):
        try:
            transport = writer.get_extra_info("ssl_object")
            peer = transport.getpeercert(binary_form=True) if transport else None
            if not peer or not hmac.compare_digest(hashlib.sha256(peer).hexdigest(), pin):
                await close(writer)
                return
        except Exception:
            await close(writer)
            return
        await proxy.handle(reader, writer)

    return handle
