# Deploying Deliverable 3 to Hugging Face Spaces

This app is deployed by pushing the current git branch to the Space’s git repo.

## One-time Space settings
- **Settings → App configuration**
  - SDK: `Gradio`
  - App file: `project-1/app_gradio.py`
- **Settings → Variables & secrets**
  - Add secret: `PERPLEXITY_API_KEY=<your Perplexity key>`

## Configure your environment (no secrets in git)
Copy `.env.example` to `.env` and fill values:
```bash
cp .env.example .env
# edit .env and fill in real values
