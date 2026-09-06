#!/bin/sh
set -eu

developer_id_status=missing
notary_profile_status=missing

if security find-certificate -a -c 'Developer ID Application' >/dev/null 2>&1; then
    developer_id_status=available
fi
if [ -n "${STOCK_MONITOR_NOTARY_PROFILE:-}" ]; then
    notary_profile_status=configured
fi

printf 'architecture=arm64\n'
printf 'developer_id=%s\n' "$developer_id_status"
printf 'notary_profile=%s\n' "$notary_profile_status"
if [ "$developer_id_status" = available ] && [ "$notary_profile_status" = configured ]; then
    printf 'distribution_gate=ready_for_notarization_attempt\n'
else
    printf 'distribution_gate=blocked_by_apple_developer_membership\n'
fi
