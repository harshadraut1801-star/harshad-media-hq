# n8n
Self-hosted n8n (free). n8n Cloud is a paid plan and needs Harsh's approval.
Role: schedules and glue only (nightly librarian scan, morning metrics pull, Telegram approval prompts). It calls the `hq` CLI; business rules stay in Python.
`workflows/` holds exported workflow JSON with **credentials stripped** before commit.
