<?php
// WP-CLI eval-file only. Requires the catalog-only build, never the original plugin.
defined('ABSPATH') || exit;
if (!defined('WP_CLI') || !WP_CLI) { exit; }
try {
    if (count($args)!==3 || !is_string($args[0]) || !is_string($args[1])
        || !preg_match('/\A[1-9][0-9]{0,2}\z/D',$args[2]??'')) {
        throw new RuntimeException('Invalid arguments.');
    }
    [$run,$store,$pageRaw]=$args; $page=(int)$pageRaw;
    require_once ABSPATH.'wp-admin/includes/plugin.php';
    if (!is_plugin_active('wc-dropi-integration/wc-dropi-integration.php')
        || !function_exists('bakata_catalog_batch_scope')
        || !bakata_catalog_batch_scope($run,$store,$page)) {
        throw new RuntimeException('Isolated staging catalog build and approval required.');
    }
    $scope=['BAKATA_DROPIFY_CATALOG_READ'=>true,
        'BAKATA_DROPIFY_CATALOG_APPROVAL_REF'=>bakata_catalog_batch_approval($run,$page),
        'BAKATA_DROPIFY_CATALOG_APPROVED_UNTIL'=>BAKATA_DROPIFY_BATCH_UNTIL,
        'BAKATA_DROPIFY_CATALOG_APPROVED_STORE'=>$store,
        'BAKATA_DROPIFY_CATALOG_APPROVED_OFFSET'=>bakata_catalog_offset($page,10),
        'BAKATA_DROPIFY_CATALOG_APPROVED_QUERY'=>''];
    foreach ($scope as $key=>$value) {
        if (defined($key)) { throw new RuntimeException('Conflicting authorization.'); }
        define($key,$value);
    }
    global $wpdb;
    $lock='bk_catalog_batch_'.substr(hash('sha256',DB_NAME.':'.$wpdb->prefix),0,40);
    if ((string)$wpdb->get_var($wpdb->prepare('SELECT GET_LOCK(%s, 0)',$lock))!=='1') {
        throw new RuntimeException('Catalog batch busy.');
    }
    try {
        if ($page>BAKATA_DROPIFY_BATCH_FIRST) {
            $prior='bk_dropify_batch_success_'.hash('sha256',bakata_catalog_batch_approval($run,$page-1));
            $receipt=$wpdb->get_var($wpdb->prepare("SELECT option_value FROM $wpdb->options WHERE option_name=%s",$prior));
            $previous=is_string($receipt)?json_decode($receipt,true):null;
            if (!is_array($previous) || ($previous['store']??null)!==$store || ($previous['offset']??null)!==($page-2)*10 || ($previous['rows']??null)!==10
                || !is_string($previous['at']??null) || ($at=strtotime($previous['at']))===false || time()-$at<10) {
                throw new RuntimeException('Previous reservation or cooldown missing.');
            }
        }
        $response=JPIODFW_ProductsModel::GetInstance()->getProducts(10,($page-1)*10,'','id','asc',null,null,null,null,null,$store,[]);
        if (!is_array($response) || !isset($response['objects'])) { throw new RuntimeException('Catalog blocked.'); }
        if ((string)$wpdb->get_var($wpdb->prepare('SELECT IS_USED_LOCK(%s) = CONNECTION_ID()',$lock))!=='1') {
            throw new RuntimeException('Reservation lock lost.');
        }
        $snapshot=bakata_catalog_project($response['objects'],$store,$page,10,$scope['BAKATA_DROPIFY_CATALOG_APPROVAL_REF'],'');
        $json=wp_json_encode($snapshot,JSON_UNESCAPED_UNICODE);
        if (!is_string($json) || strlen($json)>262144) { throw new RuntimeException('Invalid projected response.'); }
        $success='bk_dropify_batch_success_'.hash('sha256',$scope['BAKATA_DROPIFY_CATALOG_APPROVAL_REF']);
        $value=wp_json_encode(['store'=>$store,'offset'=>($page-1)*10,'rows'=>count($snapshot['rows']),'at'=>gmdate(DATE_ATOM)]);
        if (!is_string($value) || $wpdb->insert($wpdb->options,['option_name'=>$success,'option_value'=>$value,'autoload'=>'no'],['%s','%s','%s'])!==1) {
            throw new RuntimeException('Cannot record projected page.');
        }
    } finally { $wpdb->get_var($wpdb->prepare('SELECT RELEASE_LOCK(%s)',$lock)); }
    WP_CLI::line($json);
} catch (Throwable $e) {
    WP_CLI::error('Catalog page blocked or uncertain; do not retry automatically.');
}
