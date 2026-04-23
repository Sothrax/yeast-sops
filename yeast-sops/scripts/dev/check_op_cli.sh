#!/usr/bin/env bash
# Ověřuje že 1Password CLI je nainstalován a dostupný pro secret fetch.
# Usage: bash scripts/dev/check_op_cli.sh

set -u

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}✓${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; }
warn() { echo -e "${YELLOW}!${NC} $1"; }

echo "=== 1Password CLI check ==="

# 1) Binary existuje?
if ! command -v op &>/dev/null; then
    fail "op CLI nenalezen v PATH"
    echo ""
    echo "  Instalace na macOS:"
    echo "    brew install --cask 1password-cli"
    echo ""
    echo "  Po instalaci: op signin"
    exit 1
fi
pass "op CLI nalezen: $(command -v op)"

# 2) Version
OP_VERSION=$(op --version 2>/dev/null || echo "unknown")
pass "op verze: $OP_VERSION"

# 3) Přihlášen?
# op s Desktop app → op account list
# op s Connect → OP_CONNECT_HOST + OP_CONNECT_TOKEN env vars
if [[ -n "${OP_CONNECT_HOST:-}" && -n "${OP_CONNECT_TOKEN:-}" ]]; then
    pass "1P Connect detekován (OP_CONNECT_HOST + OP_CONNECT_TOKEN v env)"
    echo "    Host: $OP_CONNECT_HOST"

    # Test read — volnější, nevadí pokud item neexistuje, jen že API odpovídá
    if op vault list &>/dev/null; then
        pass "Connect API responds, vaulty přístupné"
    else
        fail "Connect API nedostupné (token expired? network? wrong host?)"
        exit 2
    fi
else
    # Desktop app / CLI-only mode
    if op account list 2>/dev/null | grep -qE 'my\.1password\.com|\.ent\.1password'; then
        pass "Desktop app signin aktivní"
        op account list | sed 's/^/    /'
    else
        warn "Žádná aktivní session (desktop app) ani Connect creds v env"
        echo ""
        echo "  Dvě možnosti:"
        echo "  (A) Desktop app:"
        echo "      op signin"
        echo "  (B) 1P Connect:"
        echo "      export OP_CONNECT_HOST=\"https://op-connect.yeast.internal\""
        echo "      export OP_CONNECT_TOKEN=\"<read-only-token>\""
        exit 3
    fi
fi

# 4) Test read na konkrétní item z naší konvence
echo ""
echo "=== Test read: op://cortex-prod-core/azure-docint-prod/endpoint ==="
if ENDPOINT=$(op read "op://cortex-prod-core/azure-docint-prod/endpoint" 2>/dev/null); then
    pass "Endpoint načten: ${ENDPOINT:0:40}..."
else
    fail "Nelze přečíst. Zkontroluj:"
    echo "    - vault 'cortex-prod-core' existuje"
    echo "    - item 'azure-docint-prod' existuje v tom vaultu"
    echo "    - field 'endpoint' je v itemu"
    echo "    - token / session má read scope na tento vault"
    exit 4
fi

echo ""
pass "Vše OK. Můžeš spustit: bash scripts/dev/run_docint_test.sh test_data/"
