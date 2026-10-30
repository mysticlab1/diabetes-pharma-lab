# Diabetes Pharma Intelligence Cloud Monitor

한국어 안내: [README_처음부터_배포하기.md](README_처음부터_배포하기.md)

A GitHub Pages/Actions project that checks three public sources daily, snapshots metadata, and shows a mobile-friendly Korean research dashboard. **Not a clinical decision support system.** Before first deployment, the dashboard is empty by design; the first Actions run attempts the initial data import.

Public sources: PubMed E-utilities, ClinicalTrials.gov API v2, openFDA drug labeling API. Domestic MFDS/HIRA automation is not yet included. Optional OpenAI-assisted screening only if the repository owner sets `OPENAI_API_KEY` in Actions secrets.

Run `python -m unittest discover -s tests -v` to verify offline data parsing and update idempotence; run `python update_site.py --live` for public API fetches after network access is available.
