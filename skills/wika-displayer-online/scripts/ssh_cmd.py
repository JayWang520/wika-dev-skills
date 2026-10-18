#!/usr/bin/env python3
"""Execute a remote command on the WIKA display device via SSH (password auth).

Usage: python3 ssh_cmd.py "<remote command>"
"""
import os
import pexpect
import sys

HOST = os.environ.get("WIKA_SSH_HOST", "display")
USER = os.environ.get("WIKA_SSH_USER")
PW = os.environ.get("WIKA_SSH_PASSWORD")
target = f"{USER}@{HOST}" if USER else HOST

cmd = sys.argv[1]
child = pexpect.spawn(
    "/usr/bin/ssh",
    ["-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=8",
     target, cmd],
    encoding="utf-8", timeout=40,
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
    child.expect(pexpect.EOF)
print(child.before)
child.close()
sys.exit(child.exitstatus if child.exitstatus is not None else 1)
