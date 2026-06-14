CREATE TABLE IF NOT EXISTS round (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  finished_at TIMESTAMP,
  status TEXT NOT NULL DEFAULT 'initialized',
  dry_run INTEGER NOT NULL DEFAULT 1,
  total_slots INTEGER NOT NULL DEFAULT 0,
  config_snapshot TEXT,
  summary TEXT,
  error_log TEXT
);

CREATE TABLE IF NOT EXISTS round_stage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  round_id INTEGER NOT NULL,
  stage_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  finished_at TIMESTAMP,
  result_payload TEXT,
  error_log TEXT,
  FOREIGN KEY (round_id) REFERENCES round(id)
);

CREATE INDEX IF NOT EXISTS idx_round_stage_round_id ON round_stage(round_id);

CREATE TABLE IF NOT EXISTS candidate_score (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  round_id INTEGER NOT NULL,
  serial_id TEXT,
  task_id TEXT,
  app_id TEXT,
  title TEXT,
  language TEXT,
  final_score REAL NOT NULL DEFAULT 0,
  tier TEXT,
  score_breakdown TEXT,
  raw_payload TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (round_id) REFERENCES round(id)
);

CREATE INDEX IF NOT EXISTS idx_candidate_score_round_id ON candidate_score(round_id);
CREATE INDEX IF NOT EXISTS idx_candidate_score_serial_id ON candidate_score(serial_id);

CREATE TABLE IF NOT EXISTS account (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id TEXT NOT NULL UNIQUE,
  owner_agent_id TEXT,
  publish_account_id TEXT,
  team_id TEXT,
  platform TEXT NOT NULL,
  language TEXT NOT NULL,
  country TEXT,
  provider TEXT DEFAULT 'bundle_social',
  tier TEXT DEFAULT 'new',
  daily_post_limit INTEGER DEFAULT 3,
  status TEXT DEFAULT 'active',
  social_name TEXT,
  social_account_id TEXT,
  channel_id TEXT,
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_account_platform_language ON account(platform, language, status);

CREATE TABLE IF NOT EXISTS drama_pick (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  round_id INTEGER NOT NULL,
  serial_id TEXT,
  task_id TEXT,
  title TEXT,
  app_id TEXT,
  language TEXT,
  history_payload TEXT,
  tier TEXT,
  final_score REAL,
  score_breakdown TEXT,
  ai_reason TEXT,
  slot_count INTEGER DEFAULT 0,
  status TEXT DEFAULT 'picked',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (round_id) REFERENCES round(id)
);

CREATE TABLE IF NOT EXISTS video_asset (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  round_id INTEGER,
  drama_pick_id INTEGER,
  source_clip_path TEXT,
  episode_number INTEGER,
  clipped_video_path TEXT,
  manus_id TEXT,
  source_upload_id TEXT,
  source_window_id TEXT,
  media_url TEXT,
  dedup_variant TEXT,
  clip_options TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS publish_plan (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  round_id INTEGER,
  video_asset_id INTEGER,
  account_id TEXT,
  agent_id TEXT,
  team_id TEXT,
  serial_id TEXT,
  platform TEXT,
  promotion_link TEXT,
  promotion_code TEXT,
  caption TEXT,
  scheduled_at TIMESTAMP,
  status TEXT DEFAULT 'pending',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS publish_record (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  publish_plan_id INTEGER,
  team_id TEXT,
  task_id TEXT,
  platform TEXT,
  platform_post_id TEXT,
  post_url TEXT,
  published_at TIMESTAMP,
  status TEXT DEFAULT 'live',
  raw_payload TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS metrics_snapshot (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  publish_record_id INTEGER,
  snapshot_day INTEGER,
  views INTEGER DEFAULT 0,
  likes INTEGER DEFAULT 0,
  comments INTEGER DEFAULT 0,
  shares INTEGER DEFAULT 0,
  revenue REAL DEFAULT 0,
  raw_payload TEXT,
  snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS learning_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  round_id INTEGER,
  event_type TEXT NOT NULL,
  serial_id TEXT,
  payload TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
