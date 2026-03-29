-- 🔐 CashFlow AI - Database Schema Setup
-- 📅 Date: 2025-03-29
-- 💡 Instructions: Paste this in your Supabase SQL Editor and click "Run".

-- 1️⃣ Create TRANSACTIONS table
CREATE TABLE IF NOT EXISTS public.transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    date DATE NOT NULL,
    vendor TEXT NOT NULL,
    amount DECIMAL(12,2) NOT NULL,
    category TEXT DEFAULT 'Other',
    department TEXT DEFAULT 'Operations',
    payment_method TEXT DEFAULT 'Bank Transfer',
    status TEXT DEFAULT 'pending',
    has_receipt BOOLEAN DEFAULT FALSE,
    invoice_no TEXT,
    notes TEXT,
    ai_confidence DECIMAL(3,2) DEFAULT 0.85
);

-- 2️⃣ Create ANOMALIES table
CREATE TABLE IF NOT EXISTS public.anomalies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    transaction_id UUID REFERENCES public.transactions(id) ON DELETE CASCADE,
    type TEXT NOT NULL,              -- e.g., 'Duplicate', 'High Spend', 'Category Shift'
    severity TEXT DEFAULT 'medium',  -- e.g., 'low', 'medium', 'high'
    description TEXT,
    is_resolved BOOLEAN DEFAULT FALSE
);

-- 3️⃣ Create UPLOADS log table
CREATE TABLE IF NOT EXISTS public.uploads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    filename TEXT NOT NULL,
    row_count INTEGER DEFAULT 0,
    categorized INTEGER DEFAULT 0,
    flagged INTEGER DEFAULT 0,
    status TEXT DEFAULT 'processing'
);

-- 4️⃣ Create BUDGETS table (Essential for Dashboard Summary)
CREATE TABLE IF NOT EXISTS public.budgets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    month TEXT NOT NULL,             -- format: YYYY-MM
    department TEXT NOT NULL,
    budget_amount DECIMAL(12,2) NOT NULL
);

-- 5️⃣ (OPTIONAL) Add sample budgets for January 2025
INSERT INTO public.budgets (month, department, budget_amount)
VALUES 
    ('2025-01', 'Operations', 500000),
    ('2025-01', 'Sales', 200000),
    ('2025-01', 'IT', 150000),
    ('2025-01', 'Design', 50000),
    ('2025-01', 'Marketing', 300000)
ON CONFLICT DO NOTHING;

-- 4️⃣ Enable Row Level Security (OPTIONAL: For now we allow service role access)
-- ALTER TABLE public.transactions ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.anomalies ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.uploads ENABLE ROW LEVEL SECURITY;

-- 5️⃣ Allow public access for development (IF you don't use Auth yet)
-- CREATE POLICY "allow_all" ON public.transactions FOR ALL USING (true);
-- CREATE POLICY "allow_all" ON public.anomalies FOR ALL USING (true);
-- CREATE POLICY "allow_all" ON public.uploads FOR ALL USING (true);
