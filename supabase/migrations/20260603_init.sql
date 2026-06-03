CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_articles (
  idx INT PRIMARY KEY,
  title TEXT NOT NULL,
  youtube_url TEXT,
  video_id TEXT,
  download_type TEXT,
  download_href TEXT,
  transcript_chars INT DEFAULT 0,
  download_chars INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_insights (
  id SERIAL PRIMARY KEY,
  article_idx INT NOT NULL REFERENCES knowledge_articles(idx),
  target_who TEXT NOT NULL,
  target_industry TEXT,
  pain_point TEXT NOT NULL,
  existing_solution TEXT,
  automation_opportunity TEXT,
  market_hint TEXT,
  tags TEXT[] DEFAULT '{}',
  confidence REAL DEFAULT 0.0,
  embedding vector(1536),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_insights_article ON knowledge_insights(article_idx);
CREATE INDEX IF NOT EXISTS idx_insights_tags ON knowledge_insights USING GIN(tags);

CREATE TABLE IF NOT EXISTS hypotheses (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  insight_ids INT[] DEFAULT '{}',
  summary TEXT,
  target_who TEXT,
  solution_type TEXT,
  confidence_score REAL DEFAULT 0.0,
  status TEXT DEFAULT 'draft',
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS test_campaigns (
  id SERIAL PRIMARY KEY,
  hypothesis_id INT REFERENCES hypotheses(id),
  channel TEXT,
  content TEXT,
  metrics JSONB DEFAULT '{}',
  result TEXT DEFAULT 'pending',
  created_at TIMESTAMPTZ DEFAULT now()
);
