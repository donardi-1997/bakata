"""Pure policy for the future dedicated CONNECT proxy; no listener or network I/O.

The runtime must connect to the returned numeric address without resolving again.
The WordPress TLS client must separately verify the original hostname.
"""
import ipaddress

HOST="api.dropi.co"
AUTHORITY=HOST+":443"


def approved_destination(method,authority,addresses):
    if method!="CONNECT" or authority!=AUTHORITY:
        raise ValueError("Proxy destination denied")
    if not isinstance(addresses,(tuple,list)) or not 1<=len(addresses)<=16:
        raise ValueError("Invalid DNS answer")
    parsed=[]
    for value in addresses:
        if not isinstance(value,str):
            raise ValueError("Invalid DNS answer")
        ip=ipaddress.ip_address(value)
        # IPv4 only for the first pilot; fail closed on mixed/private answers.
        if ip.version!=4 or not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local or ip.is_unspecified:
            raise ValueError("Non-public provider DNS answer")
        parsed.append(str(ip))
    return tuple(dict.fromkeys(parsed))
