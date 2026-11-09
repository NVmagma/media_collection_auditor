# Operation recovery

A pending operation can pause new scans. Open **Operation Review** from the
review/log links and collect current local evidence and fresh Arr reads. Apply
only the resolution offered for that exact fingerprint. Successful recovery
preserves the scan cooldown and historical attempt result.

| Pending operation | Available resolution |
| --- | --- |
| Whole-title move | Record an already completed rename, or cancel a verified unperformed move. |
| Arr path/monitoring sync | Acknowledge two matching reads; when offered, explicitly complete one reviewed remaining update. |
| Existing-folder import | Open Arr Imports and verify the pending import using GETs. |
| Whole-title deletion | Record verified absence, or cancel only when no DELETE dispatch began and the original state is intact. |
| Metadata quarantine | Record a verified quarantine, cancel an unperformed move, or restore newly protected content when offered. |
| TV season move | Acknowledge completed staging/restoration after directory/content checks and two matching Sonarr monitoring reads. |
| TV season deletion | Manual review required; the browser does not clear or replay it. |

An HTTP acknowledgment alone is insufficient. Changed files, ambiguous locations,
endpoint/identity changes, or unavailable services keep the operation blocked.
Never delete a journal or edit JSON clocks to force a replay. A retained deletion
intent may correspond to a partial or irreversible outcome.

Whole-title recovery does not repeat a directory rename. Completing a remaining
Arr update is a separate explicit action. Season-move acknowledgment sends no
monitoring update. See [TV season retention](tv-season-retention.md) and
[Removal deletion](removal-deletion.md) for their specific interruption rules.
