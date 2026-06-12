"""AI generation: swappable text and image providers.

Phase 3 turns prioritized candidates into draft posts. Text generation goes
through :mod:`opensocial.ai.text` (LiteLLM by default, Ollama with no API key);
images through :mod:`opensocial.ai.images` (Unsplash photos or the source item's
own media — AI image generation was removed). Both sit behind small interfaces
so providers are interchangeable and tests can inject deterministic fakes
without any network or model.
"""
