# buzz-file-browser

Browse and download files from a server you run, inside the [Buzz](https://github.com/block/buzz-app) desktop app.

It has two parts:

| Part | What it is |
| --- | --- |
| **Server** (`server/`) | A small read-only HTTP service in Python 3 (standard library only). It lists folders and returns files from directories you choose. |
| **Plugin** (`plugin/`) | A Buzz plugin that adds a "File browser" page to the desktop app: root buttons, breadcrumbs, a folder list, text and image preview, and a Download button. |

```
Buzz desktop app  ──(HTTPS, bearer token)──▶  file_browser_server.py  ──▶  your allowlisted folders
 (File browser plugin)                         (read-only, 127.0.0.1)
```

> **Status.** The server and its path-safety rules are covered by tests (`python3 -m unittest discover tests`). The plugin is written against
> the Buzz plugin documentation, which describes the API (v1) as a preview that can change, and it has had little testing inside the app.
> Expect rough edges and please open an issue if something breaks.

## Contents

- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Exposing the server over HTTPS](#exposing-the-server-over-https)
- [Building and installing the plugin](#building-and-installing-the-plugin)
- [Using the plugin](#using-the-plugin)
- [Running the server as a service](#running-the-server-as-a-service)
- [Security model](#security-model)
- [HTTP API](#http-api)
- [Optional: list media from a Buzz relay](#optional-list-media-from-a-buzz-relay)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)
- [Project layout](#project-layout)
- [Development](#development)
- [License](#license)

## Requirements

- **Server host:** Python 3.9 or newer. No packages to install.
- **HTTPS in front of the server.** Buzz only lets a plugin call an exact HTTPS origin. A private-network option such as
  [Tailscale Serve](https://tailscale.com/kb/1242/tailscale-serve) works well; a reverse proxy with a TLS certificate also works.
- **A Buzz desktop app with plugin support** (Settings → Plugins). The plugin system is a preview, so check that your version has it.
- **Python 3 on the machine where you run the build script** (the same host is fine).

## Quick start

```sh
git clone https://github.com/10Legs/buzz-file-browser.git
cd buzz-file-browser

# 1. Configure: choose what to share and create a token
cp config.example.json config.json
$EDITOR config.json                 # set "roots" to directories you want to share
openssl rand -hex 24 > token && chmod 600 token

# 2. Run the server (listens on 127.0.0.1:8793)
FILE_BROWSER_CONFIG=config.json python3 server/file_browser_server.py

# 3. In another terminal: expose it over HTTPS on your private network (example uses Tailscale Serve)
tailscale serve --bg --https=10446 http://127.0.0.1:8793

# 4. Build the plugin for the HTTPS origin you just created
python3 scripts/build_plugin.py https://your-host.your-tailnet.ts.net:10446
```

Then install `dist/file-browser` in the Buzz app (see [Building and installing the plugin](#building-and-installing-the-plugin)) and paste
the contents of `token` when the plugin asks for it.

## Configuration

The server reads a JSON file. Point to it with the `FILE_BROWSER_CONFIG` environment variable (default: `config.json` in the current directory).
Start from [`config.example.json`](config.example.json).

| Key | Default | Meaning |
| --- | --- | --- |
| `roots` | none (required) | List of directories to share. Entries that don't exist are skipped. The server refuses to start if none are valid. Only these directories are reachable. |
| `max_file_mb` | `8` | Largest file the server will send, in megabytes. Larger files get HTTP 413. |
| `bind_host` | `127.0.0.1` | Address to listen on. Keep it on localhost and put HTTPS in front. |
| `port` | `8793` | Port to listen on. |
| `token_file` | `token` | File holding the access token, relative to the config file. Must contain at least 24 characters. |
| `extra_deny_names` | `[]` | Extra file or folder name patterns to hide and refuse, in addition to the built-in list. Shell-style wildcards, case-insensitive, matched against every path component. |
| `uploads.psql_command` | `[]` | Optional. Enables the relay-media tab. See [below](#optional-list-media-from-a-buzz-relay). |

You can supply the token through the `FILE_BROWSER_TOKEN` environment variable instead of a file. It takes precedence over `token_file`.

Both `config.json` and `token` are in `.gitignore`. Don't commit them.

### Choosing roots

A root is a directory the app can read in full, apart from the hidden secret-looking files. Prefer narrow, purpose-made folders such as a
projects directory or an "outbox" folder over a home directory or `/`. Symlinks inside a root that point outside it are ignored.

## Exposing the server over HTTPS

The server speaks plain HTTP on localhost on purpose. Put a TLS-terminating proxy in front of it, reachable only by your own devices.

**Tailscale Serve** (private to your tailnet):

```sh
tailscale serve --bg --https=10446 http://127.0.0.1:8793
tailscale serve status                      # shows the https:// URL
tailscale serve --https=10446 off           # undo
```

**Reverse proxy** (Caddy example), only if you also restrict who can reach it (VPN, IP allowlist, mTLS):

```
files.example.net {
    reverse_proxy 127.0.0.1:8793
}
```

Do not expose the server directly to the open internet. The token is the only login.

## Building and installing the plugin

Buzz asks the owner to approve exactly which network address a plugin may call, and that address is fixed in the plugin manifest. So the
plugin is generated for your server's address:

```sh
python3 scripts/build_plugin.py https://files.example.net:10446
```

The argument must be an HTTPS origin: scheme, host and optional port, no path. The script writes `dist/file-browser/manifest.json` and
`dist/file-browser/plugin.js`. Rebuild whenever the address changes.

Install it in the Buzz desktop app:

1. Copy `dist/file-browser` to the machine that runs the app (if it is a different machine).
2. Open **Settings → Plugins → Load from folder** and choose `dist/file-browser`.
3. Choose **Install plugin**, review the single network permission it requests, and confirm.
4. Enable the plugin. A "File browser" tab appears.
5. Open the tab and paste the access token. It is saved in the app's local storage.

To remove it, disable the plugin and delete it in the same Settings page.

## Using the plugin

- **Root buttons** switch between the directories listed in `roots`.
- **Breadcrumbs** and the `⬆ ..` row move up the tree. Click a folder to open it.
- **Click a file** to preview it. Text files show their contents (the first 200,000 characters), images are displayed, and every file has a
  **Download** button.
- **Change token** forgets the saved token so you can paste a new one.
- The **Relay uploads** tab appears only when the server has the optional relay-media feature configured.

## Running the server as a service

An example systemd user unit is in [`deploy/file-browser.service.example`](deploy/file-browser.service.example). Edit the two paths, then:

```sh
mkdir -p ~/.config/systemd/user
cp deploy/file-browser.service.example ~/.config/systemd/user/file-browser.service
$EDITOR ~/.config/systemd/user/file-browser.service
systemctl --user daemon-reload
systemctl --user enable --now file-browser
journalctl --user -u file-browser -f        # fetch log
```

Restart the service after you change `config.json`.

## Security model

You are making files readable over a network. Understand what protects them and what doesn't.

**What the server enforces**

- **Authentication.** Every request needs `Authorization: Bearer <token>`. The comparison is constant-time. Use a long random token
  (`openssl rand -hex 24`).
- **Read-only.** There are no write, upload, rename or delete endpoints.
- **Allowlisted roots.** Paths are resolved to their real location. Anything that ends up outside the chosen root, through `..`, an absolute
  path or a symlink, is refused.
- **Secret-looking files are hidden and refused.** They don't appear in listings and return 404 if requested. Built in:
  `.env`, `.env.*`, `*.env`, `*.key`, `*.pem`, `*.p12`, `*.pfx`, `*.authtag`, `*.token`, `secrets`, `.ssh`, `.gnupg`, `auth.json`, `.netrc`,
  `.npmrc`, `.pypirc`, `id_rsa*`, `id_ed25519*`, `credentials*`, `private-key*`, plus `.git/config` and `.git/credentials`. The check applies to
  every path component, so a file inside a `secrets` folder is hidden too. Add more with `extra_deny_names`.
- **Size limit.** Files over `max_file_mb` are refused.
- **Logging.** Each file fetch is logged with root, path and size. The token is never logged.

**What it does not do**

- The deny list is a safety net, not a guarantee. A secret in a file with an ordinary name, or inside the contents of a normal file, is not
  detected. **Only add roots you are happy to share.**
- It does not encrypt traffic. That is the job of the HTTPS layer you put in front of it.
- One shared token, no per-user accounts and no rate limiting. Anyone with the token and network access can read every shared file.
- Git history inside a shared repository is readable, because `.git` objects are ordinary files. Don't share repositories with secrets in their history.
- The plugin keeps the token in the app's local storage, readable by anything that runs inside the app. Plugins are trusted code. Install only plugins you trust.

**Good practice:** rotate the token if it might have leaked (replace the `token` file, restart the server, paste the new token in the plugin),
keep the HTTPS endpoint private, and review the list of roots now and then.

To report a vulnerability, please open a private security advisory on the GitHub repository rather than a public issue.

## HTTP API

All endpoints are `GET`, return JSON, and require the bearer token. Errors look like `{"error": "..."}` with the HTTP status noted below.

| Endpoint | Description |
| --- | --- |
| `/roots` | `{"roots": [{"index", "path", "name"}], "max_file_mb", "uploads"}`. `uploads` is true when the relay-media feature is configured. |
| `/list?root=<i>&path=<relative path>` | `{"root", "path", "entries": [{"name", "dir", "size", "mtime"}]}`. `path` is relative to the root, empty for the root itself. Hidden entries are omitted. |
| `/file?root=<i>&path=<relative path>` | `{"name", "size", "mime", "data"}` with `data` base64-encoded. 404 if missing or hidden, 413 if over the size limit. |
| `/uploads?limit=<n>` | Relay media metadata, newest first (1 to 500, default 100). 404 unless configured. |

Status codes: `401` missing or wrong token, `404` unknown endpoint, missing path or hidden path, `413` file too large, `400` bad parameters.

```sh
TOKEN=$(cat token)
curl -H "Authorization: Bearer $TOKEN" "https://files.example.net:10446/roots"
curl -H "Authorization: Bearer $TOKEN" "https://files.example.net:10446/list?root=0&path=docs"
```

## Optional: list media from a Buzz relay

If the server host can run `psql` against a self-hosted Buzz relay's database, the plugin can show a **Relay uploads** tab that lists media
shared in channels (channel, type, size, time, and a link to the message). It lists metadata only and does not download relay media, because that
needs per-channel authentication. Each row links to the original message so you can view or save it in the app.

Enable it by setting the command prefix that runs `psql` against the relay database, for example:

```json
"uploads": { "psql_command": ["psql", "-h", "localhost", "-U", "relay_db_user", "-d", "relay_db_name"] }
```

or through a container:

```json
"uploads": { "psql_command": ["docker", "exec", "my-relay-postgres", "psql", "-U", "relay_db_user", "-d", "relay_db_name"] }
```

This reads the relay's database schema (`events` and `channels` tables), so it can break when the relay changes. Use a read-only database
role. Leave `psql_command` empty to turn the feature off.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Plugin shows "Error: HTTP 401" or "unauthorized" | The token is wrong. Use **Change token** and paste the exact contents of the token file. |
| "Couldn't load" or a network error | Is the server running? Is the HTTPS endpoint up (`tailscale serve status`)? Does the origin the plugin was built for match the real address? Rebuild with the right origin if not. |
| Install asks for a different origin than expected | You built with the wrong argument. Rebuild with `scripts/build_plugin.py`. |
| A file you expect is missing | It may match the deny list or sit behind a symlink that leaves the root. Test with the API: hidden paths return 404. |
| "file is N bytes; limit is M" | Raise `max_file_mb`, or fetch large files another way. |
| Server exits with "no valid roots" | The paths in `roots` don't exist on this machine. |
| Server exits with "token must be at least 24 characters" | Regenerate it with `openssl rand -hex 24 > token`. |
| Download button does nothing | Saving files from the app's webview isn't guaranteed. Use the preview to copy text, or fetch the file through the API with `curl`. |
| Settings → Plugins has no "Load from folder" | Your Buzz app version may predate plugin support. |

## Limitations

- Read-only. No upload, rename or delete.
- Files travel as base64 inside JSON, so large files are capped (default 8 MB).
- Single shared token, no per-user access control.
- The plugin API is a preview and can change between Buzz releases.
- The relay-media tab depends on the relay's database schema.

## Project layout

```
server/file_browser_server.py   read-only HTTP server (standard library only)
plugin/manifest.template.json   plugin manifest, origin filled in by the build script
plugin/plugin.template.js       plugin code, origin filled in by the build script
scripts/build_plugin.py         builds dist/file-browser for your server's HTTPS origin
deploy/file-browser.service.example   systemd user unit
config.example.json             example server configuration
tests/test_paths.py             path-safety tests
```

## Development

```sh
python3 -m unittest discover tests          # path-safety tests
python3 scripts/build_plugin.py https://files.example.net:10446
node --check dist/file-browser/plugin.js    # syntax check (copy to .mjs if your Node needs it)
```

Contributions are welcome. Keep the server dependency-free, keep it read-only, and add a test for any change to the path or deny rules.

## License

MIT. See [`LICENSE`](LICENSE).
