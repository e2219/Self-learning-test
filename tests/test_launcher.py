import json

import run


def test_lan_address_ignores_proxy_benchmark_network(monkeypatch):
    monkeypatch.setattr(run.sys, "platform", "linux")
    monkeypatch.setattr(run.subprocess, "check_output", lambda *a, **kw: json.dumps([
        {"ifname": "wlan0", "addr_info": [{"family": "inet", "local": "192.168.1.20"}]},
        {"ifname": "Meta", "addr_info": [{"family": "inet", "local": "198.18.0.0"}]},
        {"ifname": "docker0", "addr_info": [{"family": "inet", "local": "172.17.0.1"}]},
    ]))
    monkeypatch.setattr(run.socket, "getaddrinfo", lambda *a: [(None, None, None, None, ("198.18.0.0", 0))])

    class ProxyRoute:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def connect(self, address): pass
        def getsockname(self): return ("198.18.0.0", 0)

    monkeypatch.setattr(run.socket, "socket", lambda *a: ProxyRoute())
    assert run.local_addresses() == ["192.168.1.20"]
