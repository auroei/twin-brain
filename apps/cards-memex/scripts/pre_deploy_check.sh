#!/bin/bash
# Pre-Deploy Safety Checks
# Run this before EVERY deployment to production
#
# Usage:
#   chmod +x scripts/pre_deploy_check.sh
#   ./scripts/pre_deploy_check.sh

set -e  # Exit on first failure

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"

cd "$APP_DIR"

echo ""
echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║                     PRE-DEPLOY SAFETY CHECKS                         ║"
echo "╠══════════════════════════════════════════════════════════════════════╣"
echo "║  If ANY check fails, fix it before deploying.                        ║"
echo "║  These checks prevent user-visible bugs from reaching production.    ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

FAILED=0

# ============================================================================
# CHECK 1: Contract Tests (interface safety)
# ============================================================================
echo "┌────────────────────────────────────────────────────────────────────────┐"
echo "│ [1/4] CONTRACT TESTS                                                   │"
echo "│       Validates module interfaces haven't broken                       │"
echo "└────────────────────────────────────────────────────────────────────────┘"
echo ""

if python scripts/test_contracts.py; then
    echo ""
    echo "✅ Contract tests passed"
else
    echo ""
    echo "❌ Contract tests FAILED"
    FAILED=$((FAILED + 1))
fi

echo ""

# ============================================================================
# CHECK 2: Critical Flow Tests (behavior safety)
# ============================================================================
echo "┌────────────────────────────────────────────────────────────────────────┐"
echo "│ [2/4] CRITICAL FLOW TESTS                                              │"
echo "│       Validates most important user-facing behaviors                   │"
echo "└────────────────────────────────────────────────────────────────────────┘"
echo ""

if python scripts/test_critical_flows.py; then
    echo ""
    echo "✅ Critical flow tests passed"
else
    echo ""
    echo "❌ Critical flow tests FAILED"
    FAILED=$((FAILED + 1))
fi

echo ""

# ============================================================================
# CHECK 3: Integration Tests (end-to-end safety)
# ============================================================================
echo "┌────────────────────────────────────────────────────────────────────────┐"
echo "│ [3/4] INTEGRATION TESTS                                                │"
echo "│       Validates end-to-end behavior                                    │"
echo "└────────────────────────────────────────────────────────────────────────┘"
echo ""

if python scripts/test_integration.py; then
    echo ""
    echo "✅ Integration tests passed"
else
    echo ""
    echo "❌ Integration tests FAILED"
    FAILED=$((FAILED + 1))
fi

echo ""

# ============================================================================
# CHECK 4: Config Syntax (YAML validity)
# ============================================================================
echo "┌────────────────────────────────────────────────────────────────────────┐"
echo "│ [4/4] CONFIG SYNTAX CHECK                                              │"
echo "│       Validates YAML files are parseable                               │"
echo "└────────────────────────────────────────────────────────────────────────┘"
echo ""

CONFIG_ERROR=0
for config_file in config/*.yaml; do
    if python -c "import yaml; yaml.safe_load(open('$config_file'))" 2>/dev/null; then
        echo "  ✓ $config_file"
    else
        echo "  ✗ $config_file - INVALID YAML"
        CONFIG_ERROR=1
    fi
done

if [ $CONFIG_ERROR -eq 0 ]; then
    echo ""
    echo "✅ All config files valid"
else
    echo ""
    echo "❌ Config file errors detected"
    FAILED=$((FAILED + 1))
fi

echo ""

# ============================================================================
# SUMMARY
# ============================================================================
echo "╔══════════════════════════════════════════════════════════════════════╗"
if [ $FAILED -eq 0 ]; then
    echo "║  ✅ ALL CHECKS PASSED - Safe to deploy                               ║"
    echo "╚══════════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Next steps:"
    echo "  1. Commit your changes"
    echo "  2. Run: ./run.sh"
    echo ""
    exit 0
else
    echo "║  ❌ $FAILED CHECK(S) FAILED - DO NOT DEPLOY                           ║"
    echo "╚══════════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Fix the failures above before deploying."
    echo "Each failure represents potential user-visible bugs."
    echo ""
    exit 1
fi

