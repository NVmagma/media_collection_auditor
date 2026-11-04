# Branch workflow

The active development branch is `feature/interface-api`. The project-default
branch remains `feature/unraid`; do not modify `main` or other protected branches
without explicit approval. Keep changes incremental and verify automated tests
and Actions before recommending a container update.

`json-cutover-verified-2026-11-04` preserves the accepted pre-cleanup source in Git.
Host backups and retained containers are independent of repository cleanup.
Production uses the serialized JSON worker. Publishing a versioned candidate does
not deploy Tower or move a floating production tag.
