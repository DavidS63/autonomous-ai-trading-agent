# Self-Improving Autonomous AI Trading Agent  
**Alpaca Paper Trading + Finnhub News + Optional LLM Decision Head**

A practical implementation of the optimized prompt for a continuous, self-improving autonomous trading agent that researches markets and executes simulated short-term / day trades exclusively on **Alpaca Paper Trading**.

### Core Loop
1. **Market Intelligence** – account, positions, quotes, bars, technical features, **Finnhub company news**
2. **Self-Reflection** – explicit probability-update question after every scan
3. **Decision** – rules-based scoring → optional **LLM refinement** of thesis & confidence
4. **Risk-checked Execution** – 1% equity risk per trade, max positions, heat limits
5. **Journal + Self-Improvement** – full decision log, end-of-day review, weight updates

All trading is **paper only**. Never real capital.

---

## Quick Start

### 1. Get free keys
- **Alpaca Paper**: [app.alpaca.markets](https://app.alpaca.markets) → Paper Trading → generate API Key + Secret
- **Finnhub** (recommended): [finnhub.io](https://finnhub.io) → free API key (company news, earnings, etc.)
- **LLM** (optional): OpenAI / xAI Grok / OpenRouter / any OpenAI-compatible endpoint

### 2. Setup
```bash
cd autonomous-ai-trading-agent
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your keys
```

### 3. Run
```bash
# Single cycle (research → decide → optional execute)
python main.py

# Dry-run (no orders placed)
python main.py --dry-run

# Continuous loop
python main.py --loop --interval 30

# Force end-of-day self-improvement review
python main.py --review
```

---

## Features

| Feature | Status | Notes |
|---------|--------|-------|
| Alpaca Paper Trading | ✅ | Full order placement, positions, account |
| Risk-based position sizing | ✅ | 1% equity risk, stop-based sizing |
| Technical research | ✅ | Momentum, SMA cross, volume, ATR proxy |
| Finnhub company news | ✅ | Recent headlines + summaries attached to each symbol |
| Self-reflection prompt | ✅ | Runs after every scan |
| LLM Decision Head | ✅ | Optional. Refines confidence + thesis. Works with OpenAI, Grok (xAI), OpenRouter, local servers |
| Trade journal | ✅ | JSONL log of every decision + order |
| Self-improvement | ✅ | End-of-day review + weight updates |
| Continuous mode | ✅ | `--loop` |

---

## LLM Configuration Examples

```env
# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# xAI Grok
OPENAI_API_KEY=xai-...
OPENAI_BASE_URL=https://api.x.ai/v1
LLM_MODEL=grok-4

# OpenRouter
OPENAI_API_KEY=sk-or-...
OPENAI_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=anthropic/claude-3.5-sonnet
```

---

## Risk Rules (enforced)

- Max **1%** of equity risked per trade
- Position size derived from entry → stop distance
- Max open positions & portfolio heat limits
- Minimum confidence threshold (default 0.62)
- Clear “no trade” when edge is insufficient

---

## Bundled utility: `tidy` (file organizer)

Also in this repo is a standalone CLI for cleaning up a Downloads or project
folder. It sorts files by type, date, extension or custom rules, renames them
from patterns, and removes duplicate copies. Standard library only - no external
APIs, no network access, independent of the trading agent.

```bash
python tidy.py sort ~/Downloads --by type,date          # preview
python tidy.py sort ~/Downloads --by type,date --apply  # do it

# ProjectName_2026-08-001.pdf, ProjectName_2026-08-002.pdf, ...
python tidy.py rename ./scans --pattern '{project}_{date:%Y-%m}-{n:03}' \
               --project ProjectName --apply

python tidy.py dedupe ~/Downloads --action move --keep oldest --apply
python tidy.py undo --apply      # reverse the last run
```

Every command previews by default and writes an undo journal when applied.
Full documentation: [docs/FILETIDY.md](docs/FILETIDY.md).

---

## Important Disclaimers

- Educational / research software only.
- Paper results do not guarantee live performance.
- Markets involve risk of loss. Never trade real money with untested code.
- No liability is assumed for any decisions made with this agent.

---

## License

MIT

Built to match the spirit of the original self-improving autonomous trading agent prompt.  
Happy (paper) trading.
