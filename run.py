"""Start one local process; serves API and the built frontend on the same port."""
import os
import socket
import ipaddress
import json
import subprocess
import sys
from pathlib import Path

import uvicorn

from backend import db, security


def local_addresses():
    addresses = set()
    # Proxy TUN interfaces often hijack the default route. Inspect real Linux
    # interfaces first, then use portable hostname/route discovery as fallbacks.
    if sys.platform.startswith("linux"):
        try:
            interfaces = json.loads(subprocess.check_output(
                ["ip", "-j", "-4", "addr", "show", "up"], text=True, timeout=3
            ))
            for interface in interfaces:
                name = interface.get("ifname", "").lower()
                if name.startswith(("lo", "tun", "utun", "docker", "veth", "br-", "virbr", "tailscale", "meta")):
                    continue
                for info in interface.get("addr_info", []):
                    if info.get("family") == "inet":
                        addresses.add(info["local"])
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            if not item[4][0].startswith("127."):
                addresses.add(item[4][0])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            # UDP connect only selects a route; it sends no packet.
            sock.connect(("8.8.8.8", 80))
            addresses.add(sock.getsockname()[0])
    except OSError:
        pass
    usable = []
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not (ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified
                or ip in ipaddress.ip_network("198.18.0.0/15")):
            usable.append(address)
    return sorted(usable)


if __name__ == "__main__":
    if not (Path(__file__).parent / "frontend/dist/index.html").exists():
        raise SystemExit("请先构建前端：cd frontend && npm install && npm run build")
    db.init_db()
    security.initialize_access()
    port = int(os.environ.get("STUDY_PORT", "8000"))
    print(f"\n知习 · AI 学习助手\n电脑访问：http://localhost:{port}", flush=True)
    addresses = local_addresses()
    for address in addresses:
        print(f"手机同 Wi-Fi 访问：http://{address}:{port}", flush=True)
    if not addresses:
        print(f"未自动识别局域网地址，请在系统网络设置中查看 Wi-Fi IPv4 地址，使用 http://该地址:{port}。", flush=True)
    code = os.environ.get("STUDY_ACCESS_CODE")
    code_file = db.DATA_DIR / "access-code.txt"
    if not code and code_file.exists():
        code = code_file.read_text().strip()
    print(f"访问口令：{code or '已设置，请使用原口令'}", flush=True)
    print("手机无法访问时，请检查系统防火墙是否允许此端口，以及 Wi-Fi 是否开启了设备隔离。\n", flush=True)
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, workers=1)
