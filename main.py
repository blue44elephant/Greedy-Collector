"""Greedy Collector standalone FastAPI application.

Run with:
    uvicorn main:app --reload

Or for production:
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from greedy_collector.chains.registry import ChainError
from fastapi.staticfiles import StaticFiles

from greedy_collector import router as greedy_collector_router
from greedy_collector.config import get_settings
from greedy_collector.monitoring import start_monitoring, stop_monitoring
from greedy_collector.discovery.runtime import start_discovery, stop_discovery

settings = get_settings()

app = FastAPI(
    title="Greedy Collector",
    description="Public-blockchain risk assessment, wallet monitoring, and transaction graph analysis.",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

@app.exception_handler(ChainError)
async def chain_error_handler(request,exc):
    return JSONResponse(status_code=422,content={"detail":exc.code})


# Add CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Greedy Collector router
app.include_router(greedy_collector_router)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
async def startup_event():
    """Start monitoring tasks on application startup."""
    start_monitoring()
    await start_discovery(app)


@app.on_event("shutdown")
async def shutdown_event():
    """Stop monitoring tasks on application shutdown."""
    await stop_discovery(app)
    stop_monitoring()


@app.get("/", include_in_schema=False)
def root():
    """Serve the standalone Greedy Collector application."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "application": "Greedy Collector",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
