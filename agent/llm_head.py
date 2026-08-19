"""Optional LLM decision head - refines theses, confidence, and filters using any OpenAI-compatible API."""

from __future__ import annotations

import json
import os
from typing import List, Dict, Any, Optional

from rich.console import Console

console = Console(force_terminal=False, emoji=False, legacy_windows=True)

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore


class LLMDecisionHead:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.enabled = bool(self.api_key and OpenAI is not None)

        if self.enabled:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            console.print(f"[green]OK LLM Decision Head enabled[/] - model={self.model}")
        else:
            self.client = None
            console.print("[dim]LLM Decision Head disabled (set OPENAI_API_KEY to enable)[/]")

    def refine_ideas(
        self,
        ideas: List[Any],
        research: Dict[str, Any],
    ) -> List[Any]:
        if not self.enabled or not ideas:
            return ideas

        console.print("[cyan]> LLM refining trade ideas...[/]")

        context_parts = []
        for idea in ideas[:6]:
            news = []
            for r in research.get("symbol_reports", []):
                if r.get("symbol") == idea.symbol:
                    news = [n.get("headline") for n in (r.get("news") or [])[:3]]
                    break
            context_parts.append(
                {
                    "symbol": idea.symbol,
                    "side": idea.side,
                    "entry": idea.entry,
                    "stop": idea.stop,
                    "target": idea.target,
                    "rules_confidence": idea.confidence,
                    "thesis": idea.thesis,
                    "recent_headlines": news,
                }
            )

        system = (
            "You are a rigorous short-term trading analyst working with a paper-trading agent. "
            "Your job is to critique each candidate trade idea and return an improved confidence "
            "score (0.0-1.0) and a clearer, more specific thesis. "
            "Be conservative: only raise confidence when news + technicals strongly align. "
            "Return a JSON object with a key named results whose value is a list of objects. "
            "Each object must have: symbol, adjusted_confidence (float), refined_thesis (string), keep (bool)."
        )

        user = {
            "task": "Refine the following trade ideas.",
            "self_reflection": research.get("self_reflection"),
            "ideas": context_parts,
        }

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(user)},
                ],
                temperature=0.2,
                max_tokens=1200,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content
            data = json.loads(content)

            if isinstance(data, list):
                results = data
            elif isinstance(data, dict):
                results = data.get("results") or data.get("ideas") or data
                if isinstance(results, dict):
                    results = list(results.values())
            else:
                results = []

            if not isinstance(results, list):
                results = [results]

            refined_map = {
                r.get("symbol"): r
                for r in results
                if isinstance(r, dict) and r.get("symbol")
            }

            kept = []
            for idea in ideas:
                ref = refined_map.get(idea.symbol)
                if not ref:
                    kept.append(idea)
                    continue
                if ref.get("keep") is False:
                    console.print(f"[yellow]LLM discarded[/] {idea.symbol}")
                    continue
                new_conf = float(ref.get("adjusted_confidence", idea.confidence))
                idea.confidence = max(0.0, min(1.0, new_conf))
                if ref.get("refined_thesis"):
                    idea.thesis = ref["refined_thesis"]
                kept.append(idea)
                console.print(
                    f"[green]LLM refined[/] {idea.symbol} conf->{idea.confidence:.2f}"
                )

            return kept
        except Exception as e:
            console.print(f"[red]LLM refine failed (falling back to rules):[/] {e}")
            return ideas
