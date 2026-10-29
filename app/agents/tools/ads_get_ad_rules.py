"""Read the rules every ad and picture must follow."""

# Keep the name Muse sees unchanged.
NAME = 'ads.get_ad_rules'

# Muse needs this schema to request the read.
DEFINITION = {
    "type": "function",
    "name": "ads.get_ad_rules",
    "strict": True,
    "description": "Read the rules every ad and picture must follow.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {}
    }
}


def run(context, args: dict) -> dict:
    # Check model arguments before reading the context.
    if args:
        return {"error": "this tool takes no arguments; send {}"}
    return {"rules": context.ad_rules()}
