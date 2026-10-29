"""Read the system instructions kept beside this loader."""
from pathlib import Path


def load_prompt(name: str) -> str:
    try:
        return Path(__file__).with_name(name + ".md").read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"Missing Muse prompt: {name}.md") from None
