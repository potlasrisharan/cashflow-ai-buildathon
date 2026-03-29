from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings

from routes import summary, transactions, upload, anomalies, budgets, chat
from security import require_api_key

app = FastAPI(
    title="CashFlow AI",
    description="AI-powered expense intelligence backend",
    version="1.0.0",
    docs_url="/docs" if settings.APP_ENV != "production" else None,
    redoc_url="/redoc" if settings.APP_ENV != "production" else None,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
api_dependencies = [Depends(require_api_key)]

app.include_router(summary.router,      prefix="/api/summary",      tags=["Summary"], dependencies=api_dependencies)
app.include_router(transactions.router, prefix="/api/transactions",  tags=["Transactions"], dependencies=api_dependencies)
app.include_router(upload.router,       prefix="/api/upload",        tags=["Upload"], dependencies=api_dependencies)
app.include_router(anomalies.router,    prefix="/api/anomalies",     tags=["Anomalies"], dependencies=api_dependencies)
app.include_router(budgets.router,      prefix="/api/budgets",       tags=["Budgets"], dependencies=api_dependencies)
app.include_router(chat.router,         prefix="/api/chat",          tags=["AI Chat"], dependencies=api_dependencies)


@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "service": "CashFlow AI", "version": "1.0.0"}


@app.get("/health", tags=["Health"])
def health():
    return {"status": "healthy"}
