"""The assistant's law knowledge base: public UK tax and company law (HMRC manuals, VAT notices, legislation, gov.uk
guidance), shared by every firm. Pages are cut into pieces by their own structure (chunker), embedded (embed) and kept in Postgres with pgvector, searched by meaning and by exact words together (store)."""
