# Changelog

## 0.1.8

- Treat the API's `********` masked secret values as unchanged, avoiding
  permanent drift for notification tokens and passwords.

## 0.1.7

- Strip read-only `supportsOn*` flags from pulled notifications and creates.

## 0.1.6

- Resolve `${ENV}` placeholders inside config values and resource `fields`.
- Redact secrets and credential-bearing URLs in `plan` output, including resource creates.
- Keep `arrctl plan --json` machine-readable.

## 0.1.5

- Treat encryption keys as secrets during pull/plan.
- Skip Bazarr notifications by default because provider URLs may embed tokens.
- Redact URLs containing credentials or token query parameters.

## 0.1.4

- Keep `version` first when `pull --infer-defaults` creates the defaults block.
- Make `doctor` exit non-zero when it finds problems.
- Emit clean JSON from `plan --json`.

## 0.1.3

- Resolve `api_key_file` paths relative to the YAML file.
- Do not persist API keys entered interactively by `init --from-live`.
- Fix the qBittorrent category names in the example configuration.

## 0.1.2

- Resolve tags and common resource references (`qualityProfileId`, `metadataProfileId`,
  `languageProfileId`, `downloadClientId`, `appProfileId`, `indexerId`) by name.
- Pull complete Bazarr settings, including boolean/list values that the live API
  does not expose as scalar leaf nodes.
- Add release workflow for GitHub releases, GHCR images and optional PyPI publishing.
- Add mypy to CI.

## 0.1.1

- Safer `init --from-live`: API keys are used for the import and replaced with
  environment placeholders before the YAML is written.
- Fix base URLs with a path component.
- Create referenced resources (tags, profiles) before resources that use them.

## 0.1.0

- Initial release: plan/apply/pull/init/validate/doctor/schema.
- Config singletons and resource collections for Sonarr, Radarr, Lidarr,
  Whisparr, Prowlarr and Bazarr.
- Native API field names, shared defaults, environment/file secrets.
