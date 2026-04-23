#!/usr/bin/env bash
# Convenience wrapper: načte ADI creds z 1P Connect, spustí test_docint.py.
#
# Usage:
#   bash scripts/dev/run_docint_test.sh <test-dir>
#
# Vyžaduje:
#   - op CLI (ověř: bash scripts/dev/check_op_cli.sh)
#   - python3 + azure-ai-documentintelligence (pip install -r scripts/dev/requirements.txt)

set -eu

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <test-dir>"
    echo "       $0 test_data/"
    exit 1
fi

TEST_DIR="$1"

if [[ ! -d "$TEST_DIR" ]]; then
    echo "ERROR: not a directory: $TEST_DIR"
    exit 2
fi

if ! command -v op &>/dev/null; then
    echo "ERROR: op CLI nenalezen. Nejdřív: bash scripts/dev/check_op_cli.sh"
    exit 3
fi

# Multi-account: pokud má user víc 1P accountů, musí být explicitně zvolen.
# Preferuj OP_ACCOUNT z env; fallback na yeast account user ID; jinak fail.
if [[ -z "${OP_ACCOUNT:-}" ]]; then
    echo "WARN: OP_ACCOUNT není nastaven. Použij:"
    echo "    export OP_ACCOUNT=FZJUM5YY4ZFKHCGSQSZRDANCNM   # yeast-group.cz"
    echo "  nebo persistent v ~/.zshrc."
    exit 4
fi

echo "→ Používám 1P account: $OP_ACCOUNT"
echo "→ Načítám ADI creds z 1P (vault cortex-prod-core, item azure-docint-prod)..."

# op read zapíše hodnotu na stdout, errory na stderr.
# Pokud jeden z fieldů chybí, exit non-zero a celý run zhavaruje dřív než creds leakne.
AZURE_DOCINT_ENDPOINT=$(op read --account "$OP_ACCOUNT" "op://cortex-prod-core/azure-docint-prod/endpoint")
AZURE_DOCINT_KEY=$(op read --account "$OP_ACCOUNT" "op://cortex-prod-core/azure-docint-prod/key_primary")

# Export jen pro child proces. Shell si je ponechá, ale `unset` po runu by bylo opatrné
# kdybys chtěl paranoid level (viz konec scriptu).
export AZURE_DOCINT_ENDPOINT
export AZURE_DOCINT_KEY

echo "→ Endpoint: ${AZURE_DOCINT_ENDPOINT}"
echo "→ Spouštím test na: ${TEST_DIR}"
echo ""

python3 "$(dirname "$0")/test_docint.py" "$TEST_DIR"
RC=$?

# Clean up — necháme endpoint (ten není sensitive), wipe key
unset AZURE_DOCINT_KEY

exit $RC
