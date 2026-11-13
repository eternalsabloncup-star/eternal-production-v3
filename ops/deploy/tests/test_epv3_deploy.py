"""Failure-simulation tests. Fully isolated: temp git origin, temp 'VPS' dirs, stub commands.
No network, no systemd, no PostgreSQL, no real services.
"""
import fcntl
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import epv3_deploy as D  # noqa: E402

SCRIPT = Path(D.__file__)

STUBS = {
    "systemctl": '''#!{py}
import os, shutil, sys
w = os.environ["WORLD"]; unit = sys.argv[1]
open(f"{{w}}/restart.log", "a").write(unit + "\\n")
if os.path.exists(f"{{w}}/fail_restart_{{unit}}"):
    os.remove(f"{{w}}/fail_restart_{{unit}}"); sys.exit(1)
src = {{"epv3-api": "opt/backend/app/main.py", "epv3-accurate-gateway": "opt/gateway/app/main.py"}}[unit]
shutil.copy(f"{{w}}/{{src}}", f"{{w}}/run/{{unit}}.loaded")
''',
    "pg_dump": '''#!{py}
import os, sys
if os.path.exists(os.environ["WORLD"] + "/fail_dump"): sys.exit(1)
open(sys.argv[1], "w").write("DUMP")
''',
    "pg_restore_list": "#!{py}\nimport sys; open(sys.argv[1]).read()\n",
    "frontend_build": '''#!{py}
import os
w = os.environ["WORLD"]; open(f"{{w}}/build.count", "a").write("x")
src = open("src/x.txt").read()
os.makedirs("dist/assets", exist_ok=True)
open("dist/index.html", "w").write('<script src="/assets/app.js"></script>' + src)
if "NOASSET" not in src: open("dist/assets/app.js", "w").write("js" + src)
''',
    "db_revision": '#!{py}\nimport os; print(open(os.environ["WORLD"] + "/db_rev").read())\n',
    "alembic_upgrade": '#!{py}\nimport os; open(os.environ["WORLD"] + "/db_rev", "w").write("rev0002")\n',
    "ci": '#!{py}\nimport os; print(open(os.environ["WORLD"] + "/ci.json").read())\n',
}

BASE_FILES = {
    "backend/app/main.py": "# backend v1\n",
    "backend/app/util.py": "# util v1\n",
    "backend/requirements.txt": "fastapi\n",
    "backend/tests/test_a.py": "# t1\n",
    "backend/alembic/versions/r1.py": 'revision = "rev0001"\ndown_revision = None\n',
    "accurate-gateway/app/main.py": "# gateway v1\n",
    "accurate-gateway/requirements.txt": "httpx\n",
    "frontend/src/x.txt": "fe v1\n",
    "frontend/package.json": "{}\n",
    "staging-proxy/app.py": "proxy v1\n",
    "docs/a.md": "doc\n",
}


