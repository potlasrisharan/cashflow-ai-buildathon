# CashFlow AI — Backend

FastAPI backend for the CashFlow AI expense intelligence dashboard.

## Stack

| Layer       | Tech                          |
|-------------|-------------------------------|
| Framework   | FastAPI + Uvicorn             |
| Database    | Supabase (Postgres)           |
| AI          | Groq (LLaMA3-8b)             |
| OCR         | OCR.space                     |
| Analytics   | NumPy / SciPy / Pandas        |

---

## Quick Start

### 1. Set up environment

```bash
cd cashflow-backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your 3 API keys (see below).

### 2. Set up Supabase

1. Create a free project at [supabase.com](https://supabase.com)
2. Go to **SQL Editor** → paste the full contents of `schema.sql` → **Run**
3. Copy your **Project URL** and **anon key** from **Settings → API**

### 3. Get API Keys

| Key | Where to get |
|-----|------|
| `SUPABASE_URL` + `SUPABASE_KEY` | [supabase.com](https://supabase.com) → Settings → API |
| `GROQ_API_KEY` | [console.groq.com/keys](https://console.groq.com/keys) — free tier available |
| `OCR_SPACE_API_KEY` | [ocr.space/ocrapi](https://ocr.space/ocrapi) — register for free key |

### 4. Run the server

```bash
source venv/bin/activate
uvicorn main:app --reload --port 8000
```

Server runs at: **http://localhost:8000**  
Interactive docs: **http://localhost:8000/docs**

---

## API Endpoints

### Dashboard
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/summary?month=2025-01` | All KPI metrics |
| GET | `/api/summary/spend-by-category` | Donut chart data |
| GET | `/api/summary/spend-by-dept` | Department bar chart |
| GET | `/api/summary/trend` | Daily spend trend |

### Transactions
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/transactions` | Paginated list (filter by month, dept, category, status) |
| POST | `/api/transactions` | Create new transaction |
| GET | `/api/transactions/{id}` | Single transaction |
| PATCH | `/api/transactions/{id}` | Update status/notes |
| DELETE | `/api/transactions/{id}` | Delete |
| GET | `/api/transactions/stats/by-category` | Aggregated by category |
| GET | `/api/transactions/stats/by-dept` | Aggregated by department |

### Upload
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/upload/csv` | Upload CSV → AI categorization + anomaly detection |
| POST | `/api/upload/receipt` | Upload receipt image → OCR extraction |
| GET | `/api/upload/history` | List all past uploads |

### Anomalies
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/anomalies` | List with filters (severity, status) |
| GET | `/api/anomalies/{id}` | Single anomaly + linked transaction |
| PATCH | `/api/anomalies/{id}/resolve` | Mark resolved |
| PATCH | `/api/anomalies/{id}/dismiss` | Dismiss |
| POST | `/api/anomalies/scan?month=2025-01` | Re-run anomaly detection |

### Budgets
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/budgets?month=2025-01` | All dept budgets |
| GET | `/api/budgets/utilization` | Budget vs actual + status |
| POST | `/api/budgets` | Set/upsert a budget |
| DELETE | `/api/budgets/{dept}/{month}` | Remove a budget |

### AI Chat
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Finance Q&A with conversation history |

---

## CSV Upload Format

Minimum required columns:

```csv
date,vendor,amount
2025-01-15,AWS Cloud,22000
2025-01-16,Google Ads,14500
```

Optional columns: `department`, `category`, `payment_method`, `invoice_no`, `notes`

Missing `category`/`department` → auto-filled by Groq AI.

---

## Anomaly Detection

The service uses 4 detectors:

1. **Spend Spike** — Z-score > 2.5σ above vendor mean
2. **Unknown Vendor** — ≤1 prior transaction + amount > ₹5,000
3. **Duplicate Invoice** — same vendor + same amount in same batch
4. **Missing Receipt** — reimbursement > ₹2,000 with `has_receipt=false`

---

## Project Structure

```
cashflow-backend/
├── main.py              ← FastAPI app + CORS + route registration
├── config.py            ← Pydantic settings from .env
├── db.py                ← Supabase client singleton
├── requirements.txt
├── schema.sql           ← Full DB schema + seed data
├── .env.example
├── routes/
│   ├── summary.py       ← Dashboard KPIs
│   ├── transactions.py  ← CRUD + aggregations
│   ├── upload.py        ← CSV + receipt upload
│   ├── anomalies.py     ← Anomaly management
│   ├── budgets.py       ← Budget CRUD + utilization
│   └── chat.py          ← AI Q&A endpoint
└── services/
    ├── ai_service.py       ← Groq LLaMA3 categorization + chat
    ├── ocr_service.py      ← OCR.space receipt parsing
    └── anomaly_service.py  ← Z-score anomaly detection
```
