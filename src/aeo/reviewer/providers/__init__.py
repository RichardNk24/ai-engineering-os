from aeo.reviewer.providers.base import ReviewProvider
from aeo.reviewer.providers.openai import OpenAIReviewProvider


def build_provider(name: str) -> ReviewProvider:
    normalized = name.strip().lower()
    if normalized == "openai":
        return OpenAIReviewProvider()
    raise RuntimeError(f"Unsupported review provider: {name}")