def sh(*a, cwd=None):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class World:
    def __init__(self, tmp: Path):
        self.t = tmp
        self.origin = tmp / "origin"
        self.w = tmp / "world"
        for d in ("run", "opt", "bin", "backups", "deploy"):
            (self.w / d).mkdir(parents=True, exist_ok=True)
        sh("git", "init", "-q", "-b", "main", str(self.origin))
        sh("git", "-C", str(self.origin), "config", "user.email", "t@t")
        sh("git", "-C", str(self.origin), "config", "user.name", "t")
        self.files = dict(BASE_FILES)
        self.base = self.commit("base")
        for sub, src in (("backend", "backend"), ("gateway", "accurate-gateway")):
            for p, c in BASE_FILES.items():
                if p.startswith(src + "/"):
                    f = self.w / "opt" / sub / p[len(src) + 1:]
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_text(c)
        fe = self.w / "opt" / "frontend"
        (fe / "assets").mkdir(parents=True)
        (fe / "index.html").write_text('<script src="/assets/app.js"></script>fe v1\n')
        (fe / "assets/app.js").write_text("jsfe v1\n")
        (self.w / "opt/backend/.env").write_text("SECRET=1\n")
        (self.w / "opt/backend/.venv").mkdir()
        (self.w / "opt/backend/.venv/keep").write_text("v")
        for u, s in (("epv3-api", "backend"), ("epv3-accurate-gateway", "gateway")):
            (self.w / "run" / f"{u}.loaded").write_text(f"# {s} v1\n")
        (self.w / "db_rev").write_text("rev0001\n")
        self.set_ci(True)
        for n, body in STUBS.items():
            p = self.w / "bin" / n
            p.write_text(body.format(py=sys.executable))
            p.chmod(0o755)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        b = self.w / "bin"
        port = self.srv.server_port
        self.cfg = {
            "repo_url": str(self.origin), "github_repo": "x/y", "root": str(self.w / "deploy"),
            "backup_dir": str(self.w / "backups"), "keep_backups": 3, "health_timeout": 2, "asset_timeout": 1,
            "ci": {"command": [str(b / "ci")]},
            "proxy_health_url": f"http://127.0.0.1:{port}/proxy-health",
            "components": {
                "backend": {"src": "backend", "dest": str(self.w / "opt/backend"), "unit": "epv3-api",
                            "health_url": f"http://127.0.0.1:{port}/h/epv3-api"},
                "gateway": {"src": "accurate-gateway", "dest": str(self.w / "opt/gateway"),
                            "unit": "epv3-accurate-gateway",
                            "health_url": f"http://127.0.0.1:{port}/h/epv3-accurate-gateway"},
                "frontend": {"src": "frontend", "dest": str(self.w / "opt/frontend"),
                             "verify_base": f"http://127.0.0.1:{port}/fe"},
            },
            "commands": {
                "restart": [str(b / "systemctl"), "{unit}"],
                "pg_dump": [str(b / "pg_dump"), "{out}"],
                "pg_restore_list": [str(b / "pg_restore_list"), "{dump}"],
                "frontend_build": [str(b / "frontend_build")],
                "db_revision": [str(b / "db_revision")],
                "alembic_upgrade": [str(b / "alembic_upgrade"), "{cwd}"],
            },
        }
        self.cfg_path = self.t / "conf.json"
        self.cfg_path.write_text(json.dumps(self.cfg))
        os.environ["WORLD"] = str(self.w)
        assert self.run("init-baseline", "--sha", self.base, yes=True) == 0

    def handler(self):
        w = self.w

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                code, body = 404, b""
                if self.path.startswith("/h/"):
                    txt = (w / "run" / f"{self.path[3:]}.loaded").read_text()
                    code, body = (500, b"bad") if "BROKEN" in txt else (200, b"ok")
                elif self.path == "/proxy-health":
                    code, body = 200, b"ok"
                elif self.path.startswith("/fe"):
                    rel = self.path[3:].lstrip("/") or "index.html"
                    f = w / "opt/frontend" / rel
                    if (w / "stale_mount").exists():
                        f = w / "stale_copy" / rel
                    if f.is_file():
                        code, body = 200, f.read_bytes()
                self.send_response(code)
                self.end_headers()
                self.wfile.write(body)

        return H

    def commit(self, msg, **changes):
        for p, c in changes.items():
            p = p.replace("__", "/")
            if c is None:
                self.files.pop(p, None)
                (self.origin / p).unlink(missing_ok=True)
            else:
                self.files[p] = c
        for p, c in self.files.items():
            f = self.origin / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(c)
        sh("git", "-C", str(self.origin), "add", "-A")
        sh("git", "-C", str(self.origin), "commit", "-q", "-m", msg, "--allow-empty")
        return sh("git", "-C", str(self.origin), "rev-parse", "HEAD")

    def set_ci(self, ok=True, name_missing=None):
        names = D.DEFAULT_CI
        runs = [{"id": i, "name": n, "status": "completed", "conclusion": "success" if ok else "failure"}
                for i, n in enumerate(names) if n != name_missing]
        (self.w / "ci.json").write_text(json.dumps({"check_runs": runs}))

    def run(self, *args, yes=False):
        a = ["--config", str(self.cfg_path)] + (["--yes"] if yes else []) + list(args)
        return D.main(a)

    def deploy(self, sha, **kw):
        return self.run("deploy", "--sha", sha, yes=kw.get("yes", True))

    def read(self, rel):
        return (self.w / rel).read_text()

    def restarts(self):
        p = self.w / "restart.log"
        return p.read_text().split() if p.exists() else []

    def journal(self):
        return json.loads((self.w / "deploy/state/current.json").read_text())

    def snapshot(self):
        return {str(p.relative_to(self.w / "opt")): p.read_bytes()
                for p in sorted((self.w / "opt").rglob("*")) if p.is_file()}


