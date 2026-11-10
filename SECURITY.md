# Security policy

## Reporting vulnerabilities

Report vulnerabilities privately through [GitHub private vulnerability reporting](https://github.com/NVmagma/media_collection_auditor/security/advisories/new)
when available. If that form is unavailable, use an existing private channel with
the maintainer. Public issues should exclude working exploits, credentials,
private webhook URLs, and sensitive media paths.

## Supported deployment

The current release on `main`, published as
`ghcr.io/nvmagma/media_collection_auditor:stable`, targets Docker on Unraid.
Development candidates are for testing. Persistent JSON state holds clocks,
settings, scan history, and pending operation state.

New installs start in preview mode. Whole-title deletion and staged TV season
deletion have separate default-off switches and saved warning acknowledgments.
Whole-title deletion is requested through Arr. Opt-in season deletion permanently
removes only an eligible isolated staged season. See [Removal deletion](docs/removal-deletion.md)
and [TV season retention](docs/tv-season-retention.md) for required checks and
interrupted-operation behavior.

Treat appdata, backups, first-run setup codes, Jellyfin/Arr keys, webhook URLs, and integration
tokens as secrets. Backups may contain saved service credentials. Keep the
administrative interface on controlled networks and use HTTPS for remote access.
The runtime uses Flask's built-in server. Integration tokens grant read-only API
access but can expose collection information to dashboard viewers.

## Checks and remediation

GitHub Actions runs dependency auditing and runtime-image vulnerability scanning
on relevant changes, on demand, and weekly. Dependabot is configured to propose
updates against `feature/unraid`; maintainers must bring applicable fixes into the
current release lineage. Scanner findings require package/version triage and
regression verification. Review actively exploited or critical issues promptly.

Do not automatically deploy dependency changes. Test media operations against
disposable files, preserve fail-closed protection checks, and retain a recovery
plan. Public repository visibility does not establish that any optional scanner
or GitHub security feature has been enabled; workflow files are the source for
checks currently configured by the project.
