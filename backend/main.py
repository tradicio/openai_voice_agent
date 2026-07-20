import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from api.websocket import websocket_endpoint

# Load environment variables
load_dotenv(".env", override=True)
load_dotenv(".env.example")

# Configure logging
log_level = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    logger.info("FastAPI backend starting up")
    yield
    logger.info("FastAPI backend shutting down")


# Create FastAPI app
app = FastAPI(
    title="OpenAI Realtime Voice Chat Backend",
    description="FastAPI backend for real-time voice chat using OpenAI Realtime API",
    version="0.1.0",
    lifespan=lifespan
)

# Add CORS middleware
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url, "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info(f"CORS configured for frontend URL: {frontend_url}")

# Include routers
app.include_router(router)

# WebSocket route
app.add_api_websocket_route("/ws/audio", websocket_endpoint)

logger.info("FastAPI app initialized with routes and WebSocket endpoint")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=log_level.lower()
    )
