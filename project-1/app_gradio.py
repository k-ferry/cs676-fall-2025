# project-1/app_gradio.py
# Minimal, reliable Gradio app that:
#  - lets you enter a player name
#  - (optionally) calls Perplexity to fetch URLs
#  - scores URLs with scorer.rank_listings
#  - ALWAYS calls demo.launch() so Spaces boots correctly

from __future__ import annotations
import os
import traceback
import pandas as pd
import gradio as gr

# Local imports (your repo structure)
from src.scorer import rank_listings, score_url
from src.pplx_client import pplx_search_sources

APP_TITLE = "Soccer Card Credibility (Deliverable 3)"
APP_DESC = "Enter a player, optionally search with Perplexity, and score the returned listing URLs."

def _to_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    # Flatten signals a bit for display
    def top3(siglist):
        siglist = sorted(siglist, key=lambda s: s["value"] * s["weight"], reverse=True)
        return ", ".join(f"{s['name']}" for s in siglist[:3])
    out = []
    for r in rows:
        out.append({
            "score_abs": r["score"]["absolute"],
            "score_pct": r["score"]["percentile"],
            "status": r["status"],
            "url": r["url"],
            "host": r["meta"].get("host"),
            "top_signals": top3(r["signals"]),
            "errors": "; ".join(r.get("errors") or []),
        })
    df = pd.DataFrame(out).sort_values("score_abs", ascending=False)
    return df

def score_player(
    player: str,
    max_urls: int,
    use_perplexity: bool,
    dry_run: bool,
    manual_urls_text: str,
) -> tuple[str, pd.DataFrame]:
    """
    Returns (log_text, dataframe)
    """
    logs = []
    try:
        urls = []
        if use_perplexity:
            key = os.getenv("PERPLEXITY_API_KEY")
            if not key:
                return ("PERPLEXITY_API_KEY is not set in Space Secrets. "
                        "Go to Settings → Variables & secrets and add it.",
                        pd.DataFrame())
            res = pplx_search_sources(player, max_urls=max_urls, api_key=key)
            urls = res.get("urls", [])
            logs.append(f"Perplexity returned {len(urls)} URL(s).")
        else:
            # Manual URLs: one per line or space-separated
            if manual_urls_text.strip():
                urls = [u.strip() for u in manual_urls_text.replace("\r","").splitlines() if u.strip()]
                if not urls:
                    # fallback: split by spaces
                    urls = [u for u in manual_urls_text.split() if u.startswith("http")]
                logs.append(f"Using {len(urls)} manual URL(s).")
            else:
                # No Perplexity and no manual URLs → demo URLs
                urls = [
                    "https://www.ebay.com/itm/123",
                    "https://www.comc.com/Cards/Soccer",
                    "http://example.com/article",
                ]
                logs.append("No URLs provided. Using demo URLs.")

        if not urls:
            return ("No URLs to score.", pd.DataFrame())

        rows = rank_listings(urls, dry_run=dry_run)
        df = _to_df(rows)
        if dry_run:
            logs.append("dry_run=True (synthetic pages) — no network fetch.")
        else:
            logs.append("dry_run=False — fetched live pages (may be slower).")

        return ("\n".join(logs), df)
    except Exception as e:
        err = f"Exception: {e}\n{traceback.format_exc()}"
        return (err, pd.DataFrame())

with gr.Blocks(title=APP_TITLE) as demo:
    gr.Markdown(f"# {APP_TITLE}\n{APP_DESC}")

    with gr.Row():
        player = gr.Textbox(label="Player", value="Bukayo Saka", placeholder="Enter a player name")
        max_urls = gr.Slider(1, 20, value=10, step=1, label="Max URLs")

    with gr.Row():
        use_perplexity = gr.Checkbox(value=True, label="Use Perplexity to search for URLs")
        dry_run = gr.Checkbox(value=False, label="Dry run (use synthetic pages)")

    manual_urls = gr.Textbox(
        label="Manual URLs (one per line, used only if Perplexity is OFF)",
        placeholder="https://www.ebay.com/itm/...\nhttps://www.pwccmarketplace.com/..."
    )

    run_btn = gr.Button("Search & Score", variant="primary")

    logs = gr.Textbox(label="Logs", lines=6)
    table = gr.Dataframe(
        headers=["score_abs","score_pct","status","url","host","top_signals","errors"],
        interactive=False,
        wrap=True
    )

    run_btn.click(
        fn=score_player,
        inputs=[player, max_urls, use_perplexity, dry_run, manual_urls],
        outputs=[logs, table],
        show_progress=True
    )

# IMPORTANT: Start the app explicitly so Spaces sees an initialized app.
if __name__ == "__main__":
    demo.launch()
