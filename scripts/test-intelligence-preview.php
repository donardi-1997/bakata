<?php
declare(strict_types=1);

require __DIR__ . '/../wp-content/plugins/bakata-core/src/Intelligence/PreviewSnapshot.php';

use Bakata\Core\Intelligence\PreviewSnapshot;

function check(bool $condition, string $message): void {
    if (!$condition) {
        throw new RuntimeException($message);
    }
}
function rejects(array $data): void {
    try {
        PreviewSnapshot::decode(json_encode($data, JSON_THROW_ON_ERROR));
    } catch (InvalidArgumentException | JsonException $e) {
        return;
    }
    throw new RuntimeException('Invalid snapshot accepted.');
}
$json = stream_get_contents(STDIN, PreviewSnapshot::MAX_BYTES + 1);
$data = PreviewSnapshot::decode($json);
check(count($data['rows']) === 2, 'Fixture row count');
check($data['rows'][0]['score_bp'] === 7777, 'Python score parity');
check($data['rows'][1]['score_bp'] === null, 'Unknown score preserved');
check(count(PreviewSnapshot::filter($data['rows'], '', 'review-ready')) === 1, 'Status filter');
check(count(PreviewSnapshot::filter($data['rows'], 'DEMO-002', '')) === 1, 'Identity search');
check(PreviewSnapshot::filter($data['rows'], 'not-found', '') === [], 'Empty search');
check(PreviewSnapshot::filter(array_reverse($data['rows']), '', '')[0]['status'] === 'review-ready', 'Ready candidates first');
foreach (['mode','rubric'] as $key) {
    $bad = $data;
    $bad[$key] = 'live';
    rejects($bad);
}
foreach (['url'=>'https://real.example.com/product','score_bp'=>10000,'coverage_pct'=>99,'source'=>'real-source','status'=>'approved','price_minor'=>-1] as $key=>$value) {
    $bad = $data;
    $bad['rows'][0][$key] = $value;
    rejects($bad);
}
$bad = $data;
$bad['rows'][] = $bad['rows'][0];
rejects($bad);
$bad = $data;
$bad['rows'][0]['components'][0]['weight'] = 50;
rejects($bad);
$bad = $data;
$bad['rows'][1]['score_bp'] = 0;
rejects($bad);
$bad = $data;
$bad['rows'][0]['url'] .= '?secret=fixture';
rejects($bad);
echo "Intelligence snapshot contract passed.\n";
