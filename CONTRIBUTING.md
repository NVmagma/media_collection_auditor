# Contributing

Start from the released `main` branch and open a focused pull request. The
maintainer uses `feature/unraid` as a development branch; an older checkout of
that branch may predate the current release, so compare it with `main` before
building on it. Public contributions can use a topic branch in a fork.

Report reproducible bugs through GitHub Issues. Include the image tag/revision,
relevant enabled settings, expected behavior, actual behavior, and redacted scan
results. Remove API keys, tokens, passwords, private webhook URLs, and personal
media paths. Use [private security reporting](SECURITY.md) for vulnerabilities.

## Local setup

Use Python 3.12 and an isolated environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt pytest
PYTHONPATH=.:app:tests WEB_SESSION_SECRET=synthetic-test-secret \
  python -B -m pytest -q tests
```

Tests involving atomic renames and Linux mount identities require Linux. GitHub
Actions provides that environment. Never point tests at production appdata,
media folders, or service credentials.

Build the current runtime with:

```bash
docker build -f docker/runtime.Dockerfile \
  --build-arg SOURCE_REVISION="$(git rev-parse HEAD)" \
  -t media-collection-auditor:local .
```

Browser tests use development-only dependencies under `tests/dashboard-browser`;
widget rendering uses `tests/homarr-render`. The commands maintained in
[Python safety checks](.github/workflows/python-safety.yml) are the reference for
rendering their synthetic inputs and running Chromium/JSX checks.

## Review expectations

Keep changes small and explain the user-visible behavior. Preserve unknown JSON
fields, existing lifecycle clocks, pending operations, and default-off destructive
features. A proposal or HTTP acknowledgment is insufficient evidence that an
operation completed. Changes involving media must handle failure, interruption,
retries, and concurrent writers consistently.

Use disposable media and loopback mock services for destructive tests. New tests
should target a meaningful behavior or regression. Include the relevant validation
in the pull request and wait for required GitHub checks before recommending an
image update. For documentation-only changes, verify file links, commands,
configuration names, and descriptions against the code.

## Release workflow

`main` is the release source. Candidate acceptance builds and tests an exact image
before optional publication as `json-candidate-<revision>`. The release template
pins an accepted digest. A separate explicit promotion moves `:stable` to that
same digest. Publishing an image does not update a running Unraid container.
See [branch and release workflow](docs/branch-workflow.md).
