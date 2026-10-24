# Unraid boot enforcement: source review and remaining blocker

Status: boot enforcement is not implemented or accepted. No Tower startup file,
boot image, service, preference, array state or kernel setting was changed.

The operator requires automatic array/managed-pool startup after reboot, while
web management and SSH remain available. Leaving storage stopped until recovery
was explicitly declined. Docker, SMB, NFS and scheduled mover may pause, but that
design permission is not authorization to install or change Tower's settings.

## Confirmed startup order

Sources below were downloaded and read, never executed, at pinned official Unraid
revision `26eb1b5c1d547ddbf44a38e63956ba24f659098b`.

| Source | Upstream SHA-256 | Relevant constraint |
| --- | --- | --- |
| `etc/rc.d/rc.M` | `77d4b4c81b5718c5a5d902667e120fca37f78d9a69c2a953bbdd48c05574b96f` | Cron starts at lines 188–190, Samba at 236–240, rc.local at 252–255 |
| `etc/rc.d/rc.local` | `96d61ef181addb26e8d407b4b981cd0951d8a919357441f330567296f7df5813` | Safe Mode skips plugins/packages and selects go.safemode; absent selected go file falls back to emhttp |
| `etc/rc.d/rc.S.cont` | `02e75b216251fded0dd6e9aa2d691f1db1a14eb79743e475310d560cef24eb0f` | Copies custom udev rules/scripts early, but permits nohotplug to skip udev startup |
| `etc/rc.d/rc.udev` | `7f765e2b7783ed61ffa8e5fda6689b58da68e7c11e022d8f64bdb98bb7fae15d` | Event settlement has a 120-second timeout; the script exits zero without making guard success a required boot condition |

The first two hashes match earlier Tower observations. The latter two are upstream
review fingerprints only; matching Tower copies have not been established.

Source links: [rc.M](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/etc/rc.d/rc.M),
[rc.local](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/etc/rc.d/rc.local),
[rc.S.cont](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/etc/rc.d/rc.S.cont),
[rc.udev](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/etc/rc.d/rc.udev).

This establishes ordering of entry points, not proof that media was written before
management started. A late hook cannot alone cover earlier writers. An early udev
RUN rule cannot be treated as a guaranteed barrier when it can be skipped, fail or
time out while startup continues. No boot-image patches, init replacement or
custom kernel changes are proposed. A go-only/plugin-only installer is rejected
as a complete normal/Safe Mode fence.

## Persistent writer opt-out component

A viable candidate layer is persistent writer opt-out while storage still starts
automatically, paired with runtime guards and independently verified outcomes.
The public settings pages establish supported UI controls; their compiled manager
transaction/failure behavior and actual reboot effects still need acceptance.

The [Mover Settings page](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/emhttp/plugins/dynamix/MoverSettings.page)
provides Disabled and submits an empty `shareMoverSchedule` value.
The [Disk Settings page](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/emhttp/plugins/dynamix/DiskSettings.page)
provides `startArray=yes/no`; changing it to no is outside the accepted model.

`sqlite_boot_share_config_candidate.py` prepares exact SMB/NFS disabled and
empty mover-schedule bytes from an explicitly marked disposable share.cfg.
It rejects missing, duplicate, executable-looking or ambiguous assignments and
preserves unrelated bytes and line endings. A new private review directory holds
the original, candidate and manifest. It does not open or alter disk.cfg; storage
auto-start is unchanged. Restoration candidates require exact unchanged bytes.
The existing Docker candidate remains a separate review component.

```sh
python -B -m scripts.sqlite_boot_share_config_plan --root /absolute/marked/disposable/config-lab
```

The command has no host mode. It requires the existing disposable configuration
marker. Neither it nor this document edits live preferences, sources shell config,
submits a privileged manager POST or executes service/scheduler commands. Use an
explicit supported administrator settings step only after the whole package and
rollback are concrete and separately approved.

## Required before boot enforcement can be claimed

1. Implement/accept persistent writer opt-out with exact backups and owned-change
   recovery; preserve automatic storage startup and management availability.
2. Verify actual share/export access and generated schedules, including alternate
   writer routes, through the entire boot interval. A daemon starting or stopping
   is not by itself proof about writable media access.
3. Bind runtime guards and the private retained request to the actual host scope;
   missing/corrupt requests, unavailable runtime, hook failures and boot changes
   must not restore writers or authorize media work.
4. Accept normal and Safe Mode behavior with real Unraid manager/array startup and
   failure handling. Existing container/Ubuntu tests do not substitute for this.

The cutover report now explicitly includes the non-configurable implementation
blocker `production_boot_writer_fence_unimplemented`. Preference values, a source
hash or an operator boolean cannot clear it. Gate 6 remains open.
