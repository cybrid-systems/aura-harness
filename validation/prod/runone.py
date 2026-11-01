"""Run one Aura file under a pty (Aura block-buffers stdout on a pipe), kill the whole process
group on timeout, and keep every line printed before the hang.  Used by run_validation.py.
"""
import os, pty, select, signal, subprocess, sys, time


def run(path, timeout=120.0, env=None, cwd=None):
    aura = os.environ["AURA_BIN"]
    lib = os.environ.get("AURA_LIB")  # aura only finds its stdlib via AURA_PATH / cwd ../lib (aura#4824)
    if lib and lib not in os.environ.get("AURA_PATH", "").split(":"):
        env = {"AURA_PATH": lib + (":" + os.environ["AURA_PATH"] if os.environ.get("AURA_PATH") else ""), **(env or {})}
    m, s = pty.openpty()
    t0 = time.monotonic()
    p = subprocess.Popen([aura, "--load", path], stdin=subprocess.DEVNULL, stdout=s, stderr=s,
                         start_new_session=True, cwd=cwd,
                         env={**os.environ, "AURA_SANDBOX": "off", "AURA_PIPELINE_STRICT": "0", **(env or {})})
    os.close(s)
    buf, timed_out = bytearray(), False
    while True:
        left = timeout - (time.monotonic() - t0)
        if left <= 0:
            timed_out = True
            os.killpg(p.pid, signal.SIGKILL)
            break
        r, _, _ = select.select([m], [], [], min(left, 0.5))
        if r:
            try:
                chunk = os.read(m, 65536)
            except OSError:
                chunk = b""
            if not chunk:
                break
            buf += chunk
        elif p.poll() is not None:
            break
    try:
        while True:
            r, _, _ = select.select([m], [], [], 0.2)
            if not r:
                break
            chunk = os.read(m, 65536)
            if not chunk:
                break
            buf += chunk
    except OSError:
        pass
    os.close(m)
    rc = p.wait()
    return {"rc": rc, "timed_out": timed_out, "secs": round(time.monotonic() - t0, 3),
            "out": buf.decode("utf-8", "replace").replace("\r\n", "\n")}


if __name__ == "__main__":
    r = run(sys.argv[1], float(os.environ.get("VAL_TIMEOUT", "120")))
    sys.stdout.write(r["out"])
    print(f"## rc={r['rc']} timed_out={r['timed_out']} secs={r['secs']}")
