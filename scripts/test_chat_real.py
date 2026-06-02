"""
Diagnostic script — tests the real chat flow end-to-end with full load_context().

Run locally with venv active:
  python scripts/test_chat_real.py

Mirrors exactly what POST /api/ai/chat does in Lambda.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

def section(title):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print('─' * 60)


MESSAGE = "Any insights for today?"

section(f"Chat: '{MESSAGE}'")

from services.context_loader import load_context
from services.claude_service import _get_client, _CHAT_SYSTEM, _MODEL

# Step 1 — load_context
print("  [1] load_context()…")
t0 = time.time()
ctx = load_context()
t_ctx = time.time() - t0
print(f"      done in {t_ctx:.2f}s")
print(f"      scanner={len(ctx.scanner_results)}  movers={len(ctx.top_movers)}  "
      f"sentiment={len(ctx.sentiment)}  technicals={len(ctx.technical_indicators)}  "
      f"positions={len(ctx.portfolio.get('positions',[]))}  trades={len(ctx.trades_today)}")

# Step 2 — serialize context and measure its size
ctx_json = json.dumps(ctx.to_dict(), default=str)
print(f"      context JSON size: {len(ctx_json):,} chars")

# Step 3 — Claude chat call
system = _CHAT_SYSTEM.format(
    profit_mode=ctx.profit_mode,
    trade_scope=ctx.trade_scope,
    goal_dollars=int(ctx.daily_goal),
)

print(f"\n  [2] Claude chat('{MESSAGE}')…")
t1 = time.time()
response = _get_client().messages.create(
    model=_MODEL,
    max_tokens=1024,
    system=system,
    messages=[
        {"role": "user", "content": ctx_json},
        {"role": "assistant", "content": "I have reviewed today's market data and your portfolio. What would you like to know?"},
        {"role": "user", "content": MESSAGE},
    ],
)
t_claude = time.time() - t1
t_total = time.time() - t0

tokens_in  = response.usage.input_tokens
tokens_out = response.usage.output_tokens

print(f"      done in {t_claude:.2f}s")
print(f"      tokens in/out: {tokens_in} / {tokens_out}")
print(f"      stop reason: {response.stop_reason}")

section("Result")
print(response.content[0].text)

section("Timing summary")
print(f"  load_context():  {t_ctx:.2f}s  (locally; ~1s in Lambda with DDB cache)")
print(f"  Claude chat:     {t_claude:.2f}s")
print(f"  Total local:     {t_total:.2f}s")
print()
est_lambda = 1.0 + t_claude
print(f"  Estimated Lambda (warm, cached): ~{est_lambda:.1f}s")
print(f"  Estimated Lambda (cold, cached): ~{est_lambda + 2:.1f}s  (add ~2s cold start at 1536MB)")
if est_lambda + 2 < 27:
    print("  ✓ Should fit under the 29s API Gateway ceiling.")
else:
    print("  ✗ Still at risk of hitting the 29s API Gateway ceiling.")
