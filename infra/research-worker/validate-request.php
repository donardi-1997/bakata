<?php
// Private IPC guard. Only synthetic scope; never accepts a URL, token or command.
if (PHP_SAPI !== 'cli' || count($argv)!==2 || getenv('BAKATA_RESEARCH_FIXTURE')!=='1'
    || getenv('BAKATA_RESEARCH_PERSIST')!=='1') { exit(1); }
try {
    $page=(int)$argv[1];
    $run=getenv('BAKATA_RESEARCH_RUN');
    $until=getenv('BAKATA_RESEARCH_UNTIL');
    if (!preg_match('/\Afixture-[A-Za-z0-9_-]{1,56}\z/D',$run?:'')
        || !preg_match('/\A[0-9]{10}\z/D',$until?:'') || $page<1 || $page>3) { exit(1); }
    $path=sprintf('/exchange/request-%04d.json',$page);
    if (is_link($path) || !is_file($path) || filesize($path)>4096) { exit(1); }
    $data=json_decode(file_get_contents($path),true,16,JSON_THROW_ON_ERROR);
    if (!is_array($data) || count($data)!==6 || ($data['run']??null)!==$run
        || ($data['store']??null)!=='7' || ($data['page']??null)!==$page
        || !is_string($data['attempt']??null) || !preg_match('/\A[0-9a-f]{32}\z/D',$data['attempt'])
        || !is_int($data['reserved_at']??null) || $data['reserved_at']>time()
        || time()-$data['reserved_at']>45 || ($data['until']??null)!==(int)$until
        || (int)$until<=time() || (int)$until>time()+1800) { exit(1); }
} catch (Throwable $e) { exit(1); }
