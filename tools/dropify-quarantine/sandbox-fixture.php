<?php
/**
 * Plugin Name: Bakatá isolated catalog fixture
 * Test-only MU plugin, never packaged with Dropify.
 */
defined('ABSPATH') || exit;
// During the CLI-only fresh install, home_url() is not yet backed by options.
// This branch can only deny HTTP; it never defines catalog approvals or reads options.
if (getenv('BAKATA_RESEARCH_BOOTSTRAP') === '1') {
    if (getenv('BAKATA_RESEARCH_FIXTURE') !== '1' || getenv('BAKATA_DROPIFY_SANDBOX') !== '1'
        || PHP_SAPI !== 'cli' || !defined('WP_CLI') || WP_CLI !== true
        || wp_get_environment_type() !== 'staging'
        || !defined('WP_HOME') || WP_HOME !== 'http://localhost'
        || !defined('WP_SITEURL') || WP_SITEURL !== 'http://localhost'
        || !defined('DB_HOST') || DB_HOST !== '127.0.0.1:3306'
        || !defined('DB_NAME') || DB_NAME !== 'fixture') {
        throw new RuntimeException('Refusing research bootstrap outside isolated CLI fixture.');
    }
    add_filter('pre_http_request', static function () {
        return new WP_Error('bk_fixture_bootstrap_offline','All external HTTP blocked during bootstrap.');
    }, PHP_INT_MAX, 3);
    return;
}
if (getenv('BAKATA_DROPIFY_SANDBOX') !== '1' || wp_get_environment_type() !== 'staging'
    || home_url() !== 'http://localhost') {
    throw new RuntimeException('Refusing catalog fixture outside the disposable sandbox.');
}

if (get_option('bk_fixture_enabled') === '1') {
    define('BAKATA_DROPIFY_CATALOG_READ', true);
    define('BAKATA_DROPIFY_CATALOG_APPROVAL_REF', 'ci-wordpress-approval');
    define('BAKATA_DROPIFY_CATALOG_APPROVED_UNTIL', (int)get_option('bk_fixture_expiry'));
    define('BAKATA_DROPIFY_CATALOG_APPROVED_STORE', '7');
    define('BAKATA_DROPIFY_CATALOG_APPROVED_OFFSET', 0);
    define('BAKATA_DROPIFY_CATALOG_APPROVED_QUERY', 'fixture');
}

if (get_option('bk_fixture_batch_enabled') === '1') {
    define('BAKATA_DROPIFY_BATCH_ENABLED',true);
    define('BAKATA_DROPIFY_BATCH_HOST','localhost');
    $run='ci-paged-capture';
    if (getenv('BAKATA_RESEARCH_PERSIST')==='1') {
        $run=getenv('BAKATA_RESEARCH_RUN');
        if (getenv('BAKATA_RESEARCH_FIXTURE')!=='1' || !is_string($run) || !preg_match('/\Afixture-[A-Za-z0-9_-]{1,56}\z/D',$run)) {
            throw new RuntimeException('Invalid synthetic persistence identity.');
        }
    }
    define('BAKATA_DROPIFY_BATCH_RUN',$run);
    define('BAKATA_DROPIFY_BATCH_STORE','7');
    define('BAKATA_DROPIFY_BATCH_FIRST',1);
    define('BAKATA_DROPIFY_BATCH_LAST',3);
    define('BAKATA_DROPIFY_BATCH_UNTIL',(int)get_option('bk_fixture_batch_expiry'));
}

