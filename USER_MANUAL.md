# Autonomous AI Trading Agent — User Manual
### Explained like you’re 12 (and have never traded or coded before)

This is your complete guide. Read it in order the first time. After that, jump to whatever section you need.

---

## 1. What is this thing?

Imagine you have a **robot assistant** that:
1. Looks at the stock market every day (or every 30 minutes).
2. Reads news about big companies.
3. Decides “should I buy or sell something?” using simple rules + Grok (AI).
4. Places **fake** trades with play money so you never risk real cash.
5. After each day, looks at what worked and what didn’t, and tries to get a little smarter.

That robot is this program.  
It lives in a folder on your computer and you talk to it with **PowerShell** (the black window).

**Important words:**
- **Paper trading** = pretend money. Your real bank account is safe.
- **Alpaca** = the free website that gives the robot play money and the ability to “buy” stocks with it.
- **Agent** = the robot program itself.
- **Self-improving / self-loop** = the robot looks at its own past decisions and adjusts how much it trusts certain signals next time.

This is **not** the YouTube thumbnail “RSI agent” from the original screenshots. This is the **stock-trading** self-improving agent.

---

## 2. What you need on your computer

You already did most of this. Here’s the checklist:

| Thing | Status you should have |
|-------|------------------------|
| Windows computer | Yes |
| PowerShell | Built into Windows |
| Python | Installed (you saw a version number) |
| Git | Installed |
| Project folder | `Documents\autonomous-ai-trading-agent` |
| Virtual environment | The `(.venv)` you see in PowerShell |
| Alpaca Paper keys | In your `.env` file |
| Finnhub key | In your `.env` file |
| Grok / xAI key | In your `.env` file (optional but you have it working) |

---

## 3. How to open the robot every time (PowerShell steps)

Do these every time you want to use the agent:

1. Press the **Windows key**.
2. Type **PowerShell** and open it.
3. Copy and paste these lines one by one (press Enter after each):

```powershell
cd $HOME\Documents\autonomous-ai-trading-agent
.\.
venv\Scripts\Activate.ps1
```

You should now see `(.venv)` at the start of the line. That means the robot’s special toolbox is turned on.

---

## 4. The main commands (how to “call” the agent)

### Safe practice mode (no orders at all)
```powershell
python main.py --dry-run
```
The robot thinks and prints what it *would* do, but does not touch even the play money.

### One real paper-trading cycle
```powershell
python main.py
```
The robot researches, asks Grok, and **places paper orders** if it finds good ideas.

### Keep running every 30 minutes
```powershell
python main.py --loop --interval 30
```
It wakes up every 30 minutes and does a cycle.  
Stop it by pressing **Ctrl + C**.

### End-of-day review (learning step)
```powershell
python main.py --review
```
Forces the robot to look at today’s journal and update its internal “weights.”

### Update the code when fixes are pushed
```powershell
git pull
```

---

## 5. How the self-learning loop works

Think of the robot as a student who takes a test every day.

1. **During the day** it looks at prices, trends, volume, and news. It scores each possible trade. Grok can raise or lower that score, or throw the idea away.

2. **When it trades (paper)** it writes everything down in a notebook (`data/trade_journal.jsonl`).

3. **At the end of the day / when you run `--review`** it reads the notebook and asks which signals helped and which were noise. Then it nudges internal “weights” (trust trend more, trust momentum less, etc.).

4. **Next run** those updated weights change how it scores new ideas. Over many days the robot slowly becomes better calibrated.

This is **not** sci-fi general AI. It is a simple feedback loop: record → review → adjust → repeat.

---

## 6. How to improve the agent yourself

### Change risk and confidence
```powershell
notepad config\settings.yaml
```
- `risk_per_trade_pct: 1.0` — play-money risk per trade
- `min_confidence: 0.62` — raise to 0.70 for fewer trades
- `max_open_positions: 8`

### Change the stock list
Same file, under `universe: symbols:`.

### Turn Grok off
Clear `OPENAI_API_KEY` in `.env`.

### Read the journal
```powershell
notepad data\trade_journal.jsonl
```

### Ask Grok (me) to change the code
Just describe what you want in plain English.

---

## 7. ChatGPT-like interface

**Before:** only PowerShell.  
**Now:** a simple browser control panel (`app_ui.py`).

```powershell
pip install streamlit
streamlit run app_ui.py
```

A browser tab opens. You can click buttons for dry-run, paper cycle, or review.

---

## 8. Pairing with another agent

Yes. A companion **Briefing Agent** is included.

```powershell
python companion_briefing.py
```

It reads the journal and explains in plain English what the trading robot has been doing.

Other good teammates later: risk overlord, deep research scout, daily email summary.

---

## 9. FAQ

**Q: Can this lose real money?**  
A: No, if you only use Alpaca Paper keys.

**Q: “No high-confidence edge found” — is that bad?**  
A: No. Sitting out is often the smartest choice.

**Q: Markets are closed but I still see ideas?**  
A: It uses the last available prices. Normal after hours.

**Q: Grok discarded most ideas?**  
A: Usually a feature. It is being careful.

**Q: How do I see paper positions?**  
A: https://app.alpaca.markets (Paper account) or the agent printout.

**Q: PowerShell closed — what now?**  
A: Open it again and re-run the two activation lines.

**Q: Red error I don’t understand?**  
A: Copy the whole red text and send it to me.

**Q: Will this make me rich?**  
A: No guarantees. Treat it as a learning lab with play money.

**Q: Where are the logs?**  
A: `data\trade_journal.jsonl` and `logs\research.jsonl`.

---

## 10. Suggestions

1. Dry-run for several days before paper orders.
2. Raise min_confidence if you want fewer trades.
3. Keep risk at 1% or lower at first.
4. Run `--review` once a week.
5. Use the Streamlit UI when you want buttons instead of commands.
6. Never go live until you understand months of paper results.

---

## 11. Quick cheat-sheet

```powershell
cd $HOME\Documents\autonomous-ai-trading-agent
.\.
venv\Scripts\Activate.ps1

python main.py --dry-run
python main.py
python main.py --loop --interval 30
python main.py --review
git pull

pip install streamlit
streamlit run app_ui.py
python companion_briefing.py
```

If any section is still confusing, point to it and I will rewrite that part even more simply.