@pytest.fixture
def W(tmp_path):
    w = World(tmp_path)
    yield w
    w.srv.shutdown()


def test_backend_only_restarts_only_backend_and_keeps_untracked(W):
    sha = W.commit("be", **{"backend__app__main.py": "# backend v2\n"})
    assert W.deploy(sha) == 0
    assert W.restarts() == ["epv3-api"]
    assert W.read("opt/backend/app/main.py") == "# backend v2\n"
    assert W.read("opt/backend/.env") == "SECRET=1\n"
    assert W.read("opt/backend/.venv/keep") == "v"
    assert W.read("opt/frontend/index.html").endswith("fe v1\n")
    assert json.loads(W.read("deploy/state/deployed.json"))["sha"] == sha
    sums = list((W.w / "backups").glob("deploy-*/SHA256SUMS"))
    assert len(sums) == 1 and "db.dump" in sums[0].read_text()


def test_dry_run_default_mutates_nothing(W):
    sha = W.commit("be", **{"backend__app__main.py": "# backend v2\n"})
    before = W.snapshot()
    assert W.deploy(sha, yes=False) == 0
    assert W.snapshot() == before and W.restarts() == []
    assert not list((W.w / "backups").iterdir())


def test_frontend_only_no_restart_and_artifact_reuse(W):
    s1 = W.commit("fe", **{"frontend__src__x.txt": "fe v2\n"})
    assert W.deploy(s1) == 0
    assert W.restarts() == []
    assert W.read("opt/frontend/assets/app.js") == "jsfe v2\n"
    s2 = W.commit("docs", **{"docs__a.md": "doc2\n"})
    assert W.deploy(s2) == 0  # docs only: no build, no restart
    assert W.read("opt/frontend/assets/app.js") == "jsfe v2\n"
    assert len(W.read("build.count")) == 1
    # same frontend tree reused after revert-like commit sequence
    s3 = W.commit("fe back", **{"frontend__src__x.txt": "fe v1\n"})
    assert W.deploy(s3) == 0
    s4 = W.commit("fe again", **{"frontend__src__x.txt": "fe v2\n"})
    assert W.deploy(s4) == 0
    assert len(W.read("build.count")) == 2  # v2 artifact from s1 reused for s4


def test_gateway_only(W):
    sha = W.commit("gw", **{"accurate-gateway__app__main.py": "# gateway v2\n"})
    assert W.deploy(sha) == 0
    assert W.restarts() == ["epv3-accurate-gateway"]


def test_tests_only_change_syncs_without_restart(W):
    sha = W.commit("t", **{"backend__tests__test_a.py": "# t2\n"})
    assert W.deploy(sha) == 0
    assert W.restarts() == []
    assert W.read("opt/backend/tests/test_a.py") == "# t2\n"


