# getting necessary packages
from mcp.server.fastmcp import FastMCP
from ddgs import DDGS

# creating a mcp server
mcp = FastMCP("WebSearchServer")

# creating a search tool
@mcp.tool()
async def search_web(query: str, max_results: int = 5) -> list[dict]:
    """
    Search the internet and return relevant web results.

    Args:
    - query : The search query
    - max_results : Maximum number of results
    """

    results = DDGS().text(query, max_results = max_results)

    normalized = []

    for result in results:
        normalized.append(
            {
                "title" : result.get("title", ""),
                "url" : result.get("href", ""),
                "snippet" : result.get("body", ""),
                "published_at" : None,
                "source" : None
            }
        )

    return normalized


if __name__ == "__main__":
    mcp.run(transport="stdio") # start the server