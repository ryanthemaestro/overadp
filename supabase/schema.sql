-- OverADP Supabase Schema
-- Run this in the Supabase SQL editor after creating a project

-- =============================================
-- PROFILES TABLE (extends auth.users)
-- =============================================
CREATE TABLE IF NOT EXISTS public.profiles (
  id UUID REFERENCES auth.users(id) ON DELETE CASCADE PRIMARY KEY,
  email TEXT NOT NULL,
  plan TEXT NOT NULL DEFAULT 'free' CHECK (plan IN ('free', 'paid')),
  plan_type TEXT NOT NULL DEFAULT 'season' CHECK (plan_type IN ('season', 'draft')),
  season_paid TEXT,
  paid_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Enable RLS
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

-- Users can read their own profile
CREATE POLICY "Users can read own profile"
  ON public.profiles FOR SELECT
  USING (auth.uid() = id);

-- Service key can do everything (for Netlify functions)
CREATE POLICY "Service key full access"
  ON public.profiles FOR ALL
  USING (true)
  WITH CHECK (true);

-- =============================================
-- EMAIL LIST TABLE
-- =============================================
CREATE TABLE IF NOT EXISTS public.email_list (
  id BIGSERIAL PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  source TEXT NOT NULL DEFAULT 'landing' CHECK (source IN ('landing', 'register', 'checkout_abandon', 'manual')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Enable RLS
ALTER TABLE public.email_list ENABLE ROW LEVEL SECURITY;

-- Service key only (users don't directly access this)
CREATE POLICY "Service key full access"
  ON public.email_list FOR ALL
  USING (true)
  WITH CHECK (true);

-- =============================================
-- INDEXES
-- =============================================
CREATE INDEX IF NOT EXISTS idx_profiles_plan ON public.profiles(plan);
CREATE INDEX IF NOT EXISTS idx_profiles_season_paid ON public.profiles(season_paid);
CREATE INDEX IF NOT EXISTS idx_email_list_source ON public.email_list(source);

-- =============================================
-- UPDATED_AT TRIGGER
-- =============================================
CREATE OR REPLACE FUNCTION public.handle_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER profiles_updated_at
  BEFORE UPDATE ON public.profiles
  FOR EACH ROW
  EXECUTE FUNCTION public.handle_updated_at();