def test_health_failure_rolls_back_code_and_restarts_old(W):
    before = W.snapshot()
    sha = W.commit("bad", **{"backend__app__main.py": "# BROKEN\n", "backend__app__new.py": "# n\n",
                             "backend__app__util.py": None})
    assert W.deploy(sha) == D.EXIT_ROLLED_BACK
    assert W.snapshot() == before
    assert W.restarts() == ["epv3-api", "epv3-api"]
    assert W.journal()["status"] == "rolled_back"
    assert json.loads(W.read("deploy/state/deployed.json"))["sha"] == W.base


def test_restart_command_failure_rolls_back(W):
    (W.w / "fail_restart_epv3-accurate-gateway").write_text("")
    before = W.snapshot()
    sha = W.commit("gw+be", **{"accurate-gateway__app__main.py": "# gateway v2\n",
                               "backend__app__main.py": "# backend v2\n"})
    assert W.deploy(sha) == D.EXIT_ROLLED_BACK
    assert W.snapshot() == before


def test_frontend_public_verify_failure_rolls_back_dir(W):
    before = W.snapshot()
    sha = W.commit("fe bad", **{"frontend__src__x.txt": "NOASSET\n"})
    assert W.deploy(sha) == D.EXIT_ROLLED_BACK
    assert W.snapshot() == before
    assert not list((W.w / "opt/frontend").rglob(".*epv3*"))


@pytest.mark.parametrize("phase", ["backup", "applied:backend", "restart"])
def test_crash_mid_deploy_then_recover(W, phase):
    before = W.snapshot()
    sha = W.commit("be", **{"backend__app__main.py": "# backend v2\n", "backend__app__new.py": "# n\n"})
    env = dict(os.environ, EPV3_DEPLOY_TEST_HOOKS="1", EPV3_DEPLOY_CRASH_AT=phase)
    p = subprocess.run([sys.executable, str(SCRIPT), "--config", str(W.cfg_path), "--yes",
                        "deploy", "--sha", sha], env=env, capture_output=True)
    assert p.returncode == 137
    assert W.journal()["status"] == "in_progress"
    assert W.deploy(sha) == D.EXIT_UNFINISHED  # new deploy refused
    assert W.run("recover", yes=False) == 0 and W.journal()["status"] == "in_progress"  # dry-run
    assert W.run("recover", yes=True) == D.EXIT_ROLLED_BACK
    assert W.snapshot() == before
    assert W.deploy(sha) == 0  # clean retry works after recovery
    assert W.read("opt/backend/app/main.py") == "# backend v2\n"


def test_lock_prevents_concurrent_deploy(W):
    sha = W.commit("be", **{"backend__app__main.py": "# backend v2\n"})
    (W.w / "deploy/state").mkdir(parents=True, exist_ok=True)
    fh = open(W.w / "deploy/state/deploy.lock", "a+")
    fcntl.flock(fh, fcntl.LOCK_EX)
    try:
        assert W.deploy(sha) == D.EXIT_REFUSED
    finally:
        fh.close()
    assert W.restarts() == []


@pytest.mark.parametrize("bad", ["main", "abc1234", "A" * 40, "0" * 40])
def test_exact_sha_required(W, bad):
    assert W.deploy(bad) == D.EXIT_REFUSED


def test_sha_not_on_main_refused(W):
    sh("git", "-C", str(W.origin), "checkout", "-q", "-b", "feature")
    sha = W.commit("f", **{"backend__app__main.py": "# backend v2\n"})
    sh("git", "-C", str(W.origin), "checkout", "-q", "main")
    assert W.deploy(sha) == D.EXIT_REFUSED
    assert W.restarts() == []


def test_ci_not_green_refused(W):
    sha = W.commit("be", **{"backend__app__main.py": "# backend v2\n"})
    W.set_ci(False)
    assert W.deploy(sha) == D.EXIT_REFUSED
    W.set_ci(True, name_missing=D.DEFAULT_CI[2])
    assert W.deploy(sha) == D.EXIT_REFUSED
    assert W.restarts() == []


