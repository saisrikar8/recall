"""Conservative, inspectable query routing for local multimodal search."""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryRoute:
    channel: str
    reason: str


def route_query(text: str) -> QueryRoute:
    """Use only query wording, never evaluation labels or expected pages.

    Ambiguous and factual queries keep text ranking. Explicit requests to find a
    visual use fused ranking so captions and extracted text remain useful.
    """
    query = ' '.join(text.casefold().split())
    # Instructions to create a graphic differ from requests to retrieve an existing one.
    if re.match(r'^how (?:do|can|should) (?:i|we) (?:draw|plot|create|generate)\b', query):
        return QueryRoute('text', 'Instruction to create a graphic')
    if re.search(r'\b(?:handwritten|handwriting|graph paper|squared background)\b',query):
        return QueryRoute('combined','Request describing visual handwriting or page appearance')
    visual = r'(?:images?|photos?|pictures?|illustrations?|diagrams?|charts?|graphs?|screenshots?|montages?|drawings?|sketch(?:es)?|figures?|plots?)'
    if (re.search(r'\b(?:this|that|the|an?|which|what)\s+' + visual + r'\b', query)
            or re.search(r'\b(?:find|show|locate|retrieve)(?:\s+me)?\s+(?:(?:a|an|the)\s+)?' + visual + r'\b', query)
            or re.match(r'^' + visual + r'\s+(?:of|showing|depicting|with)\b', query)):
        return QueryRoute('combined', 'Request involving visual content')
    return QueryRoute('text', 'Default to text for ambiguous wording')


def selective_rankings(queries, text_rankings, combined_rankings):
    rankings, routes = {}, {}
    for query in queries:
        route = route_query(query['text'])
        identity = query['id']
        rankings[identity] = (combined_rankings if route.channel == 'combined' else text_rankings)[identity]
        routes[identity] = dict(channel=route.channel, reason=route.reason)
    return rankings, routes


def scene_intent(query):
    """Prioritize appearance for explicit photo/illustration retrieval requests."""
    return (route_query(query).channel == 'combined' and
            bool(re.search(r'\b(?:images?|photos?|photographs?|pictures?|illustrations?|screenshots?|paintings?|handwritten|handwriting|graph paper|squared background)\b', query, re.I)))
