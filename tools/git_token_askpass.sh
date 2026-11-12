#!/bin/sh
# Git calls this with an origin prompt, never with the token. Do not trace it.
set +x
case "${1:-}" in
    *"'https://github.com'"*|*"'https://"*"@github.com'"*) ;;
    *) exit 1 ;;
esac
case "$1" in
    *Username*) printf '%s\n' "${MDS_GIT_AUTH_USERNAME:-x-access-token}" ;;
    *Password*)
        test -r "${MDS_GIT_AUTH_TOKEN_FILE:-}" || exit 1
        tr -d '\r\n' < "$MDS_GIT_AUTH_TOKEN_FILE"
        ;;
    *) exit 1 ;;
esac
