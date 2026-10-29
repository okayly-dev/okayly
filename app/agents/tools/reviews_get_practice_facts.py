"""Read the practice's approved details: office phone, parking, hours, voice and tone."""

# Keep the name Muse sees unchanged.
NAME = 'reviews.get_practice_facts'

# Muse needs this schema to request the read.
DEFINITION = {
    "type": "function",
    "name": "reviews.get_practice_facts",
    "strict": True,
    "description": "Read the practice's approved details: office phone, parking, hours, voice and tone.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {}
    }
}


def run(context, args: dict) -> dict:
    # Check model arguments before reading the context.
    return context.facts()
