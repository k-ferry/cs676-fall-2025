# app.py — Streamlit front-end for Deliverable 3
import os
import streamlit as st
import pandas as pd

from src.pplx_client import pplx_search_sources
from src.scorer import rank_listings

st.set_page_config(page_title="Soccer Card Source Credibility", layout="wide")
st.title("Soccer Card Source Credibility (RAG + Scorer)")
st.caption("Enter a player; we’ll fetch recent sources via Perplexity, then score each URL’s credibility.")

# In Colab, you can set this env var at runtime from Secrets (see notebook cell):
# os.environ['PERPLEXITY_API_KEY'] = '...'  # (handled in notebook)

player = st.text_input("Player name", value="Bukayo Saka")
col_a, col_b, col_c = st.columns([1,1,2])
with col_a:
    max_urls = st.slider("Max URLs", min_value=5, max_value=25, value=12, step=1)
with col_b:
    dry_run = st.checkbox("Dry run (synthetic pages for scoring)", value=False)
with col_c:
    st.info("Scores are 0–100 with percentiles within this cohort. Click a row for rationale in the URL.")

if st.button("Search & Score") and player.strip():
    with st.spinner("Searching Perplexity and scoring sources..."):
        discovery = pplx_search_sources(player.strip(), max_urls=max_urls)
        urls = discovery["urls"]
        if not urls:
            st.warning("No URLs found. Try a different player spelling or a well-known card.")
        else:
            rows = rank_listings(urls, dry_run=dry_run)

            # Build table with top signal rationales (compact)
            table = []
            for r in rows:
                top3 = sorted(r["signals"], key=lambda s: s["value"]*s["weight"], reverse=True)[:3]
                rationale = "; ".join([f"{s['name']}: {s['rationale']}" for s in top3])
                table.append({
                    "Score": r["score"]["absolute"],
                    "Pct": r["score"]["percentile"],
                    "Host": r["meta"]["host"],
                    "Status": r["status"],
                    "URL": r["url"],
                    "Top rationales": rationale
                })
            df = pd.DataFrame(table).sort_values("Score", ascending=False)
            st.dataframe(df, use_container_width=True)
            st.caption(f"Perplexity returned {len(urls)} URLs for {player.strip()}.")
