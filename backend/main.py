"""FastAPI server: streams the LangGraph blog agent's progress to the browser (SSE)
and serves the frontend folder.

Run from the backend folder:  uvicorn backend.main:app --reload
Then open http://127.0.0.1:8000
"""
import json
import sys
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

import logging
logger = logging.getLogger("uvicorn.error")

# Windows needs the Proactor loop for subprocesses (the MCP stdio server).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


from backend.agent import build_graph

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
MAX_ITERATION = 3  # evaluator loops; each loop re-runs every worker, so keep it small


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.agent = await build_graph()  # builds graph + starts the MCP tool once
    yield


app = FastAPI(title="Blog Writing Agent", lifespan=lifespan)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def describe(node: str, update: dict) -> dict:
    """Turn a node's state update into a small, UI-friendly payload."""
    if node == "router":
        return {"mode": update.get("mode"), "needs_research": update.get("needs_research"),
                "queries": update.get("queries", [])}
    if node == "research":
        ev = update.get("evidence", [])
        return {"count": len(ev), "sources": [{"title": e.title, "url": e.url} for e in ev[:8]]}
    if node == "orchestrator":
        plan = update["plan"]
        return {"title": plan.blog_title,
                "tasks": [{"id": t.id_, "title": t.title, "worker": t.worker_type,
                           "words": t.target_words} for t in plan.tasks]}
    if node == "worker":
        s = update["sections"][0]
        return {"id": s["id"], "words": len(s["content"].split())}
    if node == "reducer":
        return {}
    if node == "evaluate":
        return {"evaluation": update["evaluation"], "feedback": update["feedback"],
                "iteration": update["iteration"]}
    return {}


@app.get("/api/generate")
async def generate(topic: str = Query(..., min_length=3, max_length=2000)):
    async def stream():
        final = ""
        logger.info(f"Started blog: {topic}")
        try:
            inputs = {"topic": topic, "iteration": 1, "max_iteration": MAX_ITERATION}
            async for chunk in app.state.agent.astream(inputs, stream_mode="updates"):
                for node, update in chunk.items():
                    if not update:
                        continue
                    logger.info(f"Finished step: {node}")
                    if node == "reducer":
                        final = update["final"]
                    yield sse("step", {"node": node, **describe(node, update)})
            logger.info("Blog finished OK")
            yield sse("final", {"markdown": final})
        except Exception as e:  # surface errors in the UI instead of a dead stream
            logger.exception("Blog generation failed.")
            yield sse("error", {"message": f"{type(e).__name__}: {e}"})
        yield sse("done", {})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# Serve the frontend at "/" (mounted last so /api routes win)
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")