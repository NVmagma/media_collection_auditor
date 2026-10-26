# Bounded isolated copy completion batches

`run_isolated_copy_batch` is a Python-only marked disposable-lab entry point.
It does not run from the production audit, dashboard, CLI or scheduler. It adds
bounded orchestration around the existing live-witness copy completion flow;
it does not establish production writer exclusion or activate SQLite.

The caller supplies an ordered list of explicit title jobs, the current SQLite
revision, lifecycle thresholds, trusted read-only collection transport and a
nonnegative integer `max_actions_per_run`. Booleans are not accepted as caps.
Each job specifies operation ID, media key, title folder, Movie/Series type and
optionally the existing validated Arr queue request. The complete selection is
deep-copied and validated before collection, even jobs beyond the cap. Duplicate
keys, operation IDs and physical folders, unsafe names, unexpected fields,
invalid Arr identities, ambiguous Waiting/Holding clocks, selected queued Arr work,
reused retained-source operations and unresolved intents stop preflight.

One existing cooperating-runner lock remains held for the entire batch. The
internal single-title path shares that binding; public single-title wrappers
cannot accept the private lock callback. Each title still performs full hashes,
paired fresh protections, path/metadata verification, intent-before-action and
atomic clock/queue/ledger/intent reconciliation. A returned confirmed revision
binds the next title; an unexpected SQLite writer stops it before collection.

The cap counts *attempted titles*, including Keep candidates, rather than only
successful moves. A zero cap performs no collection or media action. This is
more conservative than the JSON production hold/delete/prune cap; it does not
change that cap or read production environment settings. Each selected title
may contain many files and requires two directory renames. The cap is not a
byte budget, syscall limit or persistent quota across separate invocations.

Any failed or uncertain title stops the remaining batch. Earlier confirmed
commits remain committed; no rollback, retry, Arr delivery, source cleanup or
permanent deletion follows. The aggregate report distinguishes confirmed prior
completions, attempted/unattempted counts and an unverified last attempt. An
exception can follow a successful final SQLite commit, so a zero confirmed count
does not prove that no title committed. Report counters never grant retry or
recovery authority. Inspect the retained lab and SQLite state before explicitly
selecting another batch at a current revision. Pending state blocks that batch.

Reports omit title names, paths, service details and raw exception text. Loss of
the root/marker/database binding can also cause the enclosing lock to raise;
that failure stops execution rather than producing a trusted batch outcome.
Native tests require actual atomic no-replace publication and quarantine. On
unsupported paths the general capability case requires a prepared pending
publication intent with the original retained and later titles untouched.


Holding sources can now be selected alongside Waiting sources. Each title is
still selected only once per batch: a newly held Waiting title is not processed
again into Removal during the same invocation. Holding candidates follow the
existing protected rescue/age policy; the batch cap also counts those attempts.
Removal/Keep sources remain excluded, and no deletion action exists.
