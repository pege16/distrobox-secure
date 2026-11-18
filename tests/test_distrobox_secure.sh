#!/bin/bash

# Test suite for Distrobox Secure
# Run with: bash tests/test_distrobox_secure.sh

set +H
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DISTROBOX_SECURE_TEST=1
export DISTROBOX_SECURE_UPDATER_TEST=1
COMPLETION_SCRIPT="$SCRIPT_DIR/completions/distrobox-secure.bash"
UPDATER_SCRIPT="$SCRIPT_DIR/distrobox-secure-updater"

# Source the main script
source "$SCRIPT_DIR/distrobox-secure" >/dev/null 2>&1
source "$UPDATER_SCRIPT" >/dev/null 2>&1

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

test_start() {
    printf "%b[TEST]%b %s\n" "$BLUE" "$NC" "$1"
    TESTS_RUN=$((TESTS_RUN + 1))
}

test_pass() {
    printf "  %b✓ PASS%b\n" "$GREEN" "$NC"
    TESTS_PASSED=$((TESTS_PASSED + 1))
}

test_fail() {
    printf "  %b✗ FAIL%b\n" "$RED" "$NC"
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

# Mock distrobox
distrobox() {
    if [[ "${1:-}" == "list" ]]; then
        printf "NAME IMAGE STATUS\n"
        printf "alpha docker.io/library/ubuntu:22.04 Running\n"
        printf "beta docker.io/library/fedora:39 Exited\n"
    fi
    return 0
}

# ==============================================================================
# Test 1
# ==============================================================================
test_start "Container name validation (valid)"
result=$(validate_container_name "mycontainer" >/dev/null 2>&1; echo $?)
if [[ "$result" == "0" ]]; then
    test_pass
else
    test_fail
fi

# ==============================================================================
# Test 2
# ==============================================================================
test_start "Container name validation (invalid)"
result=$(validate_container_name "my container" >/dev/null 2>&1; echo $?)
if [[ "$result" != "0" ]]; then
    test_pass
else
    test_fail
fi

# ==============================================================================
# Test 3
# ==============================================================================
test_start "Path validation"
test_file=$(mktemp)
result=$(validate_path "$test_file" >/dev/null 2>&1; echo $?)
rm "$test_file"
if [[ "$result" == "0" ]]; then
    test_pass
else
    test_fail
fi

# ==============================================================================
# Test 4
# ==============================================================================
test_start "Mount path parsing"
test_perm_value="/src/path:with:colons:/dst/path"
readarray -t mount_parts < <(parse_mount_permission "$test_perm_value")
src_path="${mount_parts[0]}"
dst_path="${mount_parts[1]}"
if [[ "$src_path" == "/src/path:with:colons" ]] && [[ "$dst_path" == "/dst/path" ]]; then
    test_pass
else
    test_fail
fi

# ==============================================================================
# Test 5
# ==============================================================================
test_start "Bash syntax"
result=$(bash -n "$SCRIPT_DIR/distrobox-secure" >/dev/null 2>&1; echo $?)
if [[ "$result" == "0" ]]; then
    test_pass
else
    test_fail
fi

# ==============================================================================
# Test 6
# ==============================================================================
test_start "Invalid mount path parsing"
result=$(parse_mount_permission "/src-only" >/dev/null 2>&1; echo $?)
if [[ "$result" != "0" ]]; then
    test_pass
else
    test_fail
fi

# ==============================================================================
# Test 7
# ==============================================================================
test_start "Pinned container matching is exact"
test_home=$(mktemp -d)
mkdir -p "$test_home/.config/distrobox-secure"
PINNED="$test_home/.config/distrobox-secure/pinned-containers"
printf 'foo.bar\n' > "$PINNED"
if is_pinned "foo.bar" && ! is_pinned "fooXbar"; then
    test_pass
else
    test_fail
fi
rm -rf "$test_home"

# ==============================================================================
# Test 8
# ==============================================================================
test_start "Bash completion suggests commands"
source "$COMPLETION_SCRIPT"
COMP_WORDS=(distrobox-secure gr)
COMP_CWORD=1
_distrobox_secure_completions
if [[ " ${COMPREPLY[*]} " == *" grant "* ]]; then
    test_pass
else
    test_fail
fi

# ==============================================================================
# Test 9
# ==============================================================================
test_start "Bash completion suggests containers for grant"
COMP_WORDS=(distrobox-secure grant a)
COMP_CWORD=2
_distrobox_secure_completions
if [[ " ${COMPREPLY[*]} " == *" alpha "* ]]; then
    test_pass
else
    test_fail
fi

# ==============================================================================
# Test 10
# ==============================================================================
test_start "Bash completion suggests permission types"
COMP_WORDS=(distrobox-secure grant alpha ne)
COMP_CWORD=3
_distrobox_secure_completions
if [[ " ${COMPREPLY[*]} " == *" network "* ]]; then
    test_pass
else
    test_fail
fi

# ==============================================================================
# Test 11
# ==============================================================================
test_start "Updater script syntax"
result=$(bash -n "$UPDATER_SCRIPT" >/dev/null 2>&1; echo $?)
if [[ "$result" == "0" ]]; then
    test_pass
else
    test_fail
fi

# ==============================================================================
# Summary
# ==============================================================================
printf "\n%b=== Test Results ===%b\n" "$YELLOW" "$NC"
printf "Total:  %d\n" "$TESTS_RUN"
printf "Passed: %b%d%b\n" "$GREEN" "$TESTS_PASSED" "$NC"
printf "Failed: %b%d%b\n" "$RED" "$TESTS_FAILED" "$NC"
printf "\n"

if [[ $TESTS_FAILED -eq 0 ]]; then
    printf "%bAll tests passed!%b\n" "$GREEN" "$NC"
    exit 0
else
    printf "%bSome tests failed.%b\n" "$RED" "$NC"
    exit 1
fi
