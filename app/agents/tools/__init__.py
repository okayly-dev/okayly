"""Route Muse calls only to the read tools offered by the current agent."""
from ..loop import load_args
from . import (
    reviews_get_review, reviews_get_practice_facts, reviews_get_past_replies,
    ads_get_practice_facts, ads_get_ad_rules,
)

REVIEW_TOOLS = [reviews_get_review, reviews_get_practice_facts, reviews_get_past_replies]
AD_TOOLS = [ads_get_practice_facts, ads_get_ad_rules]


def definitions(tools):
    return [tool.DEFINITION for tool in tools]


def run_tool(tools, context, name, raw_args) -> dict:
    args = load_args(raw_args)
    if args is None:
        # Keep the ad agent's existing malformed-argument message.
        if tools == AD_TOOLS:
            return {"error": "this tool takes no arguments; send {}"}
        return {"error": "arguments must be a JSON object"}
    if tools == AD_TOOLS and args:
        return {"error": "this tool takes no arguments; send {}"}
    offered = {tool.NAME: tool for tool in tools}
    if name not in offered:
        return {"error": f"unknown tool {name}"}
    return offered[name].run(context, args)
