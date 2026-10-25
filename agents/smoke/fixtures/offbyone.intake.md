A small items API. Items are held in memory (no database). GET /api/items lists them, behind the flag items-list.
Add pagination to GET /api/items: `limit` (default 10) is the most items a page returns, and `page` (default 0) is the zero-based page number.
