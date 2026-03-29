from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings

from routes import summary, transactions, upload, anomalies, budgets, chat

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
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(summary.router,      prefix="/api/summary",      tags=["Summary"])
app.include_router(transactions.router, prefix="/api/transactions",  tags=["Transactions"])
app.include_router(upload.router,       prefix="/api/upload",        tags=["Upload"])
app.include_router(anomalies.router,    prefix="/api/anomalies",     tags=["Anomalies"])
app.include_router(budgets.router,      prefix="/api/budgets",       tags=["Budgets"])
app.include_router(chat.router,         prefix="/api/chat",          tags=["AI Chat"])


@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "service": "CashFlow AI", "version": "1.0.0"}


@app.get("/health", tags=["Health"])
def health():
    return {"status": "healthy"}