def test_migration_disabled_by_default_in_deploy(W):
    sha = W.commit("mig", **{"backend__alembic__versions__r2.py":
                             'revision = "rev0002"\ndown_revision = "rev0001"\n'})
    assert W.deploy(sha) == D.EXIT_REFUSED  # DB at rev0001, head rev0002
    assert W.read("db_rev") == "rev0001\n" and W.restarts() == []


def test_migrate_requires_enabled_and_valid_approval_then_deploy_ok(W):
    sha = W.commit("mig", **{"backend__alembic__versions__r2.py":
                             'revision = "rev0002"\ndown_revision = "rev0001"\n'})
    appr = W.t / "appr.json"
    appr.write_text(json.dumps({"sha": sha, "action": "alembic_upgrade", "approved_by": "Owner",
                                "expires": "2099-01-01T00:00:00Z"}))
    assert W.run("migrate", "--sha", sha, "--approval-file", str(appr), yes=True) == D.EXIT_REFUSED  # disabled
    W.cfg["migrations"] = {"enabled": True}
    W.cfg_path.write_text(json.dumps(W.cfg))
    appr.write_text(json.dumps({"sha": "f" * 40, "action": "alembic_upgrade", "approved_by": "Owner",
                                "expires": "2099-01-01T00:00:00Z"}))
    assert W.run("migrate", "--sha", sha, "--approval-file", str(appr), yes=True) == D.EXIT_REFUSED
    appr.write_text(json.dumps({"sha": sha, "action": "alembic_upgrade", "approved_by": "Owner",
                                "expires": "2000-01-01T00:00:00Z"}))
    assert W.run("migrate", "--sha", sha, "--approval-file", str(appr), yes=True) == D.EXIT_REFUSED
    assert W.read("db_rev") == "rev0001\n"
    appr.write_text(json.dumps({"sha": sha, "action": "alembic_upgrade", "approved_by": "Owner",
                                "expires": "2099-01-01T00:00:00Z"}))
    assert W.run("migrate", "--sha", sha, "--approval-file", str(appr), yes=False) == 0
    assert W.read("db_rev") == "rev0001\n"  # dry-run
    assert W.run("migrate", "--sha", sha, "--approval-file", str(appr), yes=True) == 0
    assert W.read("db_rev") == "rev0002"
    assert list((W.w / "backups").glob("deploy-*-migrate-*/db.dump"))
    assert W.deploy(sha) == 0


def test_dependency_and_proxy_changes_blocked(W):
    s = W.commit("dep", **{"backend__requirements.txt": "fastapi\nnew\n"})
    assert W.deploy(s) == D.EXIT_REFUSED
    s = W.commit("proxy", **{"staging-proxy__app.py": "proxy v2\n"})
    assert W.deploy(s) == D.EXIT_REFUSED


def test_drift_always_stops_no_override_flag(W):
    (W.w / "opt/backend/app/main.py").write_text("hand edited\n")
    sha = W.commit("be", **{"backend__app__main.py": "# backend v2\n"})
    assert W.deploy(sha) == D.EXIT_REFUSED
    with pytest.raises(SystemExit):
        W.run("deploy", "--sha", sha, "--accept-drift", yes=True)
    assert W.read("opt/backend/app/main.py") == "hand edited\n" and W.restarts() == []
    # missing runtime file is drift too
    (W.w / "opt/backend/app/main.py").write_text("# backend v1\n")
    (W.w / "opt/backend/app/main.py").unlink()
    assert W.deploy(sha) == D.EXIT_REFUSED


def test_frontend_drift_stops_and_baseline_rejects_drift(W):
    (W.w / "opt/frontend/assets/app.js").write_text("hand edited")
    sha = W.commit("fe", **{"frontend__src__x.txt": "fe v2\n"})
    assert W.deploy(sha) == D.EXIT_REFUSED
    assert W.restarts() == [] and W.read("opt/frontend/assets/app.js") == "hand edited"
    (W.w / "opt/backend/app/util.py").write_text("# drifted\n")
    assert W.run("init-baseline", "--sha", W.base, yes=True) == D.EXIT_REFUSED


