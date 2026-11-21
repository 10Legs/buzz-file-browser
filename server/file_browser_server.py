#!/usr/bin/env python3
"""file_browser_server — read-only file listing and download for the Buzz "File browser" plugin.

Standard library only. Config comes from a JSON file (see config.example.json):
  FILE_BROWSER_CONFIG=/path/to/config.json python3 file_browser_server.py

Every request needs `Authorization: Bearer <token>`. Only the configured roots are reachable. Secret-looking
files and symlinks that leave a root are hidden and refused.

  GET /roots                       configured roots
  GET /list?root=<i>&path=<rel>    directory entries
  GET /file?root=<i>&path=<rel>    {name,size,mime,data(base64)}, size-capped
  GET /uploads?limit=<n>           optional: Buzz relay media metadata (needs "uploads" in the config)
"""
import base64, fnmatch, hmac, json, mimetypes, os, subprocess, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# Matched case-insensitively against every path component. A match makes the entry invisible and undownloadable.
DENY_NAMES = [".env", ".env.*", "*.env", "*.env.*", "*.key", "*.pem", "*.p12", "*.pfx", "*.authtag", "*.token", "secrets", ".ssh", ".gnupg",
              "auth.json", ".netrc", ".npmrc", ".pypirc", "id_rsa*", "id_ed25519*", "credentials*", "private-key*"]
DENY_SUFFIXES = [".git/config", ".git/credentials"]


def denied(path, extra_names=()):
    parts = [p.lower() for p in path.split(os.sep) if p]
    if any(fnmatch.fnmatch(p, pat.lower()) for p in parts for pat in [*DENY_NAMES, *extra_names]):
        return True
    norm = "/".join(parts)
    return any(norm.endswith(s) for s in DENY_SUFFIXES)


class Config:
    def __init__(self, path):
        raw = json.load(open(path))
        base = os.path.dirname(os.path.abspath(path))
        self.roots = [os.path.realpath(os.path.expanduser(r)) for r in raw.get("roots", []) if os.path.isdir(os.path.expanduser(r))]
        self.max_bytes = int(raw.get("max_file_mb", 8)) * 1024 * 1024
        self.host = raw.get("bind_host", "127.0.0.1")
        self.port = int(raw.get("port", 8793))
        self.extra_deny = list(raw.get("extra_deny_names", []))
        tok = os.environ.get("FILE_BROWSER_TOKEN")
        if not tok:
            tf = os.path.join(base, raw.get("token_file", "token"))
            tok = open(os.path.expanduser(tf)).read().strip()
        if len(tok) < 24:
            sys.exit("token must be at least 24 characters (generate one with: openssl rand -hex 24)")
        self.token = tok
        self.uploads = raw.get("uploads") or {}


def resolve(cfg, root_i, rel):
    """Absolute path inside root `root_i`, or None if it escapes the root or looks like a secret."""
    if root_i < 0 or root_i >= len(cfg.roots):
        return None
    root = cfg.roots[root_i]
    joined = os.path.join(root, rel.lstrip("/"))
    full = os.path.realpath(joined)
    if full != root and not full.startswith(root + os.sep):
        return None
    if denied(os.path.relpath(full, root), cfg.extra_deny) or denied(os.path.relpath(joined, root), cfg.extra_deny):
        return None
    return full


