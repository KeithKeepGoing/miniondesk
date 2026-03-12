# Skill: web-search

You now have access to the `web_search` tool.

## When to use
- User asks about current events, recent news, or live data
- You need to look up facts you are uncertain about
- User explicitly asks you to search the web

## Usage
Call `web_search` with a clear, concise query. Summarize the results in your reply.
Do NOT call it for questions you can answer confidently from knowledge.
Do NOT call it more than 3 times per conversation turn.

## Tool signature
```
web_search(query: str) → str
```
Returns a JSON string with top results from DuckDuckGo Instant Answer API.
