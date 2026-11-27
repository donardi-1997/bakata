<?php
// Standalone fixture guard test; no WordPress or provider access.
declare(strict_types=1);
define('ABSPATH',__DIR__);
define('WP_CLI',true);
define('WP_HOME','http://localhost');
define('WP_SITEURL','http://localhost');
define('DB_HOST','127.0.0.1:3306');
define('DB_NAME','fixture');
putenv('BAKATA_RESEARCH_BOOTSTRAP=1');
putenv('BAKATA_RESEARCH_FIXTURE=1');
putenv('BAKATA_DROPIFY_SANDBOX=1');
$scenario=$argv[1]??'ok';
if ($scenario==='missing-flag') putenv('BAKATA_RESEARCH_FIXTURE');
function wp_get_environment_type() { return $GLOBALS['scenario']==='production'?'production':'staging'; }
class WP_Error { public function __construct(public string $code,public string $message) {} }
function add_filter($name,$fn,$priority,$args) {
    if ($name!=='pre_http_request' || $priority!==PHP_INT_MAX || $args!==3) throw new LogicException('Invalid filter');
    $GLOBALS['filter']=$fn;
}
// Deliberately no home_url(), get_option() or update_option() stubs.
// The fresh-install branch must never access an uninitialized options table.
try {
    require __DIR__.'/../tools/dropify-quarantine/sandbox-fixture.php';
} catch (RuntimeException $e) {
    if ($scenario==='ok') throw $e;
    if (isset($GLOBALS['filter'])) throw new LogicException('Unexpected filter on rejected bootstrap');
    exit(0);
}
if ($scenario!=='ok' || !isset($GLOBALS['filter']) || defined('BAKATA_DROPIFY_CATALOG_READ') || defined('BAKATA_DROPIFY_BATCH_ENABLED')) throw new LogicException('Invalid bootstrap scope');
foreach (['https://api.dropi.co/integrations/products/index','https://example.invalid'] as $url) {
    $result=($GLOBALS['filter'])(false,[],$url);
    if (!$result instanceof WP_Error || $result->code!=='bk_fixture_bootstrap_offline') throw new LogicException('Network not blocked');
}
echo "Research bootstrap denies every HTTP request without reading options.\n";