def make_handler(cfg):
    class H(BaseHTTPRequestHandler):
        def _json(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("cache-control", "no-store")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            auth = self.headers.get("authorization", "")
            if not hmac.compare_digest(auth.encode(), f"Bearer {cfg.token}".encode()):
                self._json(401, {"error": "unauthorized"})
                return
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/roots":
                    self._json(200, {"roots": [{"index": i, "path": r, "name": os.path.basename(r) or r} for i, r in enumerate(cfg.roots)],
                                     "max_file_mb": cfg.max_bytes // 1048576, "uploads": bool(cfg.uploads.get("psql_command"))})
                elif u.path == "/list":
                    self.list_dir(int(q.get("root", "0")), q.get("path", ""))
                elif u.path == "/file":
                    self.send_file(int(q.get("root", "0")), q.get("path", ""))
                elif u.path == "/uploads":
                    self.list_uploads(max(1, min(500, int(q.get("limit", "100")))))
                else:
                    self._json(404, {"error": "not found"})
            except (ValueError, OSError) as e:
                self._json(400, {"error": str(e)[:200]})

        def list_dir(self, ri, rel):
            d = resolve(cfg, ri, rel)
            if not d or not os.path.isdir(d):
                self._json(404, {"error": "not a directory"})
                return
            root, out = cfg.roots[ri], []
            for name in sorted(os.listdir(d), key=str.lower):
                real = os.path.realpath(os.path.join(d, name))
                if (real != root and not real.startswith(root + os.sep)) or denied(name, cfg.extra_deny) or denied(os.path.relpath(real, root), cfg.extra_deny):
                    continue  # hidden: secret-looking, or a symlink leaving the root
                try:
                    st = os.stat(real)
                except OSError:
                    continue
                isdir = os.path.isdir(real)
                out.append({"name": name, "dir": isdir, "size": 0 if isdir else st.st_size, "mtime": int(st.st_mtime)})
            self._json(200, {"root": ri, "path": "" if d == root else os.path.relpath(d, root), "entries": out})

        def send_file(self, ri, rel):
            f = resolve(cfg, ri, rel)
            if not f or not os.path.isfile(f):
                self._json(404, {"error": "not a file"})
                return
            size = os.path.getsize(f)
            if size > cfg.max_bytes:
                self._json(413, {"error": f"file is {size} bytes; limit is {cfg.max_bytes}"})
                return
            print(f"fetch root={ri} path={os.path.relpath(f, cfg.roots[ri])} bytes={size}", file=sys.stderr, flush=True)
            with open(f, "rb") as fh:
                data = fh.read()
            self._json(200, {"name": os.path.basename(f), "size": size, "mime": mimetypes.guess_type(f)[0] or "application/octet-stream",
                             "data": base64.b64encode(data).decode()})

        def list_uploads(self, limit):
            cmd = cfg.uploads.get("psql_command")
            if not cmd:
                self._json(404, {"error": "uploads listing is not configured"})
                return
            # Buzz relay schema: media is referenced by `imeta` tags on channel messages.
            sql = ("select encode(e.id,'hex'), c.id::text, c.name, e.created_at, "
                   "(select string_agg(t::text, '|') from jsonb_array_elements(e.tags::jsonb) t where t->>0='imeta') "
                   "from events e join channels c on c.id=e.channel_id where e.tags::text like '%imeta%' and e.deleted_at is null "
                   f"order by e.created_at desc limit {int(limit)}")
            r = subprocess.run([*cmd, "-At", "-F", "\t", "-c", sql], capture_output=True, text=True, timeout=20)
            if r.returncode:
                self._json(500, {"error": "database query failed"})
                return
            items = []
            for line in r.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) < 5:
                    continue
                eid, cid, cname, ts, imeta = parts[:5]
                try:
                    tags = [json.loads(t) for t in imeta.split("|")]
                except ValueError:
                    tags = []
                for t in tags:
                    kv = dict(x.split(" ", 1) for x in t[1:] if " " in x)
                    items.append({"event": eid, "channel": cid, "channel_name": cname, "created_at": ts, "mime": kv.get("m"),
                                  "size": int(kv.get("size", 0) or 0), "link": f"buzz://message?channel={cid}&id={eid}"})
            self._json(200, {"uploads": items})

        def log_message(self, *a):
            pass

    return H


def main():
    cfg = Config(os.environ.get("FILE_BROWSER_CONFIG", "config.json"))
    if not cfg.roots:
        sys.exit("no valid roots in the config: add at least one existing directory to \"roots\"")
    ThreadingHTTPServer((cfg.host, cfg.port), make_handler(cfg)).serve_forever()


if __name__ == "__main__":
    main()
