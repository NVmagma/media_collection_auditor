# Branch workflow

The release branch is `main` and the default development branch is
`feature/unraid`. Changes to protected branches require explicit approval. Keep changes incremental and verify automated tests
and Actions before recommending a container update.

`json-cutover-verified-2026-11-04` preserves the accepted pre-cleanup source in Git.
Host backups and retained containers are independent of repository cleanup.
Production uses the serialized JSON worker. Publishing a versioned candidate does
not deploy Tower or move a floating production tag.
