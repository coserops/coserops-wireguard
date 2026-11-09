#!/usr/bin/env python3
"""
wg_add_peer.py — Add a new WireGuard peer via SSH and print a QR code for phone scan.

Usage:
    不加 --split-tunnel（默认，全流量）

    python3 wg_add_peer.py --name phone-pixel9
    python3 wg_add_peer.py --name phone-pixel9 --dns 8.8.8.8 --split-tunnel

    python3 wg_add_peer.py --name ios18.5 --dns 1.1.1.1
"""

import argparse
import re
import sys
import os

# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------
try:
    import paramiko
except ImportError:
    sys.exit("Missing dependency: pip install paramiko")

try:
    import qrcode
except ImportError:
    sys.exit("Missing dependency: pip install 'qrcode[pil]'")

# ---------------------------------------------------------------------------
# Server settings — edit to match your deployment
# ---------------------------------------------------------------------------
SSH_HOST   = "43.160.212.73"
SSH_PORT   = 22
SSH_USER   = "ubuntu"
SSH_KEY    = os.path.expanduser("~/.ssh/tencent_cloud")
WG_CONF    = "/etc/wireguard/wg0.conf"
WG_IFACE   = "wg0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ssh_run(client: paramiko.SSHClient, cmd: str, sudo: bool = False) -> tuple[int, str, str]:
    """Run a command over SSH; return (exit_code, stdout, stderr)."""
    full_cmd = f"sudo {cmd}" if sudo else cmd
    stdin, stdout, stderr = client.exec_command(full_cmd, get_pty=False)
    out = stdout.read().decode()
    err = stderr.read().decode()
    rc  = stdout.channel.recv_exit_status()
    return rc, out, err


def ssh_append(client: paramiko.SSHClient, path: str, content: str) -> None:
    """Append *content* to a remote file using sudo tee -a (stdin pipe)."""
    _, stdout, stderr = client.exec_command(f"sudo tee -a {path} > /dev/null")
    # paramiko Transport keeps the channel alive; write then close the write side
    channel = stdout.channel
    channel.sendall(content.encode())
    channel.shutdown_write()
    rc = channel.recv_exit_status()
    if rc != 0:
        sys.exit(f"[!] Failed to append to {path}: {stderr.read().decode()}")


