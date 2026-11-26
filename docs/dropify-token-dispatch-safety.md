# Dropify: token handling and dispatch reservation

The version-pinned ZIP builder now invokes an additional source transformation. No plugin or token is deployed by this PR.

Token creation uses POST on the settings screen with capability and nonce validation, a masked input, bounded fields and manual sync defaults. The table masks tokens and no longer embeds the token row in its delete link; the catalog store object contains ID and name only. Token, store, ID and token-metadata lookup queries are parameterized. This is exposure reduction, not encryption: Dropify still stores credentials in its table and product metadata, and other settings and legacy paths need review.

All observed order send paths converge at OrdersModel::save. Immediately before its outbound order POST, a fresh WooCommerce CRUD metadata read checks existing references/status, then a direct INSERT reserves a unique option_name in the current site's wp_options (non-autoloaded). No automatic release, including on timeout, crash or failed response. Fail closed if the reservation cannot be persisted. This is local at-most-one-attempt containment, not provider-side idempotency or guaranteed delivery. Never delete a reservation automatically; reconcile with Dropi via its authorized UI before any manual remediation. Backups/restores, database transactions, legacy orders, concurrency with unpatched code, and recovery need explicit testing. The change does not prevent every other provider mutation. Order requests use a 30-second timeout and generic error strings instead of remote message details.

## Verification

Second-stage transformation file hash matched the GitHub blob. Applied these transformations alone to the supplied original ZIP: five files changed, 35 PHP files passed syntax checks on PHP 8.4.24; 12 assertions passed using database and WooCommerce stubs. No network or real data. This does not establish full combined-build or WordPress integration compatibility. Run both existing and new suites against the combined output:

    python3 scripts/harden-dropify.py original.zip patched.zip
    unzip patched.zip -d isolated
    php scripts/test-dropify-hardening.php isolated/wc-dropi-integration
    php scripts/test-dropify-dispatch.php isolated/wc-dropi-integration

Remaining: test full build, PHP 8.3, real MariaDB concurrent inserts and durability, WordPress token form and catalog UI, token encryption/rotation and all remaining leaks, authorization of bulk and manual paths, HPOS UI and end-to-end integration. Keep plugin inactive and staging egress blocked. No new direct API.
