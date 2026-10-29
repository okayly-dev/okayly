"""Read the practice's most recent replies, for tone only."""

# Keep the name Muse sees unchanged.
NAME = 'reviews.get_past_replies'

# Muse needs this schema to request the read.
DEFINITION = {
    "type": "function",
    "name": "reviews.get_past_replies",
    "strict": True,
    "description": "Read the practice's most recent replies, for tone only.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "limit"
        ],
        "properties": {
            "limit": {
                "type": "integer"
            }
        }
    }
}


def run(context, args: dict) -> dict:
    # Check model arguments before reading the context.
    limit = args.get("limit")
    if set(args) != {"limit"} or not isinstance(limit, int) or isinstance(limit, bool):
        return {"error": "expected {limit: integer}"}
    return {"replies": context.past_replies(max(1, min(limit, 10)))}
