#!/bin/sh
set -eu

repo_root=$(git rev-parse --show-toplevel)
features="$repo_root/apple/Packages/StockMonitorFeatures/Sources/StockMonitorFeatures"

count_fixed() {
    (rg -F -o "$1" "$features" -g '*.swift' || true) | wc -l | tr -d ' '
}

# R2.0：raw JSON 退出主路径
json_evidence_calls=$(count_fixed 'JSONEvidenceView(value:')
if [ "$json_evidence_calls" -ne 0 ]; then
    echo "R2.1 violation: JSONEvidenceView still used in main path ($json_evidence_calls call sites). Use SemanticEvidenceView."
    exit 1
fi

json_document_refs=$(count_fixed 'JSONDocumentView')
if [ "$json_document_refs" -ne 0 ]; then
    echo "R2.0 violation: JSONDocumentView was reintroduced. Raw JSON rendering is RawJSONDiagnosticsView (diagnostics only)."
    exit 1
fi

phase_leaks=$(count_fixed 'Phase \(descriptor.phase')
if [ "$phase_leaks" -ne 0 ]; then
    echo "R2.2 violation: workspace chrome still shows internal phase labels."
    exit 1
fi

raw_diag_refs=$(count_fixed 'RawJSONDiagnosticsView(')
# 允许的三处：组件自身递归 2 处 + 工作台"诊断 · 原始响应"折叠区 1 处。
if [ "$raw_diag_refs" -gt 3 ]; then
    echo "R2.0 warning-level check failed: RawJSONDiagnosticsView should only appear inside diagnostics rendering ($raw_diag_refs refs)."
    exit 1
fi

semantic_keys=$(count_fixed 'semantic: "')
if [ "$semantic_keys" -lt 80 ]; then
    echo "R2.0 violation: GoalM5 endpoints lost semantic presentation keys (found $semantic_keys, need >= 80)."
    exit 1
fi

# R1 基线 guard 仍然有效
"$repo_root/apple/scripts/verify-readability-baseline.sh"

echo "Readability R2 gate passed. Main paths are semantic; raw JSON stays inside diagnostics."
