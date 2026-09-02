from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.api.v1 import router as api_v1_router

# Every session token, email-verification link and password-reset link is signed
# with this key. Shipping the placeholder would let anyone mint a token for any
# account, so refuse to start outside local development.
if not settings.DEBUG and settings.SECRET_KEY == "change-me-in-production":
    raise RuntimeError(
        "SECRET_KEY is still the default. Set a real one in .env before running "
        "outside DEBUG — it signs every auth token."
    )

app = FastAPI(
    title=settings.APP_NAME,
    description="B2B Airline Deal Management & Income Calculation Platform",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # "*" covers it today only because nothing sets withCredentials — for a credentialed
    # request the browser reads "*" as a literal header name, not a wildcard, and
    # X-Total-Count (the party list pagers) would silently come back undefined. Named
    # explicitly so that stays true if credentials are ever turned on.
    expose_headers=["*", "X-Total-Count"],
)

app.include_router(api_v1_router, prefix="/api/v1")

app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME}
