# Metadata-only orphan folders

The scanner checks inside every Movie and TV title directory for video files,
including nested season folders. A directory left after a manual Radarr/Sonarr
deletion can contain only Finder files, artwork, NFO files or subtitles. Such a
folder now gets a no-video/metadata explanation instead of being treated as an
ordinary title with unavailable Jellyfin protection.

## Detection and opt-in

Detection is always active. Cleanup is **disabled by default**. In Settings →
Safety, enable **Quarantine Orphan Metadata Folders**, read the warning, check the
acknowledgement and Apply Requested Settings. This is independent of permanent
Removal deletion; it never enables that option. Dry Run previews without saving
observations, creating quarantine directories or moving files.

For a live quarantine, all of the following must be true:

- A complete recursive inventory finds no video, disc image or stream pointer.
  Hidden and zero-byte videos still count as media. Common video signatures in
  incorrectly named metadata files also prevent cleanup.
- Only recognized sidecars or empty subdirectories remain. Unknown files,
  incomplete downloads, archives, links, hardlinks, special files, unreadable
  inventories and separate/nested mounts are preserved for review.
- Keep folders are never cleaned automatically.
- A complete Arr catalog has no record with the same title folder (including
  case/Unicode variants), matching path or overlapping parent/child path.
- Complete Jellyfin user/library reads verify the title is absent. An unmatched
  result from an incomplete request is not absence. Any remaining matching
  Jellyfin record, even an old protected record, prevents quarantine until the
  library is refreshed and absence can actually be verified.
- The same folder identity, contents and stage remain unchanged across live
  observations at least **24 hours apart**. Changes reset that observation clock.
  A video returning or a service becoming unavailable clears cleanup eligibility.
- Fresh independent Arr checks around a new Jellyfin read, current opt-in settings
  and a final filesystem recheck still agree immediately before the move.

Recognized video extensions include MKV, MP4, AVI, MOV, MPEG, WebM, disc formats
and STRM pointers. Known sidecars include NFO, common artwork/subtitle extensions,
`.DS_Store`, `Thumbs.db` and `desktop.ini`. Mac `._` files are metadata only when
valid bounded AppleDouble headers prove there is no data-fork entry. A file named
`._movie.mkv` with an invalid header remains protected as possible media. The
format check follows [RFC 1740, AppleDouble](https://www.rfc-editor.org/rfc/rfc1740.html).
Unknown metadata types are not guessed or deleted.

## Where the folder goes

Eligible metadata is atomically moved into:

```text
/media/.auditor-orphans/<recovery-id>/
```

`/media` here is the configured media root. The quarantine must be outside the
four lifecycle stages, on the same mount/device as the source and separate from
private appdata. No copy fallback or overwrite is permitted. The private root
has a version marker and restrictive permissions; an unrelated existing directory
is never adopted as quarantine.

Nothing is permanently deleted. The original title directory disappears from
its lifecycle stage, but all metadata bytes remain in quarantine. The JSON receipt
retains the original title, stage, identity and tracking dates. Only that title's
active lifecycle clocks are removed after the move is verified. Unknown tracking
fields and other titles' dates are preserved. Metadata moves share the existing
five actions per library / ten overall cap, the one-hour cooldown and the single
worker lock. They send no Arr writes or imports.

Activity/History distinguishes metadata quarantines from media moves and deletions.
Activity includes a recovery ID. To list recorded locations without dumping private
configuration or tracking contents, run after the scan finishes:

```bash
docker exec media_collection_auditor python -B -m app.json_orphan_quarantine list
```

These are historical receipts, not a live assertion that every archived file is
still present. Quarantine is never automatically purged. To return retained metadata,
disable cleanup and stop the auditor, then use the original and quarantine paths
to move the folder back only if the original location is still empty. Do not
merge it into or overwrite a replacement title. Old clocks remain in the receipt;
they are not automatically reactivated. A real video returning without a current
clock is discovered with a fresh date.

## Interruption and races

Intent is saved before rename; source/destination identities and contents are
verified before and after. A stopped attempt is never automatically replayed.
Operation Review can record an already completed metadata quarantine or cancel
an unperformed intent without moving files or sending Arr updates.

If content changes or video appears during the move, the scan pauses and the files
remain in quarantine. Operation Review offers explicit restoration to the original
empty location instead of declaring cleanup complete. Restoration uses atomic
no-overwrite rename. If another directory has appeared, it refuses to overwrite
it and retains the journal for investigation. Controller-death tests exercise this
recovery; no permanent deletion is used.
