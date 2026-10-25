# Backups & Durability

The journal is one SQLite file (plus an attachments directory). Three layers:

1. **Continuous replication — Litestream** (recommended)
   ```bash
   # install: https://litestream.io/install/
   litestream replicate journal.db s3://YOUR-BUCKET/completejournal
   # restore drill (do this quarterly):
   litestream restore -o restored.db s3://YOUR-BUCKET/completejournal
   ```
   Works with S3, Backblaze B2, SFTP, or a local/NAS path.

2. **Human-readable mirror — markdown export** (git-able, Obsidian-compatible)
   ```bash
   python -m completejournal export --db journal.db --out export/
   (cd export/markdown && git init 2>/dev/null; git add -A && git commit -m "mirror $(date +%F)")
   ```

3. **Attachments**: rsync/restic the `journal.db.attachments/` directory.
   Files are content-addressed (sha256), so copies are idempotent and
   integrity is verifiable on read.

Writing must never depend on a network: the DB is local; export and
replication are projections. Restore drills matter more than backup tools —
schedule one per quarter (roadmap Phase 5).