// Every WordPress HTTP request is intercepted. The Docker network independently
// prevents egress even for code that does not use the WordPress HTTP API.
add_filter('pre_http_request', static function ($pre, $args, $url) {
    if ($url !== 'https://api.dropi.co/integrations/products/index') {
        if (preg_match('/dropi|cloudfront/i', $url)) {
            update_option('bk_fixture_unexpected_provider', '1', false);
        }
        return new WP_Error('bk_fixture_offline', 'External traffic blocked in sandbox.');
    }
    $count = (int)get_option('bk_fixture_http_calls', 0) + 1;
    update_option('bk_fixture_http_calls', (string)$count, false);
    if (get_option('bk_fixture_batch_enabled') === '1') {
        $body=json_decode($args['body']??'',true);
        $approval='batch-'.hash('sha256',BAKATA_DROPIFY_BATCH_RUN.':'.$count);
        $receipt='bk_dropify_catalog_'.hash('sha256',$approval);
        if (!defined('WP_CLI') || !WP_CLI || !in_array($count,[1,2],true)
            || get_option($receipt)===false || ($body['startData']??null)!==($count-1)*10
            || ($body['pageSize']??null)!==10 || ($body['keywords']??null)!==''
            || ($body['order_by']??null)!=='id' || ($body['order_type']??null)!=='asc'
            || ($args['method']??null)!=='POST' || ($args['sslverify']??null)!==true
            || ($args['redirection']??null)!==0 || ($args['reject_unsafe_urls']??null)!==true
            || ($args['timeout']??null)!==15 || ($args['limit_response_size']??null)!==524288
            || ($args['headers']['dropi-integration-key']??'')!=='ci-only-token-canary') {
            update_option('bk_fixture_bad_request','1',false);
            return new WP_Error('bk_fixture_bad_request','Invalid paged fixture request.');
        }
        // In the persistent rehearsal, validate the *actual* WP HTTP args
        // against the pilot policy before returning the offline response.
        if (getenv('BAKATA_RESEARCH_PERSIST')==='1') {
            require_once '/opt/bakata/catalog-egress-policy.php';
            $file=sprintf('/exchange/request-%04d.json',$count);
            if (is_link($file) || !is_file($file) || filesize($file)>4096) {
                update_option('bk_fixture_bad_request','1',false);
                return new WP_Error('bk_fixture_scope','Missing fixture reservation.');
            }
            $request=json_decode(file_get_contents($file),true);
            if (!is_array($request) || ($request['run']??null)!==BAKATA_DROPIFY_BATCH_RUN
                || ($request['store']??null)!=='7' || ($request['page']??null)!==$count
                || ($request['until']??null)!==BAKATA_DROPIFY_BATCH_UNTIL
                || !is_int($request['reserved_at']??null) || $request['reserved_at']>time()
                || time()-$request['reserved_at']>45
                || !is_dir(sprintf('/exchange/claim-%04d',$count))) {
                update_option('bk_fixture_bad_request','1',false);
                return new WP_Error('bk_fixture_scope','Invalid fixture reservation.');
            }
            // Only the synthetic adapter maps its fixture identity to a pilot
            // policy test identity; the original ledger/approval stays fixture.
            $scope=['run'=>'pilot-rehearsal','store'=>'7','page'=>$count,
                'until'=>$request['until'],'attempt'=>$request['attempt']??null];
            if (!bakata_research_catalog_request_allowed($url,$args,$scope,'ci-only-token-canary',time())) {
                update_option('bk_fixture_bad_request','1',false);
                return new WP_Error('bk_fixture_policy','Pilot HTTP policy denied fixture.');
            }
            update_option('bk_fixture_policy_passes',(string)((int)get_option('bk_fixture_policy_passes',0)+1),false);
        }
        $items=[];
        for ($i=0;$i<($count===1?10:3);$i++) {
            $id=1000+($count-1)*10+$i;
            $items[]=['id'=>$id,'name'=>'Fixture product '.$id,'sku'=>'00'.$id,'type'=>'SIMPLE',
                'stock'=>5,'sale_price'=>'7000.25','suggested_price'=>17000,
                'description'=>'opaque-canary','user'=>['name'=>'Fixture warehouse','email'=>'private-canary']];
        }
        return ['headers'=>[],'body'=>wp_json_encode(['isSuccess'=>true,'objects'=>$items]),
            'response'=>['code'=>200,'message'=>'OK'],'cookies'=>[],'filename'=>null];
    }
    $receipt = 'bk_dropify_catalog_' . hash('sha256', 'ci-wordpress-approval');
    $body = json_decode($args['body'] ?? '', true);
    if ($count !== 1 || get_option($receipt) === false
        || ($args['method'] ?? null) !== 'POST' || ($args['sslverify'] ?? null) !== true
        || ($args['redirection'] ?? null) !== 0 || ($args['reject_unsafe_urls'] ?? null) !== true
        || ($args['timeout'] ?? null) !== 15 || ($args['limit_response_size'] ?? null) !== 524288
        || ($args['headers']['dropi-integration-key'] ?? '') !== 'ci-only-token-canary'
        || ($body['startData'] ?? null) !== 0 || ($body['pageSize'] ?? null) !== 10
        || ($body['keywords'] ?? null) !== 'fixture') {
        update_option('bk_fixture_bad_request', '1', false);
        return new WP_Error('bk_fixture_bad_request', 'Invalid fixture request.');
    }
    $item = ['id'=>96,'name'=>'Fixture <script>unsafe</script>','sku'=>'025216',
        'type'=>'SIMPLE','stock'=>5,'sale_price'=>'7000.25','suggested_price'=>17000,
        'description'=>'opaque-canary','user'=>['name'=>'Fixture warehouse','email'=>'private-canary']];
    return ['headers'=>[], 'body'=>wp_json_encode(['isSuccess'=>true,'objects'=>[$item]]),
        'response'=>['code'=>200,'message'=>'OK'],'cookies'=>[], 'filename'=>null];
}, PHP_INT_MAX, 3);

add_action('admin_init', static function () {
    if (($_GET['page'] ?? '') !== 'dropi-products') { return; }
    foreach (['wp_ajax_import','wp_ajax_nopriv_import','wp_ajax_get-woo-products',
        'wp_ajax_nopriv_get-woo-products','wp_ajax_send_order_to_dropi',
        'wp_ajax_nopriv_send_order_to_dropi'] as $hook) {
        if (has_action($hook)) {
            update_option('bk_fixture_unsafe_hook', '1', false);
            wp_die('Unexpected commercial action registered.');
        }
    }
});