def test_baseline_reconciled_after_owner_fix_allows_deploy(W):
    (W.w / "opt/backend/app/main.py").write_text("hand edited\n")
    sha = W.commit("be", **{"backend__app__main.py": "# backend v2\n"})
    assert W.deploy(sha) == D.EXIT_REFUSED
    (W.w / "opt/backend/app/main.py").write_text("# backend v1\n")  # reconciled to baseline
    assert W.deploy(sha) == 0


def test_dump_failure_aborts_before_mutation(W):
    (W.w / "fail_dump").write_text("")
    before = W.snapshot()
    sha = W.commit("be", **{"backend__app__main.py": "# backend v2\n"})
    assert W.deploy(sha) == D.EXIT_ROLLED_BACK
    assert W.snapshot() == before and W.restarts() == []


def test_corrupt_backup_makes_rollback_fail_loudly(W, monkeypatch):
    sha = W.commit("bad", **{"backend__app__main.py": "# BROKEN\n"})
    orig = D.Runner.restart_and_health

    def corrupt_then_fail(self, name):
        for f in Path(self.cur["backup"]).glob("backend.tar.gz"):
            f.write_bytes(b"corrupt")
        return orig(self, name)

    monkeypatch.setattr(D.Runner, "restart_and_health", corrupt_then_fail)
    assert W.deploy(sha) == D.EXIT_ROLLBACK_FAILED
    assert W.journal()["status"] == "rollback_failed"
    assert W.deploy(sha) == D.EXIT_UNFINISHED


def test_backup_pruning_keeps_recent(W):
    for i in range(5):
        sha = W.commit(f"be{i}", **{"backend__app__main.py": f"# backend {i + 2}\n"})
        assert W.deploy(sha) == 0
    assert len(list((W.w / "backups").glob("deploy-*"))) == 3


def test_evaluate_ci_picks_latest_run_per_name():
    runs = {"check_runs": [{"id": 1, "name": "a", "status": "completed", "conclusion": "failure"},
                           {"id": 2, "name": "a", "status": "completed", "conclusion": "success"}]}
    D.evaluate_ci(runs, ["a"], "x" * 40)
    with pytest.raises(D.Refused):
        D.evaluate_ci({"check_runs": [{"id": 1, "name": "a", "status": "in_progress"}]}, ["a"], "x" * 40)


# ---- DB revision verification (no alembic wrapper required) ----
def test_deploy_requires_db_at_target_head_even_without_migration(W):
    sha = W.commit("be", **{"backend__app__main.py": "# backend v2\n"})
    (W.w / "db_rev").write_text("rev0000\n")
    assert W.deploy(sha) == D.EXIT_REFUSED
    (W.w / "db_rev").write_text("rev0001\nrev0002\n")  # multiple rows
    assert W.deploy(sha) == D.EXIT_REFUSED
    (W.w / "db_rev").write_text("")  # empty
    assert W.deploy(sha) == D.EXIT_REFUSED
    assert W.restarts() == []
    (W.w / "db_rev").write_text("rev0001\n")
    assert W.deploy(sha) == 0


def test_db_revision_command_failure_refuses(W):
    W.cfg["commands"]["db_revision"] = [str(W.w / "bin/pg_dump")]  # exits 1 when fail_dump present
    W.cfg_path.write_text(json.dumps(W.cfg))
    (W.w / "fail_dump").write_text("")
    sha = W.commit("be", **{"backend__app__main.py": "# backend v2\n"})
    assert W.deploy(sha) == D.EXIT_REFUSED and W.restarts() == []


