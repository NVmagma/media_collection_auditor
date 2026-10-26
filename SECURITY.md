# Security policy

## Reporting vulnerabilities

Please report suspected security vulnerabilities privately using the
repository's **Security** tab and private vulnerability reporting, if enabled.
If private reporting is unavailable, contact the repository maintainer through
an existing private channel. **Do not open a public issue containing a working
exploit, credentials, tokens, or private media paths.**

## Supported deployments

The supported deployment target is the current Unraid Docker release.
Development branches are experimental. SQLite is not approved as the
production state authority, and permanent filesystem deletion remains disabled.

## Review and remediation

GitHub Actions runs Python dependency auditing and container CVE scanning
on a weekly schedule, on demand, and for relevant changes. Dependabot
proposes dependency updates to the active development branch.

A scanner finding requires triage: confirm affected package and version,
exploitability, reachable code, available fix, and deployment impact. Prioritize
actively exploited or critical vulnerabilities immediately rather than waiting
for the weekly review. Record decisions and verify regression tests and both
existing CI workflows before recommending an image update.

Do not auto-merge security PRs or auto-deploy containers. Preserve Jellyfin
protection fail-closed behavior and deletion safeguards. Test risky changes
with disposable media and maintain a rollback plan.

CodeQL enablement for this private repository depends on available GitHub
security features and is tracked separately in the feature roadmap.
