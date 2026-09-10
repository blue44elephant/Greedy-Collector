"""Greedy Collector standalone FastAPI application.

Run with:
    uvicorn main:app --reload

Or for production:
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from greedy_collector import router as greedy_collector_router
from greedy_collector.config import get_settings
from greedy_collector.monitoring import start_monitoring, stop_monitoring

settings = get_settings()

app = FastAPI(
    title="Greedy Collector",
    description="Public-blockchain risk assessment, wallet monitoring, and transaction graph analysis.",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

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


@app.on_event("startup")
async def startup_event():
    """Start monitoring tasks on application startup."""
    start_monitoring()


@app.on_event("shutdown")
async def shutdown_event():
    """Stop monitoring tasks on application shutdown."""
    stop_monitoring()


@app.get("/")
def root():
    """Root endpoint - redirects to API documentation."""
    return {
        "application": "Greedy Collector",
        "version": "0.1.0",
        "status": "running",
        "docs": "/docs",
        "health": "/api/greedy-collector/status",
    }


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
