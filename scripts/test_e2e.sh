#!/usr/bin/env bash
# End-to-end test for Alexandria.
# Run from a regular terminal (NOT inside a Claude Code session).
# This tests the full pipeline including LLM-powered features.
#
# Usage:
#   cd /path/to/llmwiki
#   bash scripts/test_e2e.sh

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}PASS${NC} $1"; }
fail() { echo -e "${RED}FAIL${NC} $1"; exit 1; }
info() { echo -e "${YELLOW}....${NC} $1"; }

# Create a fresh test workspace
info "Creating test workspace..."
uv run alxia workspace create e2e-test --name "E2E Test" 2>/dev/null || true

# 1. Ingest a local markdown file
info "Ingesting local markdown file..."
cat > /tmp/alexandria-e2e-test.md << 'TESTDOC'
# Transformer Architecture Overview

The Transformer architecture was introduced by Vaswani et al. in the 2017 paper
"Attention Is All You Need". It replaced recurrent neural networks with a
self-attention mechanism that processes all positions in a sequence simultaneously.

## Key Components

The Transformer consists of an encoder and decoder, each with stacked layers of:
- Multi-head self-attention
- Position-wise feed-forward networks
- Layer normalization and residual connections

## Impact

Transformers enabled models like BERT, GPT, and T5 that achieved state-of-the-art
results across NLP tasks. The architecture scales efficiently with data and compute,
leading to the emergence of large language models (LLMs).

BERT uses only the encoder stack for bidirectional language understanding.
GPT uses only the decoder stack for autoregressive text generation.
T5 uses the full encoder-decoder architecture and treats every task as text-to-text.
TESTDOC

output=$(uv run alxia ingest /tmp/alexandria-e2e-test.md -w e2e-test 2>&1)
echo "$output"
echo "$output" | grep -q "committed" && pass "Local file ingest" || fail "Local file ingest"

# 2. Check database indexing (FTS)
info "Verifying FTS index..."
output=$(uv run python -c "
from alexandria.db.connection import connect, db_path
from alexandria.config import resolve_home
with connect(db_path(resolve_home())) as conn:
    rows = conn.execute('''SELECT documents.title, documents.path FROM documents_fts
        JOIN documents ON documents.rowid = documents_fts.rowid
        WHERE documents_fts MATCH ? AND documents.workspace = ?''',
        ('transformer', 'e2e-test')).fetchall()
    for r in rows:
        print(f'{r[\"title\"]} — {r[\"path\"]}')
    if not rows:
        print('NO_RESULTS')
" 2>&1)
echo "$output"
echo "$output" | grep -qi "transformer" && pass "FTS index" || fail "FTS index"

# 3. Test query (requires LLM)
info "Testing query (requires LLM)..."
output=$(uv run alxia query "What is the Transformer architecture?" -w e2e-test 2>&1)
echo "$output"
if echo "$output" | grep -qi "no llm"; then
    echo -e "${YELLOW}SKIP${NC} Query — no LLM provider configured"
    echo "Configure one of: ANTHROPIC_API_KEY, OPENAI_API_KEY, or install claude-code-sdk"
else
    echo "$output" | grep -qi "attention\|transformer\|vaswani" && pass "Query" || fail "Query"
fi

# 4. Test MCP tools via claude -p (if claude is available)
if command -v claude &>/dev/null; then
    info "Testing MCP tools..."

    cat > /tmp/e2e-mcp.json << MCPEOF
{
  "mcpServers": {
    "alexandria": {
      "command": "$(which alexandria || echo uv run alxia)",
      "args": ["mcp", "serve", "--workspace", "e2e-test"]
    }
  }
}
MCPEOF

    output=$(claude -p 'Call mcp__alexandria__search with query "transformer" and return the output.' \
        --mcp-config /tmp/e2e-mcp.json \
        --permission-mode bypassPermissions \
        --allowedTools "mcp__alexandria__search" 2>&1)
    echo "$output"
    echo "$output" | grep -qi "transformer" && pass "MCP search" || fail "MCP search"

    output=$(claude -p 'Call mcp__alexandria__belief_add with statement="Transformers use self-attention", topic="architectures", subject="Transformers", predicate="use", object="self-attention". Return the output.' \
        --mcp-config /tmp/e2e-mcp.json \
        --permission-mode bypassPermissions \
        --allowedTools "mcp__alexandria__belief_add" 2>&1)
    echo "$output"
    echo "$output" | grep -qi "belief added" && pass "MCP belief_add" || fail "MCP belief_add"
else
    echo -e "${YELLOW}SKIP${NC} MCP tools — claude CLI not found"
fi

# 5. Clean up
info "Cleaning up..."
rm -f /tmp/alexandria-e2e-test.md /tmp/e2e-mcp.json

echo ""
echo "========================================="
echo "E2E test complete."
echo "========================================="
