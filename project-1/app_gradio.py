# app_gradio.py — Gradio UI for Deliverable 3
# Purpose:
# - Collect a player name
# - Use Perplexity to retrieve URLs
# - Score with your credibility scorer
# - Display a ranked table with scores, percentiles, hosts, URLs, and top rationales

import os
import pandas as pd
import gradio as gr

from src.pplx_client import pplx_search_sources
from src.scorer import rank_listings

def search_and_score(player: str, max_urls: int, dry_run: bool):
    # Health checks + helpful messages
    if not player or not player.strip():
        return pd.DataFrame(), "Please enter a player name."

    if not os.getenv("PERPLEXITY_API_KEY"):
        return pd.DataFrame(), (
            "Missing PERPLEXITY_API_KEY. In your Space, go to "
            "Settings → Variables and secrets → add a Secret named PERPLEXITY_API_KEY."
        )

    try:
        discovery = pplx_search_sources(player.strip(), max_urls=max_urls)
        urls = discovery.get("urls", [])
        if not urls:
            return pd.DataFrame(), f"No URLs found for '{player}'. Try a different spelling."

        rows = rank_listings(urls, dry_run=dry_run)

        # Build compact table with top rationales
        table = []
        for r in rows:
            top3 = sorted(r["signals"], key=lambda s: s["value"] * s["weight"], reverse=True)[:3]
            rationale = "; ".join([f"{s['name']}: {s['rationale']}" for s in top3])
            table.append({
                "Score": r["score"]["absolute"],
                "Pct": r["score"]["percentile"],
                "Host": r["meta"]["host"],
                "Status": r["status"],
                "URL": r["url"],
                "Top rationales": rationale,
            })

        df = pd.DataFrame(table).sort_values("Score", ascending=False, ignore_index=True)
        note = f"Found {len(urls)} URLs for {player}."
        return df, note

    except Exception as e:
        return pd.DataFrame(), f"Error: {e}"

with gr.Blocks(theme=gr.themes.Default()) as demo:
    gr.Markdown("# Soccer Card Source Credibility (RAG + Scorer)")
    gr.Markdown("Enter a player; we’ll fetch sources via Perplexity, then score each URL’s credibility.")

    with gr.Row():
        player = gr.Textbox(label="Player name", value="Bukayo Saka", scale=3)
        max_urls = gr.Slider(label="Max URLs", minimum=5, maximum=25, value=12, step=1, scale=2)
        dry_run = gr.Checkbox(label="Dry run (synthetic scoring pages)", value=False, scale=1)

    run = gr.Button("Search & Score", variant="primary")

    with gr.Row():
        out_df = gr.Dataframe(
            headers=["Score", "Pct", "Host", "Status", "URL", "Top rationales"],
            datatype=["number", "number", "str", "str", "str", "str"],
            interactive=False,
            wrap=True,
            label="Ranked sources"
        )
    note = gr.Markdown()

    with gr.Accordion("Health", open=False):
        has_key = bool(os.getenv("PERPLEXITY_API_KEY"))
        gr.Markdown(f"**PERPLEXITY_API_KEY set:** `{has_key}`  \nSet it in: Settings → Variables and secrets → Secrets")

    run.click(fn=search_and_score, inputs=[player, max_urls, dry_run], outputs=[out_df, note])

# IMPORTANT for Spaces: do not call demo.launch(); Spaces will run it automatically.
