"""Outcome-blind startup admission for the actual scientific service sandbox."""

import errno
import os
import socket
import tempfile
from pathlib import Path

assert os.geteuid() != 0
for family in (socket.AF_INET, socket.AF_INET6):
    try:
        socket.socket(family, socket.SOCK_STREAM)
    except OSError as error:
        assert error.errno in (errno.EPERM, errno.EACCES, errno.EAFNOSUPPORT)
    else:
        raise AssertionError("network_not_denied")
try:
    Path("/var/lib/phase55/work/sandbox-deny-sentinel").open("x")
except OSError as error:
    assert error.errno in (errno.EPERM, errno.EACCES, errno.EROFS)
else:
    raise AssertionError("code_mount_writable")
assert not any(
    os.environ.get(k)
    for k in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "OANDA_API_KEY",
    )
)
with tempfile.TemporaryDirectory() as directory:
    Path(directory, "probe").write_text("disposable")
# SciPy creates temporary diagnostic streams during import. The original small
# sample did not exercise this optional GARCH dependency import under isolation.
import arch  # noqa: E402,F401
import scipy.stats  # noqa: E402,F401

print("network_and_code_write_denial_private_temp_scientific_imports_verified")