def pick_free_ip(conf_text: str, server_ip: str) -> str:
    """Return the lowest /32 IP not yet used by any peer or the server itself."""
    used = set(re.findall(r'AllowedIPs\s*=\s*([\d.]+)/32', conf_text))
    used.add(server_ip)
    parts  = server_ip.split('.')
    prefix = '.'.join(parts[:3])           # e.g. "10.0.0"
    for i in range(2, 254):
        candidate = f"{prefix}.{i}"
        if candidate not in used:
            return candidate
    sys.exit("[!] No free IPs remain in the /24 subnet.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Add a WireGuard peer on the remote server and print a QR code."
    )
    ap.add_argument("--name",         required=True, help="Peer label, e.g. phone-pixel9")
    ap.add_argument("--dns",          default="1.1.1.1", help="DNS server for the client (default: 1.1.1.1)")
    ap.add_argument("--split-tunnel", action="store_true",
                    help="Only route the VPN subnet, not all traffic")
    args = ap.parse_args()

    # ------------------------------------------------------------------
    # 1. Connect
    # ------------------------------------------------------------------
    print(f"[+] Connecting to {SSH_USER}@{SSH_HOST} ...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        SSH_HOST, port=SSH_PORT, username=SSH_USER,
        key_filename=SSH_KEY,
        look_for_keys=False,
        auth_timeout=15,
    )
    print("[+] Connected.")

    # ------------------------------------------------------------------
    # 2. Read server config
    # ------------------------------------------------------------------
    rc, conf, err = ssh_run(ssh, f"cat {WG_CONF}", sudo=True)
    if rc != 0:
        sys.exit(f"[!] Cannot read {WG_CONF}: {err.strip()}")

    # Server private key
    m = re.search(r'^\s*PrivateKey\s*=\s*(\S+)', conf, re.MULTILINE)
    if not m:
        sys.exit("[!] PrivateKey not found in wg0.conf")
    srv_priv = m.group(1)

    # Derive server public key (runs wg pubkey on the server)
    rc, srv_pub, _ = ssh_run(ssh, f"echo '{srv_priv}' | wg pubkey")
    srv_pub = srv_pub.strip()

    # ListenPort
    m = re.search(r'^\s*ListenPort\s*=\s*(\d+)', conf, re.MULTILINE)
    listen_port = m.group(1) if m else "51820"

    # Server Address  (e.g. 10.0.0.1/24)
    m = re.search(r'^\s*Address\s*=\s*([\d.]+)/(\d+)', conf, re.MULTILINE)
    if not m:
        sys.exit("[!] Address not found in [Interface] section of wg0.conf")
    server_ip = m.group(1)     # e.g. "10.0.0.1"
    subnet    = m.group(2)     # e.g. "24"

    # ------------------------------------------------------------------
    # 3. Pick a free client IP
    # ------------------------------------------------------------------
    client_ip = pick_free_ip(conf, server_ip)
    print(f"[+] Assigning client IP: {client_ip}/32")

    # ------------------------------------------------------------------
    # 4. Generate client keypair + PSK on the server
    # ------------------------------------------------------------------
    rc, client_priv, _ = ssh_run(ssh, "wg genkey")
    client_priv = client_priv.strip()

    rc, client_pub, _ = ssh_run(ssh, f"echo '{client_priv}' | wg pubkey")
    client_pub = client_pub.strip()

    rc, psk, _ = ssh_run(ssh, "wg genpsk")
    psk = psk.strip()

    print("[+] Generated client keypair and PSK.")

    # ------------------------------------------------------------------
    # 5. Append new [Peer] block to server config
    # ------------------------------------------------------------------
    peer_block = (
        f"\n"
        f"# Peer: {args.name}\n"
        f"[Peer]\n"
        f"PublicKey = {client_pub}\n"
        f"PresharedKey = {psk}\n"
        f"AllowedIPs = {client_ip}/32\n"
    )
    ssh_append(ssh, WG_CONF, peer_block)
    print(f"[+] Appended peer block to {WG_CONF}.")

    # ------------------------------------------------------------------
    # 6. Hot-reload (no existing clients dropped)
    # ------------------------------------------------------------------
    reload_cmd = f"bash -c 'wg syncconf {WG_IFACE} <(wg-quick strip {WG_IFACE})'"
    rc, out, err = ssh_run(ssh, reload_cmd, sudo=True)
    if rc != 0:
        print(f"[!] syncconf failed ({err.strip()}), falling back to full restart ...")
        rc, out, err = ssh_run(ssh, f"systemctl restart wg-quick@{WG_IFACE}", sudo=True)
        if rc != 0:
            sys.exit(f"[!] Restart failed: {err.strip()}")
        print("[+] WireGuard restarted (existing peers disconnected briefly).")
    else:
        print("[+] WireGuard hot-reloaded (existing peers unaffected).")

    ssh.close()

    # ------------------------------------------------------------------
    # 7. Build client config
    # ------------------------------------------------------------------
    parts       = server_ip.split('.')
    subnet_cidr = '.'.join(parts[:3]) + f'.0/{subnet}'

    allowed_ips = (
        f"{subnet_cidr}"        # split-tunnel: only VPN subnet
        if args.split_tunnel
        else "0.0.0.0/0, ::/0"  # full-tunnel: all traffic through VPN
    )

    client_conf = (
        f"[Interface]\n"
        f"PrivateKey = {client_priv}\n"
        f"Address = {client_ip}/32\n"
        f"DNS = {args.dns}\n"
        f"\n"
        f"[Peer]\n"
        f"PublicKey = {srv_pub}\n"
        f"PresharedKey = {psk}\n"
        f"Endpoint = {SSH_HOST}:{listen_port}\n"
        f"AllowedIPs = {allowed_ips}\n"
        f"PersistentKeepalive = 25\n"
    )

    # ------------------------------------------------------------------
    # 8. Print QR code to terminal
    # ------------------------------------------------------------------
    print()
    print("=" * 64)
    print(f"  WireGuard QR — scan with the WireGuard app on your phone")
    print(f"  Peer: {args.name}   IP: {client_ip}")
    print("=" * 64)
    print()

    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        border=2,
    )
    qr.add_data(client_conf)
    qr.make(fit=True)
    qr.print_ascii(invert=True)

    print()
    print("=" * 64)
    print(f"[+] Done. Client config (keep private):\n")
    print(client_conf)


if __name__ == "__main__":
    main()