def test_migrate_refused_without_executor_configured(W):
    sha = W.commit("mig", **{"backend__alembic__versions__r2.py":
                             'revision = "rev0002"\ndown_revision = "rev0001"\n'})
    W.cfg["migrations"] = {"enabled": True}
    del W.cfg["commands"]["alembic_upgrade"]
    W.cfg_path.write_text(json.dumps(W.cfg))
    appr = W.t / "appr.json"
    appr.write_text(json.dumps({"sha": sha, "action": "alembic_upgrade", "approved_by": "Owner",
                                "expires": "2099-01-01T00:00:00Z"}))
    assert W.run("migrate", "--sha", sha, "--approval-file", str(appr), yes=True) == D.EXIT_REFUSED
    assert W.read("db_rev") == "rev0001\n"


# ---- frontend cutover: in place, verified through the running mount ----
def test_frontend_cutover_is_in_place_and_removes_stale_assets(W):
    root = W.w / "opt/frontend"
    ino = root.stat().st_ino
    s1 = W.commit("fe", **{"frontend__src__x.txt": "fe v2\n"})
    assert W.deploy(s1) == 0
    assert root.stat().st_ino == ino and not root.is_symlink()
    assert not list(W.w.glob("opt/frontend.*"))
    assert (root / "index.html").read_text().endswith("fe v2\n")


def test_stale_static_mount_detected_and_rolled_back(W):
    stale = W.w / "stale_copy"
    (stale / "assets").mkdir(parents=True)
    for rel in ("index.html", "assets/app.js"):
        (stale / rel).write_text((W.w / "opt/frontend" / rel).read_text())
    (W.w / "stale_mount").write_text("")  # mount keeps serving the old tree
    before = W.snapshot()
    sha = W.commit("fe", **{"frontend__src__x.txt": "fe v2\n"})
    assert W.deploy(sha) == D.EXIT_ROLLED_BACK
    assert W.snapshot() == before
    assert json.loads(W.read("deploy/state/deployed.json"))["sha"] == W.base


# ---- rollback / recovery hardening ----
def test_sigterm_during_restart_rolls_back(W):
    before = W.snapshot()
    sha = W.commit("be", **{"backend__app__main.py": "# backend v2\n"})
    env = dict(os.environ, EPV3_DEPLOY_TEST_HOOKS="1", EPV3_DEPLOY_SIGTERM_AT="applied:backend")
    p = subprocess.run([sys.executable, str(SCRIPT), "--config", str(W.cfg_path), "--yes",
                        "deploy", "--sha", sha], env=env, capture_output=True)
    assert p.returncode == D.EXIT_ROLLED_BACK
    assert W.snapshot() == before and W.journal()["status"] == "rolled_back"
    assert W.restarts() == []  # no restart had been attempted -> none needed on rollback


def test_recover_restarts_only_units_actually_restarted(W):
    sha = W.commit("gw+be", **{"accurate-gateway__app__main.py": "# gateway v2\n",
                               "backend__app__main.py": "# backend v2\n"})
    env = dict(os.environ, EPV3_DEPLOY_TEST_HOOKS="1", EPV3_DEPLOY_CRASH_AT="healthy:gateway")
    subprocess.run([sys.executable, str(SCRIPT), "--config", str(W.cfg_path), "--yes", "deploy", "--sha", sha],
                   env=env, capture_output=True)
    assert W.journal()["status"] == "in_progress"
    assert W.restarts() == ["epv3-accurate-gateway"]
    assert W.run("recover", yes=True) == D.EXIT_ROLLED_BACK
    assert W.restarts() == ["epv3-accurate-gateway"] * 2  # backend never restarted, not restarted by recovery
    assert W.read("opt/gateway/app/main.py") == "# gateway v1\n"


def test_partial_apply_with_stray_temp_file_fully_restored(W, monkeypatch):
    before = W.snapshot()
    sha = W.commit("be", **{"backend__app__main.py": "# backend v2\n", "backend__app__util.py": "# u2\n"})
    orig = D.Runner.apply_code

    def partial(self, name, release, plan, bdir):
        orig(self, name, release, plan, bdir)
        (Path(self.comps[name]["dest"]) / "app/.util.py.epv3new").write_text("partial")
        raise D.DeployFailed("interrupted mid-apply")

    monkeypatch.setattr(D.Runner, "apply_code", partial)
    assert W.deploy(sha) == D.EXIT_ROLLED_BACK
    assert W.snapshot() == before


