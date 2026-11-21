// File browser — Buzz plugin (API v1). Talks to the read-only backend in server/ over HTTPS.
// __SERVER_ORIGIN__ is filled in by scripts/build_plugin.py. The access token is pasted once and kept in this app's localStorage.
export const inject = ["react", "pages", "host"];

const ORIGIN = "__SERVER_ORIGIN__";
const TOKEN_KEY = "buzz.file-browser.token";

const fmtSize = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : n >= 1024 ? Math.round(n / 1024) + " kB" : n + " B");
const fmtTime = (s) => new Date(s * 1000).toLocaleString();
const TEXT_EXT = /\.(txt|md|json|ya?ml|toml|js|mjs|ts|tsx|jsx|py|sh|rs|go|css|html|csv|log|conf|ini|sql|xml|diff|patch)$/i;

export function apply(ctx) {
  const React = ctx.react;
  const h = React.createElement;

  async function api(token, path) {
    const res = await ctx.host.request({ url: ORIGIN + path, method: "GET", headers: { Authorization: "Bearer " + token }, timeoutMs: 30000 });
    const body = typeof res.body === "string" ? res.body : new TextDecoder().decode(res.body);
    let json = null;
    try { json = JSON.parse(body); } catch (e) { /* non-JSON error body */ }
    if (res.status !== 200) throw new Error((json && json.error) || "HTTP " + res.status);
    return json;
  }

  function b64ToBytes(b64) {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function download(file) {
    const blob = new Blob([b64ToBytes(file.data)], { type: file.mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = file.name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }

  function Browser() {
    const [token, setToken] = React.useState(() => { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; } });
    const [draft, setDraft] = React.useState("");
    const [tab, setTab] = React.useState("files");
    const [roots, setRoots] = React.useState([]);
    const [hasUploads, setHasUploads] = React.useState(false);
    const [root, setRoot] = React.useState(0);
    const [path, setPath] = React.useState("");
    const [entries, setEntries] = React.useState([]);
    const [file, setFile] = React.useState(null);
    const [uploads, setUploads] = React.useState([]);
    const [error, setError] = React.useState(null);
    const [busy, setBusy] = React.useState(false);

    const run = async (fn) => { setBusy(true); setError(null); try { await fn(); } catch (e) { setError(String(e && e.message ? e.message : e)); } finally { setBusy(false); } };

    React.useEffect(() => { if (token) run(async () => { const r = await api(token, "/roots"); setRoots(r.roots); setHasUploads(!!r.uploads); }); }, [token]);
    React.useEffect(() => {
      if (!token || tab !== "files") return;
      run(async () => { const r = await api(token, `/list?root=${root}&path=${encodeURIComponent(path)}`); setEntries(r.entries); setFile(null); });
    }, [token, tab, root, path]);
    React.useEffect(() => { if (token && tab === "uploads") run(async () => { setUploads((await api(token, "/uploads?limit=200")).uploads); }); }, [token, tab]);

    const open = (e) => {
      const rel = path ? path + "/" + e.name : e.name;
      if (e.dir) { setPath(rel); return; }
      run(async () => {
        const f = await api(token, `/file?root=${root}&path=${encodeURIComponent(rel)}`);
        f.text = f.mime.startsWith("text/") || TEXT_EXT.test(f.name) ? new TextDecoder().decode(b64ToBytes(f.data)) : null;
        setFile(f);
      });
    };

    if (!token) {
      return h("section", { className: "ui-card", style: { padding: "var(--space-panel-inset)" } },
        h("h1", null, "File browser"),
        h("p", null, "Paste the access token for the file browser server."),
        h("input", { type: "password", value: draft, onChange: (e) => setDraft(e.target.value), style: { width: "28em" } }), " ",
        h("button", { onClick: () => { try { localStorage.setItem(TOKEN_KEY, draft.trim()); } catch (e) { /* keep in memory only */ } setToken(draft.trim()); } }, "Save"));
    }

    const crumbs = path ? path.split("/") : [];
    const link = (label, onClick, key) => h("a", { key, href: "#", onClick: (e) => { e.preventDefault(); onClick(); }, style: { marginRight: "4px" } }, label);

    return h("section", { className: "ui-card", style: { padding: "var(--space-panel-inset)" } },
      h("h1", null, "File browser"),
      h("div", { style: { marginBottom: "8px" } },
        link("Files", () => setTab("files"), "t1"), hasUploads ? " | " : "", hasUploads ? link("Relay uploads", () => setTab("uploads"), "t2") : null, " | ",
        link("Change token", () => { try { localStorage.removeItem(TOKEN_KEY); } catch (e) { /* ignore */ } setToken(""); }, "t3"),
        busy ? " …" : ""),
      error && h("p", { role: "alert" }, "Error: " + error),
      tab === "files" && h("div", null,
        h("div", null, roots.map((r) => h("button", { key: r.index, disabled: r.index === root, onClick: () => { setRoot(r.index); setPath(""); }, style: { marginRight: "6px" } }, r.name))),
        h("p", null, link("/", () => setPath(""), "c0"),
          crumbs.map((c, i) => h("span", { key: i }, " / ", link(c, () => setPath(crumbs.slice(0, i + 1).join("/")), "c" + i)))),
        h("table", { style: { width: "100%", borderCollapse: "collapse" } }, h("tbody", null,
          path && h("tr", { key: ".." }, h("td", { colSpan: 3 }, link("⬆ ..", () => setPath(crumbs.slice(0, -1).join("/")), "up"))),
          entries.map((e) => h("tr", { key: e.name },
            h("td", { style: { padding: "2px 6px" } }, link((e.dir ? "📁 " : "📄 ") + e.name, () => open(e), e.name)),
            h("td", { style: { padding: "2px 6px", textAlign: "right" } }, e.dir ? "" : fmtSize(e.size)),
            h("td", { style: { padding: "2px 6px", textAlign: "right" } }, fmtTime(e.mtime)))))),
        file && h("div", { style: { marginTop: "12px" } },
          h("h2", null, file.name, " ", h("small", null, fmtSize(file.size))),
          h("button", { onClick: () => download(file) }, "Download"),
          file.mime.startsWith("image/") && h("div", null, h("img", { src: `data:${file.mime};base64,${file.data}`, style: { maxWidth: "100%", marginTop: "8px" } })),
          file.text !== null && file.text !== undefined && h("pre", { style: { maxHeight: "28em", overflow: "auto", marginTop: "8px", whiteSpace: "pre-wrap" } }, file.text.slice(0, 200000)))),
      tab === "uploads" && h("div", null,
        h("p", null, "Media stored on the relay, newest first. Open the message to view or save it in the app."),
        h("table", { style: { width: "100%", borderCollapse: "collapse" } }, h("tbody", null,
          uploads.map((u, i) => h("tr", { key: i },
            h("td", { style: { padding: "2px 6px" } }, "#" + u.channel_name),
            h("td", { style: { padding: "2px 6px" } }, u.mime || ""),
            h("td", { style: { padding: "2px 6px", textAlign: "right" } }, fmtSize(u.size)),
            h("td", { style: { padding: "2px 6px", textAlign: "right" } }, u.created_at),
            h("td", { style: { padding: "2px 6px" } }, h("a", { href: u.link }, "Open message"))))))));
  }

  ctx.pages.register({ id: "main", title: "File browser", primary: true, component: Browser });
}
