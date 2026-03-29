-- ════════════════════════════════════════════════════════════
--  CashFlow AI — Full Database Schema + Seed Data
--  Run this in Supabase → SQL Editor
-- ════════════════════════════════════════════════════════════

-- ─── Enable UUID extension ───────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─── DEPARTMENTS ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS departments (
  id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name        TEXT NOT NULL UNIQUE,
  head_count  INT  DEFAULT 0,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ─── VENDORS ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vendors (
  id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name        TEXT NOT NULL UNIQUE,
  category    TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'approved' CHECK (status IN ('approved','flagged','pending')),
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ─── TRANSACTIONS ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS transactions (
  id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  date           DATE        NOT NULL,
  vendor         TEXT        NOT NULL,
  category       TEXT        NOT NULL,
  department     TEXT        NOT NULL,
  amount         NUMERIC(12,2) NOT NULL,
  payment_method TEXT        NOT NULL DEFAULT 'Bank Transfer',
  invoice_no     TEXT,
  status         TEXT        NOT NULL DEFAULT 'pending' CHECK (status IN ('paid','pending','flagged','rejected')),
  receipt_url    TEXT,
  has_receipt    BOOLEAN     DEFAULT FALSE,
  ai_confidence  NUMERIC(5,2),
  notes          TEXT,
  created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- ─── BUDGETS ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS budgets (
  id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  department   TEXT        NOT NULL,
  month        TEXT        NOT NULL,  -- e.g. "2025-01"
  budget_amount NUMERIC(12,2) NOT NULL,
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(department, month)
);

-- ─── ANOMALIES ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS anomalies (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  transaction_id  UUID REFERENCES transactions(id) ON DELETE CASCADE,
  severity        TEXT NOT NULL CHECK (severity IN ('critical','warning','info')),
  type            TEXT NOT NULL,   -- e.g. "unknown_vendor", "duplicate", "spike"
  title           TEXT NOT NULL,
  description     TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','reviewed','resolved','dismissed')),
  z_score         NUMERIC(8,4),
  resolved_at     TIMESTAMPTZ,
  resolved_by     TEXT,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ─── UPLOADS ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS uploads (
  id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  filename      TEXT NOT NULL,
  row_count     INT  DEFAULT 0,
  categorized   INT  DEFAULT 0,
  flagged       INT  DEFAULT 0,
  status        TEXT NOT NULL DEFAULT 'processing' CHECK (status IN ('processing','done','error')),
  error_msg     TEXT,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ════════════════════════════════════════════════════════════
--  INDEXES
-- ════════════════════════════════════════════════════════════
CREATE INDEX IF NOT EXISTS idx_txn_date       ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_txn_dept       ON transactions(department);
CREATE INDEX IF NOT EXISTS idx_txn_category   ON transactions(category);
CREATE INDEX IF NOT EXISTS idx_txn_status     ON transactions(status);
CREATE INDEX IF NOT EXISTS idx_anomaly_status ON anomalies(status);
CREATE INDEX IF NOT EXISTS idx_anomaly_sev    ON anomalies(severity);

-- ════════════════════════════════════════════════════════════
--  SEED: DEPARTMENTS
-- ════════════════════════════════════════════════════════════
INSERT INTO departments (name, head_count) VALUES
  ('Engineering',   24),
  ('Sales',         18),
  ('Marketing',     12),
  ('Operations',     8),
  ('HR & Admin',     6),
  ('Infrastructure', 4),
  ('Design',         5),
  ('Product',        7)
ON CONFLICT (name) DO NOTHING;

-- ════════════════════════════════════════════════════════════
--  SEED: VENDORS
-- ════════════════════════════════════════════════════════════
INSERT INTO vendors (name, category, status) VALUES
  ('AWS Cloud',          'Software',  'approved'),
  ('GitHub Enterprise',  'Software',  'approved'),
  ('Slack Pro',          'Software',  'approved'),
  ('Figma',              'Software',  'approved'),
  ('Notion',             'Software',  'approved'),
  ('Google Ads',         'Marketing', 'approved'),
  ('LinkedIn Ads',       'Marketing', 'approved'),
  ('IndiGo Airlines',    'Travel',    'approved'),
  ('Marriott Hotels',    'Travel',    'approved'),
  ('Zomato Business',    'Office',    'flagged'),
  ('ABC Trading Pvt',    'Vendors',   'flagged'),
  ('Office Rent',        'Office',    'approved'),
  ('Webflow',            'Software',  'approved'),
  ('Datadog',            'Software',  'approved'),
  ('Loom',               'Software',  'approved')
ON CONFLICT (name) DO NOTHING;

-- ════════════════════════════════════════════════════════════
--  SEED: BUDGETS (January 2025)
-- ════════════════════════════════════════════════════════════
INSERT INTO budgets (department, month, budget_amount) VALUES
  ('Engineering',   '2025-01', 250000),
  ('Sales',         '2025-01', 200000),
  ('Marketing',     '2025-01', 200000),
  ('Operations',    '2025-01', 150000),
  ('HR & Admin',    '2025-01', 100000),
  ('Infrastructure','2025-01',  75000),
  ('Design',        '2025-01',  60000),
  ('Product',       '2025-01',  65000)
ON CONFLICT (department, month) DO NOTHING;

-- ════════════════════════════════════════════════════════════
--  SEED: TRANSACTIONS (January 2025)
-- ════════════════════════════════════════════════════════════
INSERT INTO transactions (date, vendor, category, department, amount, payment_method, invoice_no, status, has_receipt, ai_confidence) VALUES
  ('2025-01-01', 'AWS Cloud',          'Software',  'Engineering',   22000, 'Bank Transfer',  'INV-2201', 'paid',    TRUE,  0.97),
  ('2025-01-02', 'Office Rent',        'Office',    'Operations',    85000, 'NEFT',           'INV-2202', 'paid',    TRUE,  0.99),
  ('2025-01-03', 'Google Ads',         'Marketing', 'Marketing',     14500, 'Credit Card',    'INV-2203', 'paid',    TRUE,  0.96),
  ('2025-01-05', 'Slack Pro',          'Software',  'Engineering',    4100, 'Credit Card',    'INV-2204', 'paid',    TRUE,  0.98),
  ('2025-01-07', 'IndiGo Airlines',    'Travel',    'Sales',          8200, 'Credit Card',    'INV-2205', 'paid',    TRUE,  0.94),
  ('2025-01-09', 'Ravi Kumar T&E',     'Travel',    'Sales',          3800, 'Reimbursement',  'REI-0041', 'pending', FALSE, 0.78),
  ('2025-01-10', 'GitHub Enterprise',  'Software',  'Engineering',    8200, 'Credit Card',    'INV-2206', 'paid',    TRUE,  0.99),
  ('2025-01-11', 'Zomato Business',    'Office',    'HR & Admin',    18400, 'Credit Card',    'INV-2291', 'flagged', TRUE,  0.71),
  ('2025-01-12', 'ABC Trading Pvt',    'Vendors',   'Operations',    50000, 'NEFT',           'INV-2210', 'flagged', FALSE, 0.42),
  ('2025-01-14', 'Figma',             'Software',  'Design',         8200, 'Credit Card',    'INV-2211', 'paid',    TRUE,  0.97),
  ('2025-01-15', 'LinkedIn Ads',       'Marketing', 'Marketing',     22000, 'Credit Card',    'INV-2212', 'paid',    TRUE,  0.95),
  ('2025-01-18', 'Notion',             'Software',  'Product',        2400, 'Credit Card',    'INV-2213', 'paid',    TRUE,  0.98),
  ('2025-01-19', 'Marriott Hotels',    'Travel',    'Sales',         12000, 'Credit Card',    'INV-2214', 'paid',    TRUE,  0.93),
  ('2025-01-20', 'Datadog',            'Software',  'Engineering',   12000, 'Credit Card',    'INV-2215', 'paid',    TRUE,  0.97),
  ('2025-01-22', 'Google Ads',         'Marketing', 'Marketing',     18000, 'Credit Card',    'INV-2216', 'paid',    TRUE,  0.96),
  ('2025-01-24', 'IndiGo Airlines',    'Travel',    'Sales',          6200, 'Credit Card',    'INV-2217', 'paid',    TRUE,  0.94),
  ('2025-01-25', 'AWS Cloud',          'Software',  'Engineering',   22000, 'Bank Transfer',  'INV-2218', 'paid',    TRUE,  0.97),
  ('2025-01-26', 'Loom',              'Software',  'Marketing',      3200, 'Credit Card',    'INV-2219', 'paid',    TRUE,  0.96),
  ('2025-01-28', 'Webflow',            'Software',  'Marketing',      6300, 'Credit Card',    'INV-2220', 'paid',    TRUE,  0.98),
  ('2025-01-30', 'Office Rent',        'Office',    'Operations',    85000, 'NEFT',           'INV-2221', 'paid',    TRUE,  0.99),
  ('2025-01-31', 'Zomato Business',    'Office',    'HR & Admin',    18400, 'Credit Card',    'INV-2291', 'flagged', TRUE,  0.68)
ON CONFLICT DO NOTHING;

-- ════════════════════════════════════════════════════════════
--  SEED: ANOMALIES
-- ════════════════════════════════════════════════════════════
INSERT INTO anomalies (transaction_id, severity, type, title, description, status, z_score)
SELECT
  t.id,
  'critical',
  'unknown_vendor',
  'Unknown Vendor — No PO Match',
  'ABC Trading Pvt Ltd has never appeared in transaction history. Amount is 6.2× median vendor payment. No matching PO found. Vendor not on approved list.',
  'open',
  4.2
FROM transactions t WHERE t.vendor = 'ABC Trading Pvt' AND t.date = '2025-01-12'
ON CONFLICT DO NOTHING;

INSERT INTO anomalies (transaction_id, severity, type, title, description, status, z_score)
SELECT
  t.id,
  'critical',
  'duplicate_invoice',
  'Duplicate Invoice Detected',
  'Invoice #INV-2291 from Zomato Business has been paid twice — Jan 11 and Jan 31. Each payment ₹18,400. Confirmed duplicate, ₹18,400 recoverable.',
  'open',
  3.8
FROM transactions t WHERE t.vendor = 'Zomato Business' AND t.date = '2025-01-31'
ON CONFLICT DO NOTHING;

INSERT INTO anomalies (transaction_id, severity, type, title, description, status, z_score)
SELECT
  t.id,
  'warning',
  'spend_spike',
  'AWS Cloud Spend Spike',
  'AWS billed ₹22,000 — 180% above 3-month average of ₹7,850. No infrastructure change logged. Could be runaway EC2 or uncapped auto-scaling.',
  'open',
  2.6
FROM transactions t WHERE t.vendor = 'AWS Cloud' AND t.date = '2025-01-25'
ON CONFLICT DO NOTHING;

INSERT INTO anomalies (transaction_id, severity, type, title, description, status, z_score)
SELECT
  t.id,
  'info',
  'missing_receipt',
  'Missing Receipt — T&E Claim',
  'Ravi Kumar submitted ₹3,800 T&E claim without receipt. Policy requires receipts for reimbursements above ₹2,000.',
  'open',
  1.4
FROM transactions t WHERE t.vendor = 'Ravi Kumar T&E'
ON CONFLICT DO NOTHING;
