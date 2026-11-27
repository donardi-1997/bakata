<?php
declare(strict_types=1);
// Executed inside the isolated WordPress container, not against dev.
if (getenv('BAKATA_DROPIFY_SANDBOX') !== '1') { throw new RuntimeException('Fixture required'); }
$mode=$argv[1]??'';
if (!in_array($mode,['disabled','enabled','subscriber','invalid-nonce'],true)) { throw new RuntimeException('Invalid mode'); }
function ck(bool $ok, string $label): void {
    if (!$ok) { throw new RuntimeException('Sandbox assertion failed: '.$label); }
}
$jar=tempnam('/tmp','bk-cookie-');
try {
    $http=curl_init();
    curl_setopt_array($http,[CURLOPT_RETURNTRANSFER=>true,CURLOPT_FOLLOWLOCATION=>true,
        CURLOPT_MAXREDIRS=>5,CURLOPT_PROTOCOLS=>CURLPROTO_HTTP,CURLOPT_REDIR_PROTOCOLS=>CURLPROTO_HTTP,
        CURLOPT_TIMEOUT=>30,CURLOPT_COOKIEFILE=>$jar,CURLOPT_COOKIEJAR=>$jar]);
    $request=static function (string $path, ?array $post=null) use ($http): array {
        curl_setopt($http,CURLOPT_URL,'http://localhost'.$path);
        // Follow login redirects only; never mask an admin POST's status.
        curl_setopt($http,CURLOPT_FOLLOWLOCATION,$path==='/wp-login.php');
        curl_setopt($http,CURLOPT_POST,$post!==null);
        if ($post!==null) { curl_setopt($http,CURLOPT_POSTFIELDS,http_build_query($post)); }
        else { curl_setopt($http,CURLOPT_HTTPGET,true); }
        $body=curl_exec($http);
        $status=curl_getinfo($http,CURLINFO_RESPONSE_CODE);
        ck(is_string($body),'HTTP response');
        ck(str_starts_with(curl_getinfo($http,CURLINFO_EFFECTIVE_URL),'http://localhost/'),'local destination');
        ck(!str_contains($body,'ci-only-token-canary') && !str_contains($body,'private-canary')
            && !str_contains($body,'opaque-canary'),'no fixture secret or opaque fields');
        return [$status,$body];
    };
    $user=$mode==='subscriber'?'sandbox_reader':'sandbox_admin';
    $request('/wp-login.php');
    $request('/wp-login.php',['log'=>$user,'pwd'=>'ci-sandbox-only-password-2026','wp-submit'=>'Log In',
        'redirect_to'=>'http://localhost/wp-admin/','testcookie'=>'1']);
    $path='/wp-admin/admin.php?page=dropi-products';
    [$status,$body]=$request($path);
    if ($mode==='subscriber') {
        ck($status===403 && !str_contains($body,'bk_catalog_read'),'subscriber denied');
    } elseif ($mode==='disabled') {
        ck($status===200 && str_contains($body,'Consulta deshabilitada') &&
            !str_contains($body,'bk_catalog_read'),'disabled default');
    } else {
        ck($status===200 && str_contains($body,'Consultar una página autorizada'),'real admin menu and form');
        $doc=new DOMDocument();
        @$doc->loadHTML($body);
        $nonce=(new DOMXPath($doc))->query('//form[.//input[@name="bk_catalog_read"]]//input[@name="_wpnonce"]')->item(0);
        ck($nonce instanceof DOMElement,'form nonce');
        $form=['bk_catalog_read'=>'1','bk_store'=>'7','bk_page'=>'1','bk_query'=>'fixture','_wpnonce'=>'invalid'];
        if ($mode==='invalid-nonce') {
            [$code,$bad]=$request($path,$form);
            ck($code===403 && !str_contains($bad,'bk-catalog-json')
                && str_contains($bad,'Catalog authorization rejected.'),
                'bad nonce denied (HTTP '.(int)$code.')');
            unset($form['_wpnonce']);
            [$code,$missing]=$request($path,$form);
            ck($code===403 && !str_contains($missing,'bk-catalog-json')
                && str_contains($missing,'Catalog authorization rejected.'),
                'missing nonce denied (HTTP '.(int)$code.')');
            $form['_wpnonce']=['invalid'];
            [$code,$array]=$request($path,$form);
            ck($code===403 && !str_contains($array,'bk-catalog-json')
                && str_contains($array,'Catalog authorization rejected.'),
                'array nonce denied (HTTP '.(int)$code.')');
            echo "Invalid, missing and non-scalar nonces rejected before rendering.\n";
            return;
        }
        $form['_wpnonce']=$nonce->getAttribute('value');
        [$code,$good]=$request($path,$form);
        ck($code===200,'authorized POST');
        ck(!str_contains($good,'<script>unsafe</script>'),'provider title escaped');
        $doc=new DOMDocument();
        @$doc->loadHTML($good);
        $field=(new DOMXPath($doc))->query('//textarea[@id="bk-catalog-json"]')->item(0);
        ck($field instanceof DOMElement,'structured snapshot');
        $snapshot=json_decode($field->textContent,true,32,JSON_THROW_ON_ERROR);
        ck($snapshot['schema']==='bakata-dropify-bridge-v1' && $snapshot['store_id']==='7'
            && $snapshot['offset']===0 && count($snapshot['rows'])===1,'snapshot scope');
        ck($snapshot['rows'][0]['sku']==='025216' && $snapshot['rows'][0]['base_price']==='7000.25'
            && $snapshot['rows'][0]['simple_stock']===5,'snapshot commercial fields');
        [$code,$again]=$request($path,$form);
        ck($code===200 && str_contains($again,'Consulta bloqueada o fallida')
            && !str_contains($again,'id="bk-catalog-json"'),'duplicate POST blocked');
        echo json_encode($snapshot,JSON_THROW_ON_ERROR|JSON_UNESCAPED_UNICODE)."\n";
    }
    curl_close($http);
} finally { @unlink($jar); }
