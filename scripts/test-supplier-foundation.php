<?php
declare(strict_types=1);

use Bakata\Core\Suppliers\CatalogAdapter;
use Bakata\Core\Suppliers\CatalogPage;
use Bakata\Core\Suppliers\CatalogPreview;
use Bakata\Core\Suppliers\SupplierProduct;

require_once __DIR__ . '/../wp-content/plugins/bakata-core/src/Suppliers/Contracts.php';
require_once __DIR__ . '/../wp-content/plugins/bakata-core/src/Suppliers/CatalogPreview.php';

/** Fake adapter exists only in this standalone test. No WP or network. */
final class TestAdapter implements CatalogAdapter
{
    public int $calls = 0;
    public function __construct(private array $pages) {}
    public function supplierId(): string { return 'ci-supplier'; }
    public function fetchPage(?string $cursor, int $limit): CatalogPage
    {
        $this->calls++;
        $key = $cursor ?? 'first';
        if (!isset($this->pages[$key])) {
            throw new RuntimeException('Unexpected fake cursor.');
        }
        return $this->pages[$key];
    }
}

$checks = 0;
function check(bool $condition, string $label): void {
    global $checks;
    if (!$condition) { throw new RuntimeException('Failed: ' . $label); }
    $checks++;
}
function rejects(callable $fn, string $class, string $message): void {
    try { $fn(); } catch (Throwable $error) {
        check($error instanceof $class && str_contains($error->getMessage(), $message), $message);
        return;
    }
    throw new RuntimeException('Expected rejection: ' . $message);
}
$now = new DateTimeImmutable('2026-01-01T00:00:00Z');
$product = static fn(string $id='SKU-A', int $cost=2500000, int $stock=5, string $currency='COP',
    int $minor=2, string $supplier='ci-supplier', ?DateTimeImmutable $at=null, string $title='Synthetic product')
    => new SupplierProduct($supplier,$id,$title,$cost,$currency,$minor,$stock,$at ?? $now);
$preview = new CatalogPreview();
$collect = static fn(array $pages, int $size=2, int $max=3) => $preview->collect(
    new TestAdapter($pages),$now,'COP',2,3600,$size,$max
);
$first=$product();
$second=$product(id:'SKU-B',stock:0);
$rows=$collect(['first'=>new CatalogPage([$first],'next'),'next'=>new CatalogPage([$second],null)]);
check(count($rows)===2,'all pages');
check($rows[0]['unitCostMinor']===2500000 && $rows[0]['currency']==='COP' && $rows[0]['currencyMinorUnit']===2,'integer cost and currency');
check($rows[1]['availableQuantity']===0,'zero stock remains zero');
check(!array_key_exists('salePrice',$rows[0]) && !array_key_exists('publish',$rows[0]),'no sale price or publish decision');
check($first->identity()===$product(cost:3000000,stock:1,title:'Changed')->identity(),'stable identity');
check($first->proposedSku()===$product(stock:0)->proposedSku(),'stable SKU');
check($first->identity()!==$product(supplier:'other-supplier')->identity(),'supplier isolation');
check($first->identity()!==$second->identity(),'SKU isolation');
check($first->fingerprint()!==$product(cost:3000000)->fingerprint(),'cost changes fingerprint');
check($first->fingerprint()!==$product(stock:0)->fingerprint(),'stock changes fingerprint');
check($first->fingerprint()===$product(at:$now->modify('-1 minute'))->fingerprint(),'time excluded from fingerprint');
check($collect(['first'=>new CatalogPage([],null)])===[],'empty catalog');
check($rows===$collect(['first'=>new CatalogPage([$first],'next'),'next'=>new CatalogPage([$second],null)]),'deterministic preview');
rejects(fn()=>$product(cost:-1),InvalidArgumentException::class,'Invalid product cost');
rejects(fn()=>$product(stock:-1),InvalidArgumentException::class,'Invalid product cost');
rejects(fn()=>$product(id:''),InvalidArgumentException::class,'Invalid external product');
rejects(fn()=>$product(title:' '),InvalidArgumentException::class,'Invalid product title');
rejects(fn()=>$collect(['first'=>new CatalogPage([$product(currency:'USD')],null)]),RuntimeException::class,'Currency mismatch');
rejects(fn()=>$collect(['first'=>new CatalogPage([$product(minor:0)],null)]),RuntimeException::class,'Currency mismatch');
rejects(fn()=>$collect(['first'=>new CatalogPage([$product(supplier:'other-supplier')],null)]),RuntimeException::class,'another supplier');
rejects(fn()=>$collect(['first'=>new CatalogPage([$product(at:$now->modify('-3601 seconds'))],null)]),RuntimeException::class,'stale or from the future');
rejects(fn()=>$collect(['first'=>new CatalogPage([$product(at:$now->modify('+1 second'))],null)]),RuntimeException::class,'stale or from the future');
rejects(fn()=>$collect(['first'=>new CatalogPage([$first],'next'),'next'=>new CatalogPage([$first],null)]),RuntimeException::class,'Duplicate external product');
rejects(fn()=>$collect(['first'=>new CatalogPage([],'next'),'next'=>new CatalogPage([],'next')]),RuntimeException::class,'Repeated pagination cursor');
rejects(fn()=>$collect(['first'=>new CatalogPage([],'next')],2,1),RuntimeException::class,'page limit reached');
rejects(fn()=>$collect(['first'=>new CatalogPage([$first,$second],null)],1),RuntimeException::class,'exceeded requested page size');
rejects(fn()=>new CatalogPage(['not a product'],null),InvalidArgumentException::class,'Invalid catalog product');
rejects(fn()=>new CatalogPage([],''),InvalidArgumentException::class,'Invalid pagination cursor');
rejects(fn()=>$collect([],0),InvalidArgumentException::class,'Invalid preview limits');
echo "Supplier foundation: {$checks} checks passed.\n";
