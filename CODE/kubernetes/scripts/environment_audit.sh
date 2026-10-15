#!/usr/bin/env bash
set -u
for command in docker kubectl kind minikube k3d helm tc ip iperf3 ping; do
  if command -v "$command" >/dev/null 2>&1; then
    printf '%-10s %s\n' "$command" "$(command -v "$command")"
  else
    printf '%-10s NOT FOUND\n' "$command"
  fi
done
printf 'kernel     %s\n' "$(uname -r)"
printf 'os         %s\n' "$(uname -srm)"
