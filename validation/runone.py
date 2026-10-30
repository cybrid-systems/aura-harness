"""run one Aura file, print the last lines of its output + child max RSS and wall time"""
import os, resource, subprocess, sys, time
f, tail, to = sys.argv[1], int(os.environ.get("PROBE_TAIL", "6")), int(os.environ.get("PROBE_TIMEOUT", "300"))
env = dict(os.environ, AURA_PATH=os.environ.get("AURA_LIB", ""), AURA_SANDBOX="off", AURA_PIPELINE_STRICT="0")
t0 = time.time()
try:
    p = subprocess.run([os.environ["AURA_BIN"], os.path.basename(f)], cwd=os.path.dirname(f) or ".", env=env,
                       capture_output=True, text=True, timeout=to)
    out, rc = p.stdout + p.stderr, p.returncode
except subprocess.TimeoutExpired as e:
    out, rc = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), "timeout"
lines = [l for l in out.splitlines() if l.strip()]
print("\n".join(lines[-tail:]))
print(f"rc={rc} rss_mb={resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss // 1024} wall_s={time.time() - t0:.2f}")
