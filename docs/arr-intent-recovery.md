# Operation recovery

An unresolved operation pauses new scans. Open **Operation recovery** to collect
fresh local and GET-only Arr observations. Review the exact fingerprint before
applying a resolution. No move or remote update is automatically replayed.

If the directory move is complete and Arr already matches the intended path and
monitoring state, acknowledge that verified outcome without another PUT. If a
remaining Arr update is needed, review and explicitly authorize that single
update. Contradictory filesystem evidence, changed content, conflicting identities
or unavailable protection keep recovery blocked.

A move that did not happen may be cancelled only after verifying the unique
unchanged source and missing destination. A completed rename is recorded without
renaming again. Lifecycle clocks from a completed move are retained even when
remote acknowledgement was lost. Arr import intents have their own GET-only
review on **Arr imports**.
