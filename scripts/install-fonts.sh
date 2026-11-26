#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
dir=wp-content/themes/bakata/assets/fonts
mkdir -p "$dir"
tmp=$(mktemp -d "$dir/.download.XXXXXXXX")
trap 'rm -rf -- "$tmp"' EXIT
install_font() {
    local name=$1 url=$2 expected=$3
    if [[ -f "$dir/$name" ]] && [[ $(git hash-object "$dir/$name") == "$expected" ]]; then
        printf 'Font verified: %s\n' "$name"
        return
    fi
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
        --retry 3 --max-time 90 "$url" -o "$tmp/$name"
    [[ $(git hash-object "$tmp/$name") == "$expected" ]] || { echo "Font integrity failure: $name" >&2; exit 1; }
    chmod 644 "$tmp/$name"
    mv -f -- "$tmp/$name" "$dir/$name"
    printf 'Font installed: %s\n' "$name"
}
install_font 'plus-jakarta-sans.woff2' 'https://raw.githubusercontent.com/tokotype/PlusJakartaSans/18d1cd2f7ea10481919d2f05c1f7064b7307fc26/fonts/webfonts/PlusJakartaSans%5Bwght%5D.woff2' 'eebac44580986b89ed54b1dfc23209ce82ebc073'
install_font 'inter.woff2' 'https://raw.githubusercontent.com/rsms/inter/v4.1/docs/font-files/InterVariable.woff2' '5a8d3e72ad7ffb62af3b146e1b1f54ab5813a212'
install_font 'inter-italic.woff2' 'https://raw.githubusercontent.com/rsms/inter/v4.1/docs/font-files/InterVariable-Italic.woff2' 'b3530f3f5269165314114a9e1c2f129e20fddcbd'
