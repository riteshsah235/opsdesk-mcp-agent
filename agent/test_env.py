"""Checks which environment variable NAMES the contained gateway and relay processes hold.
Presence/absence only: no value is ever read into output. Needs gg and Linux; skipped otherwise."""
import os, shutil, subprocess, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mcp_client import McpClient

SENT_GROQ, SENT_PK = "sentinel-groq-not-a-key", "sentinel-user:sentinel-token"


def env_names(pid):
    try:
        raw = open("/proc/%s/environ" % pid, "rb").read().split(b"\0")
    except OSError:
        return None
    return {e.split(b"=", 1)[0].decode() for e in raw if b"=" in e}


def contained_procs():
    found = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            cmd = open("/proc/%s/cmdline" % pid, "rb").read().decode(errors="replace").replace("\0", " ")
        except OSError:
            continue
        if ("--modules" in cmd and "--httpPort 18081" in cmd) or "relay.py http://127.0.0.1:18081" in cmd:
            names = env_names(pid)
            if names is not None:
                found.append((pid, cmd.split()[0], names))
    return found


STUB = """#!/bin/sh
# Stand-in for gg: records the NAMES of its own and its parent's environment variables, then waits.
tr '\\0' '\\n' < /proc/$$/environ | cut -d= -f1 | sort > "@OUT@.self"
tr '\\0' '\\n' < /proc/$PPID/environ | cut -d= -f1 | sort > "@OUT@.parent"
sleep 30
"""


class Passthrough(unittest.TestCase):
    """Uses a stub in place of gg, so a placeholder Project Key cannot make a real gg exit."""
    def test_only_project_key_reaches_gateway_and_model_key_never_enters(self):
        import tempfile, time
        with tempfile.TemporaryDirectory() as d:
            stub = os.path.join(d, "gg"); open(stub, "w").write(STUB.replace("@OUT@", os.path.join(d, "names"))); os.chmod(stub, 0o755)
            out = os.path.join(d, "names")
            env = dict(os.environ, GG=stub, GROQ_API_KEY=SENT_GROQ, GROQ_MODEL="m", GC_PROJECT_KEY=SENT_PK, SOME_OTHER_SECRET="x")
            p = subprocess.Popen(["sh", os.path.join(HERE, "contained.sh")], env=env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(100):
                    if os.path.exists(out + ".parent"):
                        break
                    time.sleep(0.1)
                self.assertTrue(os.path.exists(out + ".parent"), "stub did not start (needs unshare -rn)")
                time.sleep(0.3)
                own = set(open(out + ".self").read().split())
                parent = set(open(out + ".parent").read().split())
            finally:
                p.kill(); p.wait()
                subprocess.run(["pkill", "-f", stub])
            self.assertIn("GC_PROJECT_KEY", own)
            self.assertNotIn("SOME_OTHER_SECRET", own)
            for names in (own, parent):
                self.assertNotIn("GROQ_API_KEY", names)
                self.assertNotIn("GROQ_MODEL", names)
            self.assertLessEqual(len(own), 12, sorted(own))


@unittest.skipUnless(sys.platform.startswith("linux") and (os.environ.get("GG") or shutil.which("gg")), "needs Linux and gg")
class ContainedEnvironment(unittest.TestCase):
    def test_real_gateway_has_no_model_key(self):
        saved = {k: os.environ.get(k) for k in ("GROQ_API_KEY", "GC_PROJECT_KEY")}
        os.environ["GROQ_API_KEY"] = SENT_GROQ
        os.environ.pop("GC_PROJECT_KEY", None)
        c = McpClient(relay_cmd=["sh", os.path.join(HERE, "contained.sh")])
        try:
            c.connect()
            self.assertTrue(c.list_tools())  # gateway works with the reduced environment
            procs = contained_procs()
            self.assertGreaterEqual(len(procs), 2, "expected gateway and relay processes")
            for pid, exe, names in procs:
                self.assertNotIn("GROQ_API_KEY", names, "process %s holds the model key variable" % exe)
                self.assertNotIn("GROQ_MODEL", names)
            gg = [n for _, exe, n in procs if os.path.basename(exe) == "gg"]
            self.assertTrue(gg, "gg process not found")
            self.assertNotIn("GC_PROJECT_KEY", gg[0])  # none set, none invented
            self.assertLessEqual(len(gg[0]), 12, "gateway environment is larger than expected: %s" % sorted(gg[0]))
        finally:
            c.close()
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


if __name__ == "__main__":
    unittest.main(verbosity=1)