def test_second_restart_failure_during_rollback_is_rollback_failed_and_blocks(W):
    sha = W.commit("be", **{"backend__app__main.py": "# backend v2\n"})
    orig = D.Runner.restart_and_health
    calls = []

    def always_fail(self, name):
        calls.append(name)
        raise D.DeployFailed("restart failed")

    D.Runner.restart_and_health = always_fail
    try:
        assert W.deploy(sha) == D.EXIT_ROLLBACK_FAILED
    finally:
        D.Runner.restart_and_health = orig
    assert W.read("opt/backend/app/main.py") == "# backend v1\n"  # code restored even though restart failed
    assert W.journal()["status"] == "rollback_failed" and len(calls) == 2
    assert W.deploy(sha) == D.EXIT_UNFINISHED
    assert W.run("recover", yes=True) == D.EXIT_ROLLED_BACK  # operator retry after fixing the unit


# ---- installer fail-closed ----
INSTALL = SCRIPT.parent / "install.sh"


def _install(prefix, *args, env_extra=None):
    env = dict(os.environ, EPV3_DEPLOY_PREFIX=str(prefix), EPV3_DEPLOY_ALLOW_PREFIX="1", **(env_extra or {}))
    return subprocess.run(["bash", str(INSTALL), *args], env=env, capture_output=True, text=True)


def test_installer_fails_closed_without_prepared_config(W, tmp_path):
    pref = tmp_path / "pfx"
    r = _install(pref, "--apply")
    assert r.returncode != 0 and not pref.exists()
    ex = SCRIPT.parent / "deploy.conf.example.json"
    r = _install(pref, "--apply", "--config", str(ex))
    assert r.returncode != 0 and not pref.exists()  # example is never a live config
    bad = dict(W.cfg, components={})
    (tmp_path / "bad.json").write_text(json.dumps(bad))
    r = _install(pref, "--apply", "--config", str(tmp_path / "bad.json"))
    assert r.returncode != 0 and not pref.exists()


def test_installer_dry_run_then_apply_keeps_existing_config(W, tmp_path):
    pref = tmp_path / "pfx"
    r = _install(pref, "--config", str(W.cfg_path))
    assert r.returncode == 0 and "DRY-RUN" in r.stdout and not pref.exists()
    r = _install(pref, "--apply", "--config", str(W.cfg_path))
    assert r.returncode == 0, r.stderr + r.stdout
    assert (pref / "bin/epv3-deploy").is_file() and (pref / "deploy.conf.json").is_file()
    assert not (pref / "keys").exists()
    (pref / "deploy.conf.json").write_text(W.cfg_path.read_text() + " ")
    r = _install(pref, "--apply", "--config", str(W.cfg_path))
    assert r.returncode == 0 and (pref / "deploy.conf.json").read_text().endswith(" ")


def test_example_config_matches_vps_facts_but_is_not_live_valid():
    cfg = json.loads((SCRIPT.parent / "deploy.conf.example.json").read_text())
    assert cfg["ssh_key"] == "/home/eternaladmin/.ssh/epv3_github"
    c = cfg["components"]
    assert c["frontend"]["dest"] == "/opt/epv3/frontend-staging"
    assert c["frontend"]["verify_base"] == "http://127.0.0.1:8180"
    assert c["backend"]["health_url"] == "http://127.0.0.1:8100/api/v1/health"
    assert c["gateway"]["health_url"] == "http://127.0.0.1:8091/health"
    assert "eternal_production_v3" in json.dumps(cfg["commands"]["db_revision"])
    assert "alembic_upgrade" not in cfg["commands"] and cfg["migrations"]["enabled"] is False
    assert D.validate_config(cfg)
