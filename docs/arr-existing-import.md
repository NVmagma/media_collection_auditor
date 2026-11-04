# Register an existing folder in Radarr or Sonarr

Open **Arr imports**, choose the library and existing folder, select the correct
provider match and a currently available quality profile, then review the plan.
The integration supports Radarr 6 and Sonarr 4.

Imports are explicit. They register an existing folder **unmonitored**, with
movie/episode searches disabled. TV seasons start unmonitored and new-item
monitoring is disabled. No files move and lifecycle clocks do not reset.

Review includes the stage root, unique folder/provider identity, profile and
content fingerprint. A changed folder, tracking document, profile, settings or
remote catalog invalidates the review. A durable JSON intent precedes the single
POST. A lost response retains that intent and blocks another create attempt.
Use the pending-import review for GET-only reconciliation; never blindly repeat
the POST. Two exact remote readbacks are required before clearing the intent.
