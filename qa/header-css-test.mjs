import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const css = await readFile(new URL('../wp-content/themes/bakata/assets/css/header.css', import.meta.url), 'utf8');

function check(cssText) {
  assert.match(cssText, /\.bk-header-menu\s*>\s*summary\s*\{\s*list-style:\s*none\s*;/);
  assert.match(cssText, /\.bk-header-menu\s*>\s*summary::-webkit-details-marker\s*\{\s*display:\s*none\s*;/);
  assert.doesNotMatch(cssText, /\.bk-header-menu\s+summary(?:\s*\{|::-webkit-details-marker)/);
}

check(css);
// Prove each original descendant selector is rejected independently.
assert.throws(() => check(css.replace('.bk-header-menu > summary {', '.bk-header-menu summary {')));
assert.throws(() => check(css.replace('.bk-header-menu > summary::-webkit-details-marker', '.bk-header-menu summary::-webkit-details-marker')));
console.log('Header disclosure selector regression checks passed.');
