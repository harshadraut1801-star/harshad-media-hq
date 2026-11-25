-- 0002_librarian: fields the Media Librarian needs.
ALTER TABLE media ADD COLUMN mtime_ns INTEGER;
ALTER TABLE media ADD COLUMN vfr INTEGER NOT NULL DEFAULT 0;          -- variable frame rate
ALTER TABLE media ADD COLUMN motion_photo INTEGER NOT NULL DEFAULT 0; -- JPEG with embedded video
ALTER TABLE media ADD COLUMN camera_model TEXT;
ALTER TABLE media ADD COLUMN duplicate_of INTEGER REFERENCES media(id);
ALTER TABLE media ADD COLUMN thumb_path TEXT;                         -- relative to project root
ALTER TABLE media ADD COLUMN proxy_path TEXT;
ALTER TABLE media ADD COLUMN notes TEXT;                              -- JSON array of flags
CREATE INDEX idx_media_day ON media(series, day_folder);
