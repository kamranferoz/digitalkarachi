"""Content generation framework for DigitalKarachi.com.

Submodules:
- schema:  Post / NewsItem dataclasses + JSON validation
- llm:     provider-agnostic LLM interface (Ollama impl today)
- topics:  per-category seed topic banks + dedup
- blog:    long-form blog generator
- news:    RSS-rewrite news dispatch generator
- rss:     RSS feed fetcher + dedup
"""
