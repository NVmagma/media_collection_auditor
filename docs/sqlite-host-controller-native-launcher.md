# Native preparation launcher without host Python installation

Status: preparation-only launcher implemented; local ARM64 Linux acceptance passed.
Unraid/x86-64 acceptance is pending. No service adapter or production activation
has been added, and all existing controller blockers remain.

## Mechanism and trust boundary

`scripts/sqlite_host_controller_native.sh` invokes the exported runtime's own
Linux loader and interpreter, with explicit runtime library directories and a
clean environment. Python discovers its copied standard library from the exported
interpreter path. It runs the existing six-module controller bundle with `-I -S`.
No host Python installation, chroot, namespace creation, mount, Docker call or
boot/service setting is needed by this entry point. The packaging step is separate.

This is a **trusted native process, not an OS sandbox**. It can observe the
calling host's process/namespace scope directly; there is no synthetic or
caller-supplied boot identity. Its current code accesses the explicitly selected
preparation directory and kernel observations, and exposes no external-action API.
Its privileges still require deployment review before adding actual host adapters.
Filesystem visibility is not restricted by a chroot; runtime/source integrity and
the trusted-administrator protocol remain essential. A successful preparation
never proves external writer exclusion or that control storage has no aliases.

The launcher accepts only prepare, hold and review. It requires canonical paths,
the accepted disposable runtime marker, and explicit reviewed manifest/entry-point
SHA-256 values. The fixed bundle entry point then checks every source hash.
Loader/interpreter/library paths must resolve within the exported rootfs. Missing
runtime files, unknown architecture, mismatched package hashes and observed
fallback of immediate interpreter dependencies fail before controller invocation.
A fixed preflight also checks the copied Python prefix and observed mappings after
loading the controller's standard-library extensions, before control-state creation.
`--inhibit-cache` avoids the host loader cache. LC_ALL/LANG use C and GCONV_PATH
points into the runtime to avoid the locale/conversion-data fallback found during
the first fixture run. This is not a complete dynamic-extension or hostile-root
runtime attestation; production binding remains unverified.

Fixed loader layouts are provided for x86-64 and ARM64 Debian-based exports.
Other layouts/architectures fail instead of guessing. This is a runtime capability
constraint, not a media filesystem-name restriction.

## Local real Linux acceptance

The dedicated new container fixture used cached Python 3.12.15 on ARM64. It copied
only that image's interpreter, standard library and native libraries into a new
runtime tree, omitting site packages. It passed:

- native launcher -> copied loader/interpreter -> actual packaged controller;
- every observed file-backed runtime mapping under the new runtime root;
- real SIGKILL of that new controller, with its request unchanged;
- fresh review process refusing session adoption;
- rejection of an altered manifest digest;
- an incomplete copied standard library refused before any new control state.

The container had no network, host binds, Docker socket or added capabilities.
Only its new tmpfs was executable. The test did not modify a host runtime or test
Tower's x86-64 loader. It mirrored runtime files from its image; full image-export
extraction remains the separately accepted runtime component.

## Narrow Tower acceptance command

The existing accepted runtime was retained at
`/mnt/media/sql_test/controller-runtime.l969Uy`. Verify that this is still the
intended disposable runtime before testing; a missing runtime/marker is refused.
From the updated feature/sqlite checkout, the new lab driver is:

```sh
bash -p scripts/sqlite_host_controller_native_lab.sh \
  /mnt/media/sql_test/controller-runtime.l969Uy /mnt/media/sql_test
```

The driver creates a new 0700 native-controller.* lab. A temporary cached-image
packager sees only seven fixed Python source files read-only and that new lab
writable. It has no network, capabilities, host settings, media or Docker socket.
It builds the exact bundle without pulling an image or installing dependencies.
The existing runtime is read, not rewritten.

Prepare and review then execute as **host processes**, using the existing exported
runtime. They create only new preparation state, read native Linux scope, and
verify retained artifact bytes are unchanged by review. They never stop Docker,
shares or mover, mount anything, change array auto-start, alter boot files, load
modules, contact Jellyfin/Arr, or touch production tracking/media.

Expected final status: `native_host_preparation_lab_complete`, with
`retained_request_unchanged=true` and every action/production/exclusion flag false.
The JSON controller reports intentionally remain `blocked`: this test accepts
native launch mechanics, not a service fence or approved production control path.
If any check fails, retain the output and new lab; do not repair/adopt its state.
No runtime is automatically deleted and no existing service is restored/restarted.

## Still required

After actual x86-64 acceptance, review the immutable runtime/source deployment,
all extension dependencies and the private persistent control location outside
exports/binds/aliases. Then implement exact host service/settings adapters and
owned-change recovery, with boot fencing and authoritative fresh protections.
Native observations do not remove any of those requirements. The alternative
chroot/bind-mapping design is not silently activated by this mechanism.
