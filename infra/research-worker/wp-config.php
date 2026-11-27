<?php
// Fixture-only: deliberately no secret injection, remote DB host or production URL.
if (PHP_SAPI !== 'cli' || getenv('BAKATA_RESEARCH_FIXTURE') !== '1'
    || getenv('BAKATA_DROPIFY_SANDBOX') !== '1') {
    exit(1);
}
define('DB_NAME','fixture');
define('DB_USER','fixture');
define('DB_PASSWORD','ci-research-only');
define('DB_HOST','127.0.0.1:3306');
define('DB_CHARSET','utf8mb4');
define('DB_COLLATE','');
$table_prefix='wp_';
define('WP_HOME','http://localhost');
define('WP_SITEURL','http://localhost');
define('WP_ENVIRONMENT_TYPE','staging');
define('DISABLE_WP_CRON',true);
define('DISALLOW_FILE_MODS',true);
define('DISALLOW_FILE_EDIT',true);
define('AUTOMATIC_UPDATER_DISABLED',true);
define('WP_DEBUG',false);
define('WP_DEBUG_DISPLAY',false);
define('WP_DEBUG_LOG',false);
// No HTTP sessions exist. Random per-process keys rather than reusable credentials.
foreach (['AUTH_KEY','SECURE_AUTH_KEY','LOGGED_IN_KEY','NONCE_KEY',
    'AUTH_SALT','SECURE_AUTH_SALT','LOGGED_IN_SALT','NONCE_SALT'] as $key) {
    define($key,bin2hex(random_bytes(32)));
}
define('ABSPATH',__DIR__.'/');
require_once ABSPATH.'wp-settings.php';
