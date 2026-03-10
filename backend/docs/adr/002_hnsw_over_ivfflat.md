# ADR-002: HNSW index over IVFFlat for pgvector similarity search

## Status
Accepted

## Context

AIRRA stores incident embeddings as 384-dimensional vectors in PostgreSQL via the `pgvector` extension. Semantic retrieval (finding historically similar incidents to inform LLM reasoning) requires a vector index — without one, every search performs a full sequential scan.

pgvector supports two index types:
- **IVFFlat** — inverted file index; partitions the vector space into `lists` clusters and searches only a subset at query time
- **HNSW** — hierarchical navigable small world; builds a proximity graph that supports logarithmic-time approximate nearest-neighbour search

The choice matters for both build-time behaviour and query-time recall.

## Decision

Use **HNSW** with `vector_cosine_ops` (cosine distance metric).

```sql
CREATE INDEX ON incidents USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

## Consequences

**Why HNSW for AIRRA specifically:**

IVFFlat requires a training phase — the index partitions are computed from existing data. With fewer than ~1,000 incidents (the realistic scale during early operation) the centroids are poorly formed and recall degrades significantly. The pgvector documentation recommends a minimum of `lists × 30` rows before building the index; below that threshold IVFFlat performs worse than a sequential scan.

HNSW builds incrementally — each inserted vector is wired into the proximity graph immediately, with no training phase. Recall is consistently high regardless of dataset size, making it the correct choice for a system that starts with zero incidents and grows gradually.

**Trade-offs:**
- HNSW index build is slower and uses more memory than IVFFlat for very large datasets (millions of vectors). At AIRRA's scale (thousands of incidents) this is not a concern.
- HNSW `ef_construction` and `m` parameters trade index build time for query recall. The defaults (`m=16`, `ef_construction=64`) are appropriate for this scale.
- pgvector HNSW was added in version 0.5.0; the deployment requires `pgvector/pgvector:pg16` rather than the standard `postgres:16` image.

## Alternatives considered

**Sequential scan (no index)**: acceptable below ~500 rows. As the incident history grows, scan time grows linearly. Unsuitable for production.

**IVFFlat**: better memory profile at scale. Would be the correct choice if AIRRA were ingesting millions of incidents and had sufficient history to train centroids. A future migration could switch index types without changing the query layer.
