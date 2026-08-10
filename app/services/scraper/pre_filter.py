"""Fast Pre-Filter Module (Bypassed per user request to process all posts with LLMs)."""


def passes_pre_filter(text: str) -> bool:
    """Pre-filter bypassed to allow all posts directly into LLM processing queue."""
    if not text or len(text.strip()) < 5:
        return False
    return True
