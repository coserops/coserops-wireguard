#!/usr/bin/env python3
"""
wg_remove_peer.py — Remove a WireGuard peer by name comment or public key.

Usage:
    python3 wg_remove_peer.py --name phone-pixel9
    python3 wg_remove_peer.py --list
"""

import argparse
import re
import sys
import os

try:
    import paramiko
except ImportError:
    sys.exit("Missing dependency: pip install paramiko")

SSH_HOST = "43.160.212.73"
SSH_PORT = 22
SSH_USER = "ubuntu"
SSH_KEY  = os.path.expanduser("~/.ssh/tencent_cloud")
WG_CONF  = "/etc/wireguard/wg0.conf"
WG_IFACE = "wg0"


def ssh_run(client, cmd, sudo=False):
    full_cmd = f"sudo {cmd}" if sudo else cmd
    _, stdout, stderr = client.exec_command(full_cmd)
    out = stdout.read().decode()
    err = stderr.read().decode()
    rc  = stdout.channel.recv_exit_status()
    return rc, out, err


def parse_peers(conf: str) -> list[dict]:
    """Return list of dicts with keys: name, pubkey, allowed_ips, raw_block."""
    peers = []
    # Split on [Peer] sections; keep the header
    blocks = re.split(r'(?=^\[Peer\])', conf, flags=re.MULTILINE)
    for block in blocks:
        if not block.strip().startswith('[Peer]'):
            continue
        name_m = re.search(r'^#\s*Peer:\s*(.+)', block, re.MULTILINE)
        pub_m  = re.search(r'^\s*PublicKey\s*=\s*(\S+)', block, re.MULTILINE)
        ip_m   = re.search(r'^\s*AllowedIPs\s*=\s*(\S+)', block, re.MULTILINE)
        peers.append({
            'name':        name_m.group(1).strip() if name_m else '(unnamed)',
            'pubkey':      pub_m.group(1)  if pub_m  else '',
            'allowed_ips': ip_m.group(1)   if ip_m   else '',
            'raw_block':   block,
        })
    return peers


def main():
    ap = argparse.ArgumentParser(description="Remove a WireGuard peer from the server.")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--name", help="Peer name comment as used in wg_add_peer.py")
    group.add_argument("--list", action="store_true", help="List all peers and exit")
    args = ap.parse_args()

    print(f"[+] Connecting to {SSH_USER}@{SSH_HOST} ...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER,
                key_filename=SSH_KEY, look_for_keys=False, auth_timeout=15)
    print("[+] Connected.")

    rc, conf, err = ssh_run(ssh, f"cat {WG_CONF}", sudo=True)
    if rc != 0:
        sys.exit(f"[!] Cannot read {WG_CONF}: {err.strip()}")

    peers = parse_peers(conf)

    if args.list:
        if not peers:
            print("  (no peers found)")
        for p in peers:
            print(f"  name={p['name']}  ip={p['allowed_ips']}  pubkey={p['pubkey'][:20]}...")
        ssh.close()
        return

    # Find the peer to remove
    target = [p for p in peers if p['name'] == args.name]
    if not target:
        names = [p['name'] for p in peers]
        sys.exit(f"[!] No peer named '{args.name}'. Known peers: {names}")
    if len(target) > 1:
        sys.exit(f"[!] Multiple peers named '{args.name}'. Remove manually.")

    peer = target[0]
    print(f"[+] Removing peer: name={peer['name']}  ip={peer['allowed_ips']}")

    # Remove the block from config text
    new_conf = conf.replace(peer['raw_block'], '')
    # Collapse extra blank lines
    new_conf = re.sub(r'\n{3,}', '\n\n', new_conf)

    # Write new config via temp file + mv (atomic)
    escaped = new_conf.replace("'", "'\\''")
    write_cmd = f"bash -c 'printf \"%s\" '\"'\"'{escaped}'\"'\"' | sudo tee {WG_CONF}.tmp > /dev/null && sudo mv {WG_CONF}.tmp {WG_CONF}'"
    rc, _, err = ssh_run(ssh, write_cmd)
    if rc != 0:
        # Fallback: write via python3 on the server
        import base64 as _b64
        b64_conf  = _b64.b64encode(new_conf.encode()).decode()
        py_script = f"import base64; open('/tmp/wg0_new.conf','w').write(base64.b64decode('{b64_conf}').decode())"
        ssh_run(ssh, f"python3 -c '{py_script}'")
        rc2, _, err2 = ssh_run(ssh, f"mv /tmp/wg0_new.conf {WG_CONF}", sudo=True)
        if rc2 != 0:
            sys.exit(f"[!] Failed to write config: {err2.strip()}")

    print(f"[+] Config updated.")

    # Hot-reload
    reload_cmd = f"bash -c 'wg syncconf {WG_IFACE} <(wg-quick strip {WG_IFACE})'"
    rc, _, err = ssh_run(ssh, reload_cmd, sudo=True)
    if rc != 0:
        print(f"[!] syncconf failed, falling back to restart ...")
        rc, _, err = ssh_run(ssh, f"systemctl restart wg-quick@{WG_IFACE}", sudo=True)
        if rc != 0:
            sys.exit(f"[!] Restart failed: {err.strip()}")
        print("[+] WireGuard restarted.")
    else:
        print("[+] WireGuard hot-reloaded.")

    ssh.close()
    print(f"[+] Done. Peer '{peer['name']}' removed.")


if __name__ == "__main__":
    main()
