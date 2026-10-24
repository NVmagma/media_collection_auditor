# SMB and mover scope review

Tower reported `smbd` running and one mover-related scheduled entry. NFS client
use does not establish that SMB is disabled. The operator has now agreed that
SMB shares and scheduled mover activity may pause in the initial maintenance
window, alongside Docker/NFS. Management and SSH must remain available. This is
a design decision; no settings, schedules, services or media have been changed.

## Source identities established

All three supplied hashes match public Unraid source at revision
`26eb1b5c1d547ddbf44a38e63956ba24f659098b`:

| Host path | Source | SHA-256 |
| --- | --- | --- |
| `/etc/rc.d/rc.samba` and its `/usr/local` alias | [rc.samba](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/etc/rc.d/rc.samba) | `3167690b93a05c223179c15679604931ac3aa96c3365c1131aa00f399a93ffee` |
| `/usr/local/sbin/mover` | [mover](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/sbin/mover) | `def6b33c2f8f4c8e85a93dd18dd6179234e05730d8cecfe292d6a3c416ec29fc` |
| `/usr/local/sbin/mover.old` | [mover.old](https://github.com/unraid/webgui/blob/26eb1b5c1d547ddbf44a38e63956ba24f659098b/sbin/mover.old) | `a7bf8bc106faf2b16714a5ab22db26c73397322d7ff11a7c09a1296f741e9548` |

The Samba script defaults to starting for missing/unrecognized actions; its
normal controls also cover restart, reload and update. Its startup launches
`smbd` and related discovery/domain processes. The guard must deny default
invocations too, and shutdown verification must account for existing processes
and handles rather than just blocking future script calls.

Both mover scripts call `/usr/libexec/unraid/move`. The newer script permits a
`MOVE_HELPER` override, so matching the script hash does not establish its full
execution environment or rule out another helper. The `.old` hash matches stock
Unraid here; its existence alone does not identify a tuning plugin. These files
were downloaded into temporary review files and read, never executed. Source
identity is compatibility evidence, not a writer-exclusion permit.

## Probe correction

The selected preference observer previously rejected terminal CR characters and
unquoted yes/no assignments, although the NFS candidate parser already supports
canonical CRLF and quoted/unquoted forms. The read-only probe now handles these
forms and reports assignment and terminal-CR counts without printing raw settings.
Duplicates, noncanonical values and executable-looking assignments remain
unverified. No live source file is normalized or rewritten. A new Tower snapshot
is still needed to establish why its earlier preferences were unverified; CRLF
is a reproduced explanation, not an asserted fact about that file.

The probe also fingerprints the move helper and observes Samba child/helper
process names. Neither process absence nor a matching hash grants work authority.
Raw cron commands and unrelated settings/credentials stay redacted.

## Disposable guard extension and remaining acceptance

The fixed fake-host routes now include Docker, NFS, Samba, both mover scripts
and the default move helper. The current complete guest fixture checks 49 denied
invocations, including Samba's missing/unrecognized actions and a synthetic
stdin payload for the helper. No real helper is executed: every unguarded fixture
entry is an inert stub. Partial installation still rejects the complete binding,
and retained requests remain non-adoptable.

The earlier two-service 22-invocation Linux/SIGKILL acceptance remains historical
component evidence. The expanded six-route mount fixture now also passed actual local Linux mount
and SIGKILL acceptance: 49 complete-case and 10 partial-case denials before and
after installer death, with retained request/originals unchanged and restoration
denied. See the [acceptance record](sqlite-offline-dispatch-rehearsal.md). No
additional Linux VM was downloaded or built; a new private container used a cached
image, no host mounts and no network. Actual Unraid installation, all-mode
boot coverage, quiescence of existing writers and production verification remain
open. No new production authority is introduced.
