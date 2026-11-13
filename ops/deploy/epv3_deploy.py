#!/usr/bin/env python3
"""Eternal Production V3 dedicated deploy runner (stdlib only, on-demand CLI, no daemon).

Deploys one exact, CI-green GitHub SHA that is an ancestor of main.
Exit codes: 0 ok/dry-run, 2 refused (nothing mutated), 3 failed and rolled back,
4 rollback failed (manual intervention), 5 unfinished journal.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
EXIT_OK, EXIT_REFUSED, EXIT_ROLLED_BACK, EXIT_ROLLBACK_FAILED, EXIT_UNFINISHED = 0, 2, 3, 4, 5

DEFAULT_WORKFLOW = ".github/workflows/ci.yml"
DEFAULT_CI = [
    "Backend (Postgres + Pytest + Alembic)",
    "Accurate Gateway (fixture mode)",
    "Frontend (build + tests)",
]
APPLY_ORDER = ["gateway", "backend", "frontend"]
DEP_FILES = {"backend": ["requirements.txt", "requirements.lock.txt"], "gateway": ["requirements.txt"]}
# Path prefixes (relative to component dir) that never require a restart.
NO_RESTART_PREFIXES = ("tests/", "README", "docs/")


class Refused(Exception):
    pass


class DeployFailed(Exception):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def now_us() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def log(msg: str) -> None:
    print(f"[epv3-deploy] {msg}", flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def atomic_write(path: Path, data: str | bytes, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "wb") as f:
        f.write(data.encode() if isinstance(data, str) else data)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, path)


REQUIRED_COMMANDS = ["restart", "pg_dump", "pg_restore_list", "frontend_build", "db_revision"]


def validate_config(cfg: dict) -> list[str]:
    """Fail-closed validation: returns list of problems (empty = usable live config)."""
    errs: list[str] = []
    if "REPLACE_ME" in json.dumps(cfg):
        errs.append("config still contains REPLACE_ME placeholders")
    for k in ("repo_url", "github_repo", "root", "backup_dir", "components", "commands"):
        if not cfg.get(k):
            errs.append(f"missing key: {k}")
    if errs:
        return errs
    for c in REQUIRED_COMMANDS:
        if not cfg["commands"].get(c):
            errs.append(f"missing command: {c}")
    if cfg.get("ssh_key") and not Path(cfg["ssh_key"]).is_file():
        errs.append(f"ssh_key not found: {cfg['ssh_key']}")
    ci = cfg.get("ci", {})
    if not (ci.get("token_file") and Path(ci["token_file"]).is_file()):
        errs.append("ci.token_file missing/not found")
    for name in APPLY_ORDER:
        c = cfg["components"].get(name)
        if not c:
            errs.append(f"missing component: {name}")
            continue
        for k in ("src", "dest") + (("unit", "health_url") if name != "frontend" else ("verify_base",)):
            if not c.get(k):
                errs.append(f"component {name}: missing {k}")
        if c.get("dest") and not Path(c["dest"]).is_dir():
            errs.append(f"component {name}: dest is not an existing directory (real dir required): {c['dest']}")
        if c.get("dest") and Path(c["dest"]).is_symlink():
            errs.append(f"component {name}: dest must not be a symlink")
    if not Path(cfg["backup_dir"]).is_dir():
        errs.append(f"backup_dir not found: {cfg['backup_dir']}")
    return errs


class Runner:
    def __init__(self, cfg: dict, yes: bool = False):
        self.cfg = cfg
        self.yes = yes
        self.root = Path(cfg["root"])
        self.state = self.root / "state"
        self.mirror = self.root / "source" / "mirror.git"
        self.releases = self.root / "source" / "releases"
        self.artifacts = self.root / "artifacts"
        self.backups = Path(cfg["backup_dir"])
        self.comps = cfg["components"]
        self.cmds = cfg["commands"]
        self.hooks = os.environ.get("EPV3_DEPLOY_TEST_HOOKS") == "1"
        self.cur: dict = {}
        self._lock_fh = None

    # ---------- infra ----------
    def run(self, cmd, cwd=None, env=None, check=True, timeout=1800, capture=True, input_=None):
        e = dict(os.environ)
        e.update(env or {})
        p = subprocess.run([str(c) for c in cmd], cwd=cwd, env=e, capture_output=capture,
                           timeout=timeout, input=input_)
        if check and p.returncode != 0:
            err = (p.stderr or b"").decode(errors="replace")[-800:]
            raise DeployFailed(f"command failed ({p.returncode}): {' '.join(map(str, cmd))}: {err}")
        return p

    def fmt(self, key: str, **kw) -> list[str]:
        return [str(a).format(**kw) for a in self.cmds[key]]

    def git(self, *args, check=True, input_=None) -> subprocess.CompletedProcess:
        env = {"GIT_TERMINAL_PROMPT": "0"}
        if self.cfg.get("ssh_key"):
            env["GIT_SSH_COMMAND"] = (f"ssh -i {self.cfg['ssh_key']} -o IdentitiesOnly=yes "
                                      "-o StrictHostKeyChecking=yes -o BatchMode=yes")
        return self.run(["git", f"--git-dir={self.mirror}", *args], env=env, check=check, input_=input_)

    @contextlib.contextmanager
    def lock(self):
        self.state.mkdir(parents=True, exist_ok=True)
        fh = open(self.state / "deploy.lock", "a+")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.close()
            raise Refused("another deploy/recover holds the lock")
        fh.seek(0)
        fh.truncate()
        fh.write(f"pid={os.getpid()} since={now()}\n")
        fh.flush()
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
            fh.close()

    def save(self, **upd) -> None:
        self.cur.update(upd)
        self.cur["updated"] = now()
        atomic_write(self.state / "current.json", json.dumps(self.cur, indent=1))
        with open(self.state / "journal.log", "a") as f:
            f.write(json.dumps({"t": self.cur["updated"], "id": self.cur.get("id"),
                                **{k: v for k, v in upd.items()}}) + "\n")

    def phase(self, name: str) -> None:
        log(f"phase: {name}")
        self.save(phase=name)
        if self.hooks and os.environ.get("EPV3_DEPLOY_CRASH_AT") == name:
            os._exit(137)
        if self.hooks and os.environ.get("EPV3_DEPLOY_SIGTERM_AT") == name:
            os.kill(os.getpid(), signal.SIGTERM)

    def load_current(self) -> dict:
        p = self.state / "current.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def deployed_sha(self) -> str:
        p = self.state / "deployed.json"
        if not p.exists():
            raise Refused("no baseline: run `init-baseline --sha <currently deployed sha>` first")
        return json.loads(p.read_text())["sha"]

    # ---------- source ----------
    def fetch(self) -> None:
        if not self.mirror.exists():
            self.mirror.parent.mkdir(parents=True, exist_ok=True)
            env = {}
            if self.cfg.get("ssh_key"):
                env["GIT_SSH_COMMAND"] = (f"ssh -i {self.cfg['ssh_key']} -o IdentitiesOnly=yes "
                                          "-o StrictHostKeyChecking=yes -o BatchMode=yes")
            self.run(["git", "clone", "--mirror", self.cfg["repo_url"], self.mirror], env=env)
        else:
            self.git("remote", "update", "--prune")

    def validate_sha(self, sha: str) -> None:
        if not SHA_RE.match(sha or ""):
            raise Refused("SHA must be the full 40-hex lowercase commit id (no branch/short/tag)")
        p = self.git("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}", check=False)
        if p.returncode != 0 or p.stdout.decode().strip() != sha:
            raise Refused(f"commit {sha} not found in mirror")
        main = self.cfg.get("main_ref", "main")
        if self.git("merge-base", "--is-ancestor", sha, f"refs/heads/{main}", check=False).returncode != 0:
            raise Refused(f"{sha} is not an ancestor of {main}")

    def check_ci(self, sha: str) -> None:
        """Fail-closed CI gate via GitHub Actions REST API (Actions: read-only permission)."""
        ci = self.cfg.get("ci", {})
        try:
            token = Path(ci["token_file"]).read_text().strip()
        except (KeyError, OSError):
            raise Refused("CI verification unavailable: token file unreadable")
        if not token:
            raise Refused("CI verification unavailable: empty token")
        verify_ci_actions(
            lambda path: github_get(ci.get("api_base", "https://api.github.com"), path, token),
            self.cfg["github_repo"], sha, ci.get("required", DEFAULT_CI),
            ci.get("workflow_path", DEFAULT_WORKFLOW), int(ci.get("per_page", 100)))

    def tree(self, sha: str, sub: str) -> dict[str, str]:
        out = self.git("ls-tree", "-r", "-z", sha, "--", f"{sub}/").stdout.decode()
        res = {}
        for ent in filter(None, out.split("\0")):
            meta, path = ent.split("\t", 1)
            mode, typ, blob = meta.split()
            if mode == "120000":
                raise Refused(f"symlink in tree not supported: {path}")
            res[path[len(sub) + 1:]] = blob
        return res

    def extract(self, sha: str) -> Path:
        dest = self.releases / sha
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        arch = self.git("archive", "--format=tar", sha).stdout
        with tarfile.open(fileobj=io.BytesIO(arch)) as t:
            t.extractall(dest, filter="data")
        return dest

    # ---------- classification ----------
    def classify(self, old: str, new: str) -> dict:
        res = {"components": [], "restart": [], "blockers": [], "changes": {}, "migration": False, "target_head": None}
        for name, c in self.comps.items():
            src = c["src"]
            o, n = self.tree(old, src), self.tree(new, src)
            changed = sorted(p for p in set(o) | set(n) if o.get(p) != n.get(p))
            res["changes"][name] = changed
            if not changed:
                continue
            if name in DEP_FILES and any(p in changed for p in DEP_FILES[name]):
                res["blockers"].append(f"{name}: dependency files changed; needs Owner-approved venv step")
            if name == "backend" and any(p.startswith("alembic/versions/") for p in changed):
                res["migration"] = True
            res["components"].append(name)
            if not all(p.startswith(NO_RESTART_PREFIXES) for p in changed):
                res["restart"].append(name)
        proxy = self.tree(old, "staging-proxy"), self.tree(new, "staging-proxy")
        if any(proxy[0].get(p) != proxy[1].get(p) for p in set(proxy[0]) | set(proxy[1])
               if not p.startswith("tests/")):
            res["blockers"].append("staging-proxy changed; not managed by runner (Owner-approved manual step)")
        if res["migration"]:
            res["target_head"] = self.alembic_head(new)
        res["components"].sort(key=APPLY_ORDER.index)
        res["restart"].sort(key=APPLY_ORDER.index)
        return res

    def alembic_head(self, sha: str) -> str:
        files = self.tree(sha, "backend/alembic/versions")
        revs, downs = {}, set()
        for path, blob in files.items():
            if not path.endswith(".py"):
                continue
            txt = self.git("cat-file", "blob", blob).stdout.decode()
            r = re.search(r"^revision(?:\s*:\s*\w+)?\s*=\s*['\"]([^'\"]+)['\"]", txt, re.M)
            d = re.search(r"^down_revision[^=]*=\s*(.+)$", txt, re.M)
            if r:
                revs[r.group(1)] = path
                downs.update(re.findall(r"['\"]([^'\"]+)['\"]", d.group(1)) if d else [])
        heads = [r for r in revs if r not in downs]
        if len(heads) != 1:
            raise Refused(f"expected single alembic head, found {heads}")
        return heads[0]

    def verify_db_revision(self, head: str, migration_pending: bool = False) -> None:
        """Read-only: live alembic_version must be exactly the single head of the target tree."""
        p = self.run(self.fmt("db_revision"), check=False)
        rows = [r.strip() for r in p.stdout.decode().splitlines() if r.strip()]
        if p.returncode != 0 or len(rows) != 1:
            raise Refused("cannot verify DB revision safely (command failed or not exactly one alembic_version row)")
        if rows[0] != head:
            hint = " (run the separately approved `migrate` first)" if migration_pending else ""
            raise Refused(f"DB revision {rows[0]} != target head {head}; deploy never migrates{hint}")

    # ---------- build ----------
    def build(self, sha: str, release: Path, plan: dict) -> Path | None:
        for name in plan["components"]:
            if name in ("backend", "gateway"):
                d = release / self.comps[name]["src"]
                self.run([sys.executable, "-m", "compileall", "-q", d])
        if "frontend" not in plan["components"]:
            return None
        tree_id = self.git("rev-parse", f"{sha}:{self.comps['frontend']['src']}").stdout.decode().strip()
        art = self.artifacts / "frontend" / tree_id
        if self.artifact_valid(art):
            log(f"reusing valid frontend artifact {tree_id[:12]}")
            return art / "dist"
        shutil.rmtree(art, ignore_errors=True)
        art.mkdir(parents=True)
        src = release / self.comps["frontend"]["src"]
        self.run(self.fmt("frontend_build"), cwd=src, timeout=3600,
                 env={"VITE_API_BASE_URL": "/api/v1", "CI": "1"})
        dist = src / "dist"
        if not (dist / "index.html").is_file():
            raise DeployFailed("frontend build produced no dist/index.html")
        shutil.copytree(dist, art / "dist")
        manifest = dir_manifest(art / "dist")
        atomic_write(art / "MANIFEST.json", json.dumps(manifest, indent=1))
        atomic_write(art / "VALID", tree_id)
        return art / "dist"

    @staticmethod
    def artifact_valid(art: Path) -> bool:
        if not (art / "VALID").exists() or not (art / "MANIFEST.json").exists():
            return False
        try:
            return json.loads((art / "MANIFEST.json").read_text()) == dir_manifest(art / "dist")
        except Exception:
            return False

    # ---------- backup ----------
    def touched(self, name: str, plan: dict, dist: Path | None) -> list[str]:
        if name != "frontend":
            return plan["changes"][name]
        prev = self.deployed_manifest()
        return sorted(set(dir_manifest(dist)) | set(prev))

    def deployed_manifest(self) -> dict[str, str]:
        p = self.state / "deployed.json"
        return json.loads(p.read_text()).get("frontend_manifest", {}) if p.exists() else {}

    def backup(self, sha: str, plan: dict, old: str, dist: Path | None = None) -> Path:
        bdir = self.backups / f"deploy-{now_us()}-{sha[:12]}"
        bdir.mkdir(parents=True)
        self.save(backup=str(bdir))
        if self.cfg.get("db_backup", True):
            dump = bdir / "db.dump"
            self.dump_db(dump)
            if not dump.exists() or dump.stat().st_size == 0:
                raise DeployFailed("db dump empty")
            self.run(self.fmt("pg_restore_list", dump=dump))
        for name in plan["components"]:
            dest = Path(self.comps[name]["dest"])
            changed = self.touched(name, plan, dist)
            existing = [p for p in changed if (dest / p).is_file()]
            with tarfile.open(bdir / f"{name}.tar.gz", "w:gz") as t:
                for p in existing:
                    t.add(dest / p, arcname=p)
            atomic_write(bdir / f"{name}.plan.json", json.dumps({
                "restore": existing, "created": [p for p in changed if p not in existing]}))
        lines = [f"{sha256_file(f)}  {f.name}" for f in sorted(bdir.iterdir()) if f.is_file()
                 and f.name != "SHA256SUMS"]
        atomic_write(bdir / "SHA256SUMS", "\n".join(lines) + "\n")
        verify_checksums(bdir)
        return bdir

    def dump_db(self, dump: Path) -> None:
        if self.cfg.get("pg_dump_to_stdout"):
            data = self.run(self.fmt("pg_dump", out=dump), timeout=3600).stdout
            atomic_write(dump, data, 0o600)
        else:
            self.run(self.fmt("pg_dump", out=dump), timeout=3600)

    def prune_backups(self) -> None:
        keep = int(self.cfg.get("keep_backups", 10))
        protect = self.cur.get("backup")
        dirs = sorted(d for d in self.backups.glob("deploy-*") if d.is_dir())
        for d in dirs[:-keep] if keep > 0 else []:
            if str(d) != protect:
                shutil.rmtree(d, ignore_errors=True)

    # ---------- apply / rollback ----------
    def apply_code(self, name: str, release: Path, plan: dict, bdir: Path) -> None:
        dest = Path(self.comps[name]["dest"])
        src = release / self.comps[name]["src"]
        for p in plan["changes"][name]:
            s, d = src / p, dest / p
            if s.is_file():
                d.parent.mkdir(parents=True, exist_ok=True)
                tmp = d.with_name(f".{d.name}.epv3new")
                shutil.copy2(s, tmp)
                os.replace(tmp, d)
            elif d.is_file():
                d.unlink()

    def apply_frontend(self, dist: Path) -> None:
        """In-place update of the mounted root: the directory (inode/path) the proxy mount holds never changes.
        Hashed assets first, index.html last, then stale files from the previous deployed manifest."""
        root = Path(self.comps["frontend"]["dest"])
        new = dir_manifest(dist)
        for rel in sorted(new, key=lambda r: (r == "index.html", r)):
            d = root / rel
            d.parent.mkdir(parents=True, exist_ok=True)
            tmp = d.with_name(f".{d.name}.epv3new")
            shutil.copy2(dist / rel, tmp)
            os.replace(tmp, d)
        for rel in self.deployed_manifest():
            if rel not in new:
                (root / rel).unlink(missing_ok=True)

    def rollback(self) -> None:
        cur = self.cur
        bdir = Path(cur["backup"]) if cur.get("backup") else None
        touched = cur.get("applied", [])
        for name in reversed(touched):
            self.rollback_code(name, bdir)
        errors = []
        for name in touched:
            if name in cur.get("restart_attempted", []):
                try:
                    self.restart_and_health(name)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{name}: {e}")
        if errors:
            raise DeployFailed("post-rollback restart/health failed: " + "; ".join(errors))

    def rollback_code(self, name: str, bdir: Path) -> None:
        dest = Path(self.comps[name]["dest"])
        plan = json.loads((bdir / f"{name}.plan.json").read_text())
        verify_checksums(bdir)
        for p in plan["created"] + plan["restore"]:
            (dest / p).with_name(f".{Path(p).name}.epv3new").unlink(missing_ok=True)
        for p in plan["created"]:
            (dest / p).unlink(missing_ok=True)
        with tarfile.open(bdir / f"{name}.tar.gz") as t:
            for m in t.getmembers():
                target = dest / m.name
                target.parent.mkdir(parents=True, exist_ok=True)
                f = t.extractfile(m)
                tmp = target.with_name(f".{target.name}.epv3rb")
                tmp.write_bytes(f.read())
                os.chmod(tmp, m.mode & 0o7777)
                os.replace(tmp, target)

    def restart_and_health(self, name: str) -> None:
        c = self.comps[name]
        self.run(self.fmt("restart", unit=c["unit"]), timeout=120)
        wait_http(c["health_url"], int(self.cfg.get("health_timeout", 45)))

    # ---------- verify ----------
    def verify_frontend(self, dist: Path) -> None:
        """Through the proxy mount actually running: every artifact file must be served byte-identical."""
        base = self.comps["frontend"]["verify_base"].rstrip("/")
        t = int(self.cfg.get("health_timeout", 45))
        for rel, h in dir_manifest(dist).items():
            url = f"{base}/" if rel == "index.html" else f"{base}/{rel}"
            body = http_get(url, t if rel == "index.html" else int(self.cfg.get("asset_timeout", 15)))
            if hashlib.sha256(body).hexdigest() != h:
                raise DeployFailed(f"proxy serves stale/different content for {rel}")
            if rel == "index.html":
                for ref in sorted(set(re.findall(rb'(?:src|href)="/(assets/[^"]+)"', body))):
                    if ref.decode() not in dir_manifest(dist):
                        raise DeployFailed(f"index.html references {ref.decode()} missing from artifact")

    # ---------- commands ----------
    def deploy(self, sha: str) -> int:
        with self.lock():
            cur = self.load_current()
            if cur.get("status") in ("in_progress", "rollback_failed"):
                log(f"unfinished journal ({cur.get('status')}, id={cur.get('id')}); run `recover`")
                return EXIT_UNFINISHED
            try:
                old = self.deployed_sha()
                self.fetch()
                self.validate_sha(sha)
                self.check_ci(sha)
                plan = self.classify(old, sha)
                if plan["blockers"]:
                    raise Refused("; ".join(plan["blockers"]))
                self.verify_db_revision(plan["target_head"] or self.alembic_head(sha), plan["migration"])
                self.check_drift(old, sha, plan)
            except Refused as e:
                log(f"REFUSED: {e}")
                return EXIT_REFUSED
            summary = {k: plan[k] for k in ("components", "restart", "migration")}
            log(f"plan {old[:12]} -> {sha[:12]}: {json.dumps(summary)}")
            if not plan["components"]:
                if self.yes:
                    atomic_write(self.state / "deployed.json", json.dumps(
                        {"sha": sha, "at": now(), "prev": old, "frontend_manifest": self.deployed_manifest()}))
                log("no deployable component change" + ("; baseline advanced" if self.yes else ""))
                return EXIT_OK
            if not self.yes:
                log("DRY-RUN (no --yes): nothing changed")
                return EXIT_OK

            self.cur = {"id": f"{now()}-{sha[:12]}", "sha": sha, "prev_sha": old, "status": "in_progress",
                        "applied": [], "components": plan["components"]}
            self.save(phase="start")
            try:
                self.phase("build")
                release = self.extract(sha)
                dist = self.build(sha, release, plan)
                self.phase("backup")
                bdir = self.backup(sha, plan, old, dist)
                self.phase("apply")
                for name in plan["components"]:
                    self.save(applied=self.cur["applied"] + [name])
                    if name == "frontend":
                        self.apply_frontend(dist)
                    else:
                        self.apply_code(name, release, plan, bdir)
                    self.phase(f"applied:{name}")
                self.phase("restart")
                for name in plan["restart"]:
                    if name != "frontend":
                        self.save(restart_attempted=self.cur.get("restart_attempted", []) + [name])
                        self.restart_and_health(name)
                        self.phase(f"healthy:{name}")
                self.phase("verify")
                if "frontend" in plan["components"]:
                    self.verify_frontend(dist)
                if self.cfg.get("proxy_health_url") and set(plan["restart"]) - {"frontend"}:
                    wait_http(self.cfg["proxy_health_url"], int(self.cfg.get("health_timeout", 45)))
            except BaseException as e:
                log(f"FAILURE ({type(e).__name__}: {e}); rolling back")
                return self.finish_rollback(str(e))
            fm = dir_manifest(dist) if "frontend" in plan["components"] else self.deployed_manifest()
            atomic_write(self.state / "deployed.json", json.dumps(
                {"sha": sha, "at": now(), "prev": old, "frontend_manifest": fm}))
            self.save(status="success", phase="done")
            self.prune_backups()
            log(f"SUCCESS {sha}")
            return EXIT_OK

    def finish_rollback(self, reason: str) -> int:
        try:
            self.phase("rollback")
            self.rollback()
            self.save(status="rolled_back", reason=reason)
            log("rollback complete; code restored to previous SHA")
            return EXIT_ROLLED_BACK
        except BaseException as e:
            self.save(status="rollback_failed", reason=f"{reason} | rollback: {e}")
            log(f"ROLLBACK FAILED: {e}")
            return EXIT_ROLLBACK_FAILED

    def recover(self) -> int:
        with self.lock():
            self.cur = self.load_current()
            st = self.cur.get("status")
            if st not in ("in_progress", "rollback_failed"):
                log(f"nothing to recover (status={st})")
                return EXIT_OK
            if not self.yes:
                log(f"DRY-RUN: would roll back journal {self.cur.get('id')} (phase {self.cur.get('phase')})")
                return EXIT_OK
            return self.finish_rollback(f"recovery of interrupted deploy (phase {self.cur.get('phase')})")

    def check_drift(self, old: str, new: str, plan: dict) -> None:
        """Live files must equal the recorded baseline. No override: reconcile, then `init-baseline`."""
        bad = []
        for name in plan["components"]:
            dest = Path(self.comps[name]["dest"])
            if name == "frontend":
                prev = self.deployed_manifest()
                if not prev:
                    raise Refused("no frontend baseline manifest; reconcile and run `init-baseline`")
                bad += [f"frontend/{r}" for r, h in prev.items()
                        if not (dest / r).is_file() or sha256_file(dest / r) != h]
                continue
            o, n = self.tree(old, self.comps[name]["src"]), self.tree(new, self.comps[name]["src"])
            for p in plan["changes"][name]:
                f = dest / p
                if not f.is_file():
                    if p in o and not p.startswith(NO_RESTART_PREFIXES):
                        bad.append(f"{name}/{p} (missing)")
                elif git_blob_id(f.read_bytes()) not in (o.get(p), n.get(p)):
                    bad.append(f"{name}/{p}")
        if bad:
            raise Refused(f"DRIFT STOP: live files differ from baseline {old[:12]}: {bad[:10]}; reconcile local "
                          "changes with Owner, then re-run `init-baseline`")

    def baseline_mismatches(self, sha: str) -> list[str]:
        bad = []
        for name in ("backend", "gateway"):
            dest = Path(self.comps[name]["dest"])
            for p, blob in self.tree(sha, self.comps[name]["src"]).items():
                if p.startswith(NO_RESTART_PREFIXES):
                    continue
                f = dest / p
                if not f.is_file() or git_blob_id(f.read_bytes()) != blob:
                    bad.append(f"{name}/{p}")
        return bad

    def init_baseline(self, sha: str) -> int:
        with self.lock():
            self.fetch()
            if not SHA_RE.match(sha):
                raise Refused("full SHA required")
            self.git("rev-parse", "--verify", f"{sha}^{{commit}}")
            bad = self.baseline_mismatches(sha)
            if bad:
                raise Refused(f"DRIFT STOP: live runtime does not match {sha[:12]}: {bad[:10]}")
            self.verify_db_revision(self.alembic_head(sha))
            fe = Path(self.comps["frontend"]["dest"])
            if not (fe / "index.html").is_file():
                raise Refused("frontend root has no index.html")
            if not self.yes:
                log(f"DRY-RUN: would record baseline {sha}")
                return EXIT_OK
            atomic_write(self.state / "deployed.json", json.dumps(
                {"sha": sha, "at": now(), "baseline": True, "frontend_manifest": dir_manifest(fe)}))
            return EXIT_OK

    def migrate(self, sha: str, approval: str) -> int:
        """Separate, explicitly approved DB migration. Never invoked by `deploy`."""
        with self.lock():
            cur = self.load_current()
            if cur.get("status") in ("in_progress", "rollback_failed"):
                log("unfinished journal; run `recover`")
                return EXIT_UNFINISHED
            try:
                if not self.cfg.get("migrations", {}).get("enabled", False):
                    raise Refused("migrations disabled in config (default)")
                if not self.cmds.get("alembic_upgrade"):
                    raise Refused("no migration executor configured (commands.alembic_upgrade)")
                a = json.loads(Path(approval).read_text())
                exp = dt.datetime.fromisoformat(a["expires"].replace("Z", "+00:00"))
                if a.get("sha") != sha or a.get("action") != "alembic_upgrade" or not a.get("approved_by"):
                    raise Refused("approval file does not match sha/action/approver")
                if exp < dt.datetime.now(dt.timezone.utc):
                    raise Refused("approval expired")
                self.fetch()
                self.validate_sha(sha)
                self.check_ci(sha)
            except (Refused, KeyError, ValueError, OSError) as e:
                log(f"REFUSED: {e}")
                return EXIT_REFUSED
            if not self.yes:
                log("DRY-RUN: migration approved but --yes missing")
                return EXIT_OK
            self.cur = {"id": f"{now()}-migrate-{sha[:12]}", "sha": sha, "status": "in_progress", "kind": "migrate"}
            self.save(phase="migrate-backup")
            try:
                release = self.extract(sha)
                bdir = self.backups / f"deploy-{now_us()}-migrate-{sha[:12]}"
                bdir.mkdir(parents=True)
                self.save(backup=str(bdir))
                dump = bdir / "db.dump"
                self.dump_db(dump)
                self.run(self.fmt("pg_restore_list", dump=dump))
                atomic_write(bdir / "SHA256SUMS", f"{sha256_file(dump)}  db.dump\n")
                verify_checksums(bdir)
                self.phase("migrate-run")
                self.run(self.fmt("alembic_upgrade", cwd=release / "backend"), timeout=3600)
                self.verify_db_revision(self.alembic_head(sha))
            except BaseException as e:
                self.save(status="migrate_failed", reason=str(e))
                log(f"MIGRATION FAILED: {e}. DB NOT auto-restored; restore from {self.cur.get('backup')} "
                    "only with Owner approval")
                return EXIT_ROLLBACK_FAILED
            self.save(status="success", phase="done")
            return EXIT_OK

    def status(self) -> int:
        cur = self.load_current()
        dep = (self.state / "deployed.json")
        print(json.dumps({"deployed": json.loads(dep.read_text()) if dep.exists() else None,
                          "last_journal": cur}, indent=1))
        return EXIT_OK


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def github_get(base: str, path: str, token: str) -> dict:
    """GET JSON from the GitHub API. Any failure -> Refused (never bypass CI); token never in messages."""
    base = base.rstrip("/")
    if not (base.startswith("https://") or base.startswith(("http://127.0.0.1", "http://localhost"))):
        raise Refused("CI verification unavailable: api_base must be https")
    req = urllib.request.Request(base + path, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "epv3-deploy"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise Refused(f"CI verification unavailable: GitHub API HTTP {e.code}") from None
    except Exception as e:  # noqa: BLE001
        raise Refused(f"CI verification unavailable: {type(e).__name__}") from None


def _paged(get, path: str, key: str, per_page: int, max_pages: int = 20) -> list[dict]:
    items: list[dict] = []
    total = None
    for page in range(1, max_pages + 1):
        data = get(f"{path}{'&' if '?' in path else '?'}per_page={per_page}&page={page}")
        batch = data.get(key)
        if not isinstance(batch, list) or not isinstance(data.get("total_count"), int):
            raise Refused("CI verification unavailable: malformed API response")
        total = data["total_count"]
        items += batch
        if len(items) >= total or not batch:
            break
    if len(items) != total:
        raise Refused("CI verification unavailable: incomplete pagination")
    return items


def verify_ci_actions(get, repo: str, sha: str, required: list[str], workflow_path: str,
                      per_page: int = 100) -> None:
    """Every official CI run for exactly `sha` must be completed/success with all required jobs
    (latest attempt) completed/success, each job name exactly once."""
    if not SHA_RE.match(sha):
        raise Refused("CI check needs full 40-hex SHA")
    runs = _paged(get, f"/repos/{repo}/actions/runs?head_sha={sha}", "workflow_runs", per_page)
    official, seen = [], set()
    for r in runs:
        if r.get("id") in seen:
            continue
        seen.add(r.get("id"))
        if (r.get("head_sha") == sha
                and (r.get("repository") or {}).get("full_name") == repo
                and (r.get("head_repository") or {}).get("full_name") == repo
                and str(r.get("path", "")).split("@")[0] == workflow_path):
            official.append(r)
    if not official:
        raise Refused(f"CI not verified for {sha[:12]}: no official workflow run on exact SHA")
    for r in official:
        if r.get("status") != "completed" or r.get("conclusion") != "success":
            raise Refused(f"CI not green for {sha[:12]}: run {r.get('id')} "
                          f"{r.get('conclusion') or r.get('status')}")
        jobs = _paged(get, f"/repos/{repo}/actions/runs/{r['id']}/jobs?filter=latest", "jobs", per_page)
        for name in required:
            same = [j for j in jobs if j.get("name") == name]
            if len(same) != 1:
                raise Refused(f"CI not verified for {sha[:12]}: job '{name}' "
                              f"{'missing' if not same else 'duplicated'} in run {r['id']}")
            j = same[0]
            if j.get("head_sha") != sha or j.get("run_attempt") != r.get("run_attempt"):
                raise Refused(f"CI not verified for {sha[:12]}: job '{name}' sha/attempt mismatch")
            if j.get("status") != "completed" or j.get("conclusion") != "success":
                raise Refused(f"CI not green for {sha[:12]}: {name} -> "
                              f"{j.get('conclusion') or j.get('status')}")


def dir_manifest(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): sha256_file(p) for p in sorted(root.rglob("*")) if p.is_file()}


def verify_checksums(bdir: Path) -> None:
    for line in (bdir / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if sha256_file(bdir / name) != digest:
            raise DeployFailed(f"backup checksum mismatch: {name}")


def http_get(url: str, timeout: int) -> bytes:
    deadline = time.time() + timeout
    last = None
    while True:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    return r.read()
                last = f"HTTP {r.status}"
        except Exception as e:  # noqa: BLE001
            last = str(e)
        if time.time() >= deadline:
            raise DeployFailed(f"{url} not healthy: {last}")
        time.sleep(0.5)


def wait_http(url: str, timeout: int) -> None:
    http_get(url, timeout)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="epv3-deploy")
    ap.add_argument("--config", default=os.environ.get("EPV3_DEPLOY_CONFIG", "/opt/epv3/deploy/deploy.conf.json"))
    ap.add_argument("--yes", action="store_true", help="execute (default is dry-run)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("plan", "deploy", "init-baseline", "migrate"):
        p = sub.add_parser(n)
        p.add_argument("--sha", required=True)
        if n == "migrate":
            p.add_argument("--approval-file", required=True)
    sub.add_parser("validate-config")
    sub.add_parser("recover")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    try:
        cfg = json.loads(Path(a.config).read_text())
    except (OSError, ValueError) as e:
        log(f"REFUSED: cannot read config {a.config}: {e}")
        return EXIT_REFUSED
    errs = validate_config(cfg)
    if a.cmd == "validate-config" or errs:
        for e in errs:
            log(f"CONFIG: {e}")
        log("config OK" if not errs else "REFUSED: config not usable")
        return EXIT_REFUSED if errs else EXIT_OK
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt("SIGTERM")))
    r = Runner(cfg, yes=a.yes and a.cmd != "plan")
    try:
        if a.cmd in ("plan", "deploy"):
            return r.deploy(a.sha)
        if a.cmd == "init-baseline":
            return r.init_baseline(a.sha)
        if a.cmd == "migrate":
            return r.migrate(a.sha, a.approval_file)
        if a.cmd == "recover":
            return r.recover()
        return r.status()
    except Refused as e:
        log(f"REFUSED: {e}")
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
