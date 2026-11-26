# Dropify quarantine (staging only)

This is a manually installed must-use plugin candidate for a disposable WordPress environment, not a production security patch. It is deliberately outside wp-content and is not loaded or deployed by default. Do not activate Dropify on production.

For isolated testing only, block outbound traffic at the container/host level first, use synthetic data and no token, then copy bakata-dropify-guard.php to the staging wp-content/mu-plugins directory. Verify actual mount and execution order. The guard blocks the observed Dropi domains through WordPress HTTP API, forces TLS verification for those requests, disables the legacy autosync option and denies the observed AJAX actions. Generic AJAX action names may collide with other plugins; do not deploy this guard to a shared store. Remove the file only after deactivating Dropify and destroying or isolating the test environment.

Run `php scripts/test-dropify-guard.php` from the repository. The harness uses stubs, not WordPress. It does not demonstrate integration compatibility.

Remaining blockers: per-token sync settings, manual and bulk dispatch, direct HTTP clients and redirects from other hosts, publication on import, nonce/capability checks, token storage and request logging, HPOS and idempotency. The guard does not fix these; network isolation is mandatory. Do not connect a real token or remove the network block until the source patches and sandbox tests are reviewed. No API direct to Dropi is introduced.
