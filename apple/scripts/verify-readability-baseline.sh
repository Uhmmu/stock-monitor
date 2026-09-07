#!/bin/sh
set -eu

repo_root=$(git rev-parse --show-toplevel)
features="$repo_root/apple/Packages/StockMonitorFeatures/Sources/StockMonitorFeatures"

count_fixed() {
    (rg -F -o "$1" "$features" -g '*.swift' || true) | wc -l | tr -d ' '
}

count_regex() {
    (rg -o "$1" "$features" -g '*.swift' || true) | wc -l | tr -d ' '
}

assert_not_increased() {
    label=$1
    actual=$2
    baseline=$3
    if [ "$actual" -gt "$baseline" ]; then
        echo "$label increased from the R1 baseline ($baseline -> $actual). Use StockMonitorDesign tokens or roles."
        exit 1
    fi
}

assert_not_increased "custom font sizes" "$(count_fixed '.font(.system(size:')" 1
assert_not_increased "numeric padding literals" "$(count_regex '\.padding\([0-9]')" 56
assert_not_increased "feature-local Color construction" "$(count_fixed 'Color(')" 2
assert_not_increased "caption2 usage" "$(count_fixed '.font(.caption2)')" 12

echo "Readability baseline guard passed. New business UI must use StockMonitorDesign roles and tokens."
