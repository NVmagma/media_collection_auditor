# Disposable controller runtime without host Python

Tower has no host Python installation. The initial accepted design permits all
Docker services to pause, so the maintenance controller cannot depend on the
Docker daemon remaining alive. This rehearsal checks a possible interpreter
packaging mechanism; it does not implement the production controller or fence.

`bash scripts/sqlite_controller_runtime_lab.sh EXISTING_LAB_BASE` uses only a new
0700 subdirectory and the already-cached, reviewed Python image. The default is
`python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1`.
An explicit `SQLITE_LAB_IMAGE` override must be an immutable digest/image ID;
a mutable tag rejects. No pull, image build or package installation occurs.

It creates a new unstarted container without host binds, exports its filesystem,
and removes only that new container. A restricted packaging container has only
the new lab and the single preparer script mounted, no network, host settings,
media or Docker socket. Archive extraction rejects traversal, escaping links,
devices and excessive expansion. Absolute image symlinks become equivalent
contained relative links before Python's data extraction filter. Existing
runtime directories are never adopted or overwritten; partial artifacts remain.

The host then invokes `unshare --net -- chroot NEW_ROOTFS ...` to launch a fixed
Python smoke program directly, outside Docker. Only that new process receives
the private network namespace. No host proc/dev, production mount or socket is
bound into the rootfs. The fixed program verifies Python, an exclusive flock
and a synthetic SQLite checkpoint under its own `/tmp`. All lab artifacts stay
available for review. No existing service, startup preference, NFS control,
media/state path or kernel module setting is changed. The lab requires host
root, `chroot`, `unshare` and executable lab storage; capability failures stop
rather than changing mount permissions or installing host packages.

This is a root-launched disposable program, not an adversarial sandbox or a
production runtime approval. It executes only the fixed reviewed smoke program
from the cached image, which must remain trusted. Source/package integrity,
application dependencies, private production storage, process credentials,
actual host bindings and the complete host controller remain separate deployment
requirements. No production media command or arbitrary entrypoint is accepted.

Expected final status: `disposable_host_runtime_verified` with
`exclusive_lock_verified=true`, `sqlite_checkpoint_verified=true`, and all
production/writer-exclusion authorization flags false. A successful result does
not disable Docker or establish writer exclusion. It establishes whether this
interpreter mechanism is usable on the actual host before the controller is
packaged around it.

## Independent Linux VM acceptance

The full launcher passed using a locally imported synthetic Ubuntu Python 3.12.3
image (SQLite 3.45.1), without a pull or image build. This is mechanism acceptance,
not acceptance of Tower's separate cached Python image. After the VM's private
Docker daemon exited, another host-launched invocation of the extracted runtime
read the synthetic SQLite checkpoint successfully with Docker unavailable.
An initial cached archive containing only Docker tools rejected the missing Python
entrypoint; no success result was inferred from that failure. All artifacts were
retained and no production daemon was involved. Tower's focused runtime check
remains required before selecting this packaging mechanism for its controller.
