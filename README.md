# arrctl

[![CI](https://github.com/xLinkOut/arrctl/actions/workflows/ci.yml/badge.svg)](https://github.com/xLinkOut/arrctl/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/xLinkOut/arrctl)](https://github.com/xLinkOut/arrctl/releases)

Declarative configuration for **Sonarr**, **Radarr**, **Lidarr**, **Whisparr**, **Prowlarr** and **Bazarr**.

`arrctl` keeps a single YAML file as the source of truth, can **apply** it to a running stack, and can **pull** the current live configuration back into the file. It talks directly to the app APIs, uses native field names, and only manages the keys you put in the file.

```text
             arr.yaml
                │
        ┌───────┴────────┐
        │     arrctl     │
        └───────┬────────┘
                │ HTTP API
   ┌────────────┼────────────┬───────────┬──────────┐
 Sonarr      Radarr       Lidarr     Whisparr   Prowlarr
                                                │
                                             Bazarr
```

## Why another *arr tool?

Buildarr and Flemmarr were good ideas, but they are unmaintained. Most current tools solve only one slice of the problem (Recyclarr/Configarr for quality profiles). `arrctl` is deliberately small and focused:

- one YAML file, no state database;
- native API field names, no translation layer;
- common defaults plus per-app overrides;
- `plan`/`apply`/`pull` workflows;
- works with a fresh Docker Compose stack;
- no secrets in the repository by default.

## Install

With `uv`/`uvx`, directly from GitHub (no clone needed):

```bash
uvx --from git+https://github.com/xLinkOut/arrctl arrctl --help
```

Once the package is published to PyPI:

```bash
uvx arrctl --help
```

Or install it as a normal tool:

```bash
uv tool install arrctl
```

Python 3.11 or newer is required.

## Quick start

Create a starter file:

```bash
arrctl init -o arr.yaml
```

Edit the connections and add API keys through environment variables:

```bash
export SONARR_API_KEY=...
export RADARR_API_KEY=...
```

Preview changes:

```bash
arrctl plan -c arr.yaml
```

Apply:

```bash
arrctl apply -c arr.yaml --yes
```

Import an existing live stack into a new file:

```bash
arrctl init --from-live -o arr.yaml
# or, if arr.yaml already has the connections:
arrctl pull -c arr.yaml --infer-defaults
```

## The YAML file

```yaml
version: 1

defaults:
  host:
    logLevel: info
    updateMechanism: docker
    backupInterval: 7
  ui:
    firstDayOfWeek: 1          # Monday
    theme: auto
  mediamanagement:
    copyUsingHardlinks: true
    importExtraFiles: true
    extraFileExtensions: srt

apps:
  sonarr:
    connection:
      url: http://127.0.0.1:8010
      api_key: ${SONARR_API_KEY}
      # api_key_file: /srv/jupiter/sonarr/config.xml
    config:
      naming:
        renameEpisodes: true
        standardEpisodeFormat: "{Series Title} - S{season:00}E{episode:00} - {Episode Title} [{Quality Full}]"
    resources:
      rootfolder:
        - path: /data/library/serie
      tag:
        - label: arrctl
```

### `defaults`

`defaults` is deep-merged into every Servarr app that supports the resource. App values win. For example, `defaults.ui.firstDayOfWeek: 1` applies to Sonarr, Radarr, Lidarr, Whisparr and Prowlarr, but not to Bazarr (Bazarr has no week-start setting and uses a different settings model).

Lists are replaced, not merged.

### `apps.<app>.config`

Config singletons exposed by the app API:

| Resource | Sonarr | Radarr | Lidarr | Whisparr | Prowlarr | Bazarr |
|---|---|---|---|---|---|---|
| `host` | ✓ | ✓ | ✓ | ✓ | ✓ | `general` + `auth` |
| `ui` | ✓ | ✓ | ✓ | ✓ | ✓ | `general` (partial) |
| `mediamanagement` | ✓ | ✓ | ✓ | ✓ | — | — |
| `naming` | ✓ | ✓ | ✓ | ✓ | — | — |
| `indexer` | ✓ | ✓ | ✓ | ✓ | — | providers |
| `downloadclient` | ✓ | ✓ | ✓ | ✓ | only `id` | — |
| `importlist` | ✓ | ✓ | — | ✓ | — | — |
| `metadata` | — | ✓ | — | — | — | — |
| `metadataprovider` | — | — | ✓ | — | — | — |
| `development` | — | — | — | — | ✓ | — |

The names are the actual API field names. For example:

```yaml
config:
  ui:
    firstDayOfWeek: 1
```

No `firstDayOfWeek-something` or camel-to-snake translation. Use `arrctl schema sonarr ui` to list valid fields.

### `apps.<app>.resources`

Collections are lists of native API objects. Common resources:

| Resource | Apps | Identity |
|---|---|---|
| `rootfolder` | Sonarr, Radarr, Lidarr, Whisparr | `path` |
| `tag` | all Servarr | `label` |
| `downloadclient` | all Servarr | `name` |
| `indexer` | all Servarr | `name` |
| `notification` | all Servarr | `name` |
| `importlist` | Sonarr, Radarr, Lidarr, Whisparr | `name` |
| `importlistexclusion` / `exclusions` | Sonarr/Lidarr, Radarr/Whisparr | IDs/title |
| `qualityprofile` | Sonarr, Radarr, Lidarr, Whisparr | `name` |
| `qualitydefinition` | Sonarr, Radarr, Lidarr, Whisparr | `quality.name` |
| `customformat` | Sonarr, Radarr, Lidarr, Whisparr | `name` |
| `delayprofile` | Sonarr, Radarr, Lidarr, Whisparr | `order` |
| `releaseprofile` | Sonarr, Radarr, Lidarr, Whisparr | `name` |
| `metadata` | Sonarr, Radarr, Lidarr, Whisparr | `name` |
| `autotagging` | Sonarr, Radarr, Lidarr, Whisparr | `name` |
| `remotepathmapping` | Sonarr, Radarr, Lidarr, Whisparr | `host` + `remotePath` |
| `customfilter` | all Servarr | `label` |
| `languageprofile` | Sonarr | `name` |
| `metadataprofile` | Lidarr | `name` |
| `application` | Prowlarr | `name` |
| `appprofile` | Prowlarr | `name` |
| `indexerproxy` | Prowlarr | `name` |

For resources with a `fields` list (download clients, indexers, notifications, import lists, applications, proxies), write `fields` as a mapping:

```yaml
resources:
  downloadclient:
    - name: qBittorrent
      implementation: QBittorrent
      configContract: QBittorrentSettings
      enable: true
      protocol: torrent
      priority: 1
      fields:
        host: gluetun
        port: 8080
        username: admin
        password: ${QBITTORRENT_PASSWORD}
        movieCategory: film
```

`arrctl` merges those values into the app's field schema. Existing resources keep their field metadata; new resources use `implementation`/`configContract` to find the right schema.

### Secrets

Use environment variables or files:

```yaml
api_key: ${SONARR_API_KEY}
password: ${QBITTORRENT_PASSWORD}
token: ${file:/run/secrets/ntfy_token}
```

`${VAR:-default}` is supported. `api_key_file` can read the `<ApiKey>` element directly from a Servarr `config.xml`:

```yaml
connection:
  url: http://127.0.0.1:8010
  api_key_file: /srv/jupiter/sonarr/config.xml
```

`pull` omits secret fields unless `--include-secrets` is passed. Do not commit secrets to the repository.

## Commands

### `plan`

```bash
arrctl plan -c arr.yaml
arrctl plan -c arr.yaml --only sonarr.ui,radarr
arrctl plan -c arr.yaml --json
```

Exit code `2` means drift was found; `0` means the live state matches. This is intentional so it can run from cron.

### `apply`

```bash
arrctl apply -c arr.yaml
arrctl apply -c arr.yaml --yes
arrctl apply -c arr.yaml --dry-run
arrctl apply -c arr.yaml --restart
```

`apply` does `GET` on the current object, overlays the managed keys, and `PUT`s the complete object. Keys not present in the YAML are left alone. UI changes to unmanaged keys survive.

`--restart` calls `/system/restart` only for apps where host/network fields changed.

### `pull`

```bash
arrctl pull -c arr.yaml
arrctl pull -c arr.yaml --only sonarr,radarr --infer-defaults
```

`pull` reads the live apps and writes them into the file, preserving YAML comments where possible. `--infer-defaults` moves values that are identical across apps into `defaults`.

Pull is deliberately an explicit command, not a background bidirectional sync. Use `plan` for drift detection; use `pull` when you intentionally want to adopt a UI change.

### `init`

```bash
arrctl init -o arr.yaml
arrctl init --from-live -o arr.yaml
```

The first form writes a template with all connections. The second prompts for each URL and API key and imports the live stack.

### `validate` / `doctor`

```bash
arrctl validate -c arr.yaml
arrctl doctor -c arr.yaml
arrctl doctor -c arr.yaml --strict
```

`validate` is offline. `doctor` checks connectivity and compares the bundled schema with the live API, which is useful after an app upgrade.

### `schema`

```bash
arrctl schema
arrctl schema sonarr
arrctl schema sonarr ui
arrctl schema radarr downloadclient
```

## Fresh Docker Compose stack

A one-shot service is enough:

```yaml
services:
  arrctl:
    image: ghcr.io/xlinkout/arrctl:0.1.3
    profiles: ["setup"]
    networks: [media]
    depends_on:
      sonarr:
        condition: service_started
      radarr:
        condition: service_started
      lidarr:
        condition: service_started
      whisparr:
        condition: service_started
      prowlarr:
        condition: service_started
      bazarr:
        condition: service_started
    volumes:
      - ./arr.yaml:/etc/arrctl/arr.yaml:ro
    environment:
      SONARR_API_KEY: ${SONARR_API_KEY}
      RADARR_API_KEY: ${RADARR_API_KEY}
      LIDARR_API_KEY: ${LIDARR_API_KEY}
      WHISPARR_API_KEY: ${WHISPARR_API_KEY}
      PROWLARR_API_KEY: ${PROWLARR_API_KEY}
      BAZARR_API_KEY: ${BAZARR_API_KEY}
    command: ["apply", "-c", "/etc/arrctl/arr.yaml", "--wait", "120", "--yes"]
```

For a truly fresh instance, either inject the API keys before first boot with the Servarr environment variables (`SONARR__AUTH__APIKEY`, etc.) or use `api_key_file` and let the container read the generated `config.xml` from a read-only mount.

> **Caveat:** the initial Forms admin user may still need to be created once in the UI. The API can set auth mode and credentials on some versions, but this is the one part that is not consistently exposed by every app.

## Security

- API keys and passwords are resolved from environment variables or files.
- `pull` omits secrets by default.
- `plan` redacts secrets in output.
- The tool does not store secrets in a state file.
- Use a read-only mount for `config.xml` if you use `api_key_file`.
- Use `verify_ssl: false` only for local self-signed certificates.

## Scope and current limitations

- `arrctl` manages settings and configuration resources, not the media library.
- No automatic deletion/pruning. Removing an item from YAML does not delete it from the app.
- `arrctl` resolves the common references by name: `qualityProfileId`, `metadataProfileId`, `languageProfileId`, `downloadClientId`, `appProfileId`, `indexerId` and `tags`. `pull` writes names/labels; `apply` turns them back into the IDs of the target instance. Other IDs remain native.
- Bazarr settings use the hidden `/api/system/settings` endpoint. It works on 1.6.x but is not part of Bazarr's documented public API.
- Quality definitions are predefined; `arrctl` can update them but not create them.
- Host/network changes may require a restart; use `--restart` or restart the container.

## Development

```bash
git clone https://github.com/xLinkOut/arrctl
cd arrctl
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run arrctl --help
```

Build:

```bash
uv build
```

## License

MIT
