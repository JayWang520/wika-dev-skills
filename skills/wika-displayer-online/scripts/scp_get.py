#!/usr/bin/env python3
"""Download a file from the WIKA display device via scp (password auth).

Usage: python3 scp_get.py <remote_path> <local_path>
"""
import os
import pexpect
import sys

HOST = os.environ.get("WIKA_SSH_HOST", "display")
USER = os.environ.get("WIKA_SSH_USER")
PW = os.environ.get("WIKA_SSH_PASSWORD")
target = f"{USER}@{HOST}" if USER else HOST

remote, local = sys.argv[1], sys.argv[2]
child = pexpect.spawn(
    "/usr/bin/scp",
    ["-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=8",
     f"{target}:{remote}", local],
    encoding="utf-8", timeout=120,
)
i = child.expect(["[Pp]assword:", pexpect.EOF, pexpect.TIMEOUT])
if i == 2:
    child.close(force=True)
    raise SystemExit("SSH/SCP connection timed out")
if i == 0:
    if not PW:
        child.close(force=True)
        raise SystemExit("Configure SSH keys or set WIKA_SSH_PASSWORD locally")
    child.sendline(PW)
    child.expect(pexpect.EOF, timeout=120)
print(child.before[-200:] if child.before else "")
child.close()
sys.exit(child.exitstatus if child.exitstatus is not None else 1)
