<?php
declare(strict_types=1);

use Bakata\Core\Webhooks\WpReceiptLedger;

function verify_race_environment(): void
{
    global $wpdb;
    $marker = getenv('BAKATA_RACE_MARKER');
    $address = gethostbyname('db');
    if (getenv('BAKATA_RECEIPT_RACE') !== '1' || $wpdb->dbname !== 'bakata_receipt_race'
        || DB_HOST !== 'db:3306' || !is_string($marker) || !preg_match('/\A[a-f0-9]{64}\z/D', $marker)
        || !filter_var($address, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)
        || filter_var($address, FILTER_VALIDATE_IP, FILTER_FLAG_NO_PRIV_RANGE | FILTER_FLAG_NO_RES_RANGE) !== false) {
        throw new RuntimeException('Refusing non-isolated database destination.');
    }
    $value = $wpdb->get_var('SELECT marker FROM bakata_race_isolation_marker LIMIT 1');
    if (!is_string($value) || !hash_equals($marker, $value)) {
        throw new RuntimeException('Disposable database marker missing or mismatched.');
    }
}

// Run via WP-CLI in a disposable WordPress installation, never a store database.
if (($argv[1] ?? '') === '--receipt-worker') {
    require getcwd() . '/wp-load.php';
    require_once WP_PLUGIN_DIR . '/bakata-core/src/Webhooks/ReceiptLedger.php';
    verify_race_environment();
    [$script, $mode, $dir, $index, $key, $fingerprint] = $argv;
    // Force connection establishment before announcing readiness.
    if ($wpdb->get_var('SELECT CONNECTION_ID()') === null) {
        throw new RuntimeException('Connection failed.');
    }
    file_put_contents("$dir/ready-$index", (string) $wpdb->get_var('SELECT CONNECTION_ID()'));
    $deadline = microtime(true) + 30;
    while (!file_exists("$dir/go")) {
        if (microtime(true) > $deadline) { throw new RuntimeException('Barrier timeout.'); }
        usleep(1000);
        clearstatcache();
    }
    try {
        $result = (new WpReceiptLedger($wpdb))->claim($key, $fingerprint, new DateTimeImmutable('now'))->value;
    } catch (RuntimeException $e) {
        if ($e->getMessage() !== 'Receipt identity conflict.') { throw $e; }
        $result = 'conflict';
    }
    echo $result;
    exit;
}

global $wpdb;
if (!defined('WP_CLI') || !WP_CLI
    || !in_array(wp_parse_url(home_url(), PHP_URL_HOST), ['localhost', '127.0.0.1'], true)) {
    throw new RuntimeException('Refusing race outside disposable local WordPress.');
}
verify_race_environment();
require_once WP_PLUGIN_DIR . '/bakata-core/src/Webhooks/ReceiptLedger.php';
$admins = get_users(['role' => 'administrator', 'number' => 1, 'fields' => 'ID']);
if (!$admins) { throw new RuntimeException('Administrator missing.'); }
wp_set_current_user((int) $admins[0]);
(new WpReceiptLedger($wpdb))->install();
$table = $wpdb->prefix . 'bakata_receipts_v1';
$workers = 8;
$rounds = 5;

foreach (['same', 'mixed'] as $scenario) {
    for ($round = 0; $round < $rounds; $round++) {
        $dir = sys_get_temp_dir() . '/bakata-receipt-race-' . bin2hex(random_bytes(12));
        if (!mkdir($dir, 0700)) { throw new RuntimeException('Cannot create barrier.'); }
        $key = hash('sha256', random_bytes(32));
        $fingerprints = [hash('sha256', 'synthetic-a'), hash('sha256', 'synthetic-b')];
        $processes = [];
        try {
            for ($i = 0; $i < $workers; $i++) {
                $fp = $fingerprints[$scenario === 'same' ? 0 : $i % 2];
                $process = proc_open(
                    [PHP_BINARY, __FILE__, '--receipt-worker', $dir, (string) $i, $key, $fp],
                    [0 => ['pipe', 'r'], 1 => ['file', "$dir/out-$i", 'w'], 2 => ['file', "$dir/err-$i", 'w']],
                    $pipes,
                    getcwd()
                );
                if (!is_resource($process)) { throw new RuntimeException('Worker start failed.'); }
                fclose($pipes[0]);
                $processes[$i] = $process;
            }
            $deadline = microtime(true) + 30;
            do {
                $ready = glob("$dir/ready-*");
                if (count($ready) === $workers) { break; }
                if (microtime(true) > $deadline) { throw new RuntimeException('Workers not ready.'); }
                usleep(10000);
            } while (true);
            $connections = array_map('file_get_contents', $ready);
            if (count(array_unique($connections)) !== $workers) {
                throw new RuntimeException('Workers do not have independent connections.');
            }
            file_put_contents("$dir/go", 'go');
            $deadline = microtime(true) + 30;
            while ($processes) {
                foreach ($processes as $i => $process) {
                    $status = proc_get_status($process);
                    if ($status['running']) { continue; }
                    $exit = $status['exitcode'];
                    proc_close($process);
                    unset($processes[$i]);
                    if ($exit !== 0) { throw new RuntimeException("Worker $i failed: " . file_get_contents("$dir/err-$i")); }
                }
                if ($processes && microtime(true) > $deadline) { throw new RuntimeException('Worker execution timeout.'); }
                if ($processes) { usleep(10000); }
            }
            $rows = $wpdb->get_results($wpdb->prepare("SELECT fingerprint FROM $table WHERE receipt_key = %s", $key), ARRAY_A);
            if (count($rows) !== 1) { throw new RuntimeException('Expected exactly one receipt row.'); }
            $winner = $rows[0]['fingerprint'];
            if (!in_array($winner, $fingerprints, true)) { throw new RuntimeException('Unexpected fingerprint.'); }
            $recorded = 0;
            for ($i = 0; $i < $workers; $i++) {
                $result = trim(file_get_contents("$dir/out-$i"));
                $fp = $fingerprints[$scenario === 'same' ? 0 : $i % 2];
                if ($result === 'recorded' && $fp === $winner) { $recorded++; continue; }
                if ($result !== ($fp === $winner ? 'duplicate' : 'conflict')) {
                    throw new RuntimeException("Unexpected worker result: $result");
                }
            }
            if ($recorded !== 1) { throw new RuntimeException('Expected exactly one recorded.'); }
            echo "$scenario round " . ($round + 1) . ": $workers workers, one recorded, one row; outcomes verified.\n";
        } finally {
            // Terminate only children created by this invocation.
            file_put_contents("$dir/go", 'go');
            foreach ($processes as $process) { proc_terminate($process, 9); }
            foreach ($processes as $process) { proc_close($process); }
            foreach (glob("$dir/*") as $file) { unlink($file); }
            rmdir($dir);
        }
    }
}
