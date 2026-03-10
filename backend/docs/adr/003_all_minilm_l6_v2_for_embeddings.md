# ADR-003: all-MiniLM-L6-v2 for incident embedding

## Status
Accepted

## Context

AIRRA embeds every incident as a dense vector to enable semantic similarity retrieval. The embedding model must satisfy several constraints:

1. **Cost** — embedding happens on every incident creation, every analysis task, and on resolution (re-embed with root cause). With 48+ AI-generated incidents per day, a paid API would accumulate non-trivial cost.
2. **Latency** — embedding runs in a Celery worker on CPU. The model must run inference in <100ms per incident on commodity hardware.
3. **Memory** — workers run in containers with shared memory budgets. A model requiring a GPU or >1GB RAM per worker replica is impractical.
4. **Quality** — the model must capture semantic similarity between incident descriptions well enough that "payment service database connection pool exhausted" retrieves "order service postgres max_connections reached" as a similar incident.

## Decision

Use **`sentence-transformers/all-MiniLM-L6-v2`** loaded via the `sentence-transformers` library.

Key properties:
- **384 dimensions** — compact vector; fits well within pgvector's practical limits
- **80MB model** — loads once per worker process via a lazy singleton with a thread lock
- **CPU-only inference** — ~20ms per incident after model warmup (~2–4s on first call per worker)
- **MIT licence** — no usage restrictions
- **Strong STS benchmarks** — top-performing model in its size class on the Sentence Transformers SBERT benchmarks

The model is loaded lazily on first use and cached as a module-level singleton:

```python
_model: SentenceTransformer | None = None
_model_lock = threading.Lock()

def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model
```

The double-checked locking pattern prevents multiple threads from loading the model simultaneously on first access.

## Consequences

**Benefits:**
- Zero per-call cost (model runs locally)
- Consistent latency (~20ms) after warmup
- No external API dependency for the retrieval path

**Known limitations:**
- Less accurate than `text-embedding-3-large` (OpenAI) or `voyage-large-2` on long-form text. For short, structured incident summaries the quality gap is acceptable.
- Cold start: the first embedding request per worker process takes 2–4s. In production, trigger a warm-up embed at worker startup.
- 384 dimensions may under-represent incidents with complex, multi-signal context. A future migration to a 768-dim model would require re-embedding all historical incidents and an Alembic column-type migration.

## Alternatives considered

**OpenAI `text-embedding-3-small`** (1536-dim): higher quality, $0.02/1M tokens. Adds API latency and external dependency to the retrieval path. Acceptable cost at low volume; would require a separate API budget.

**`all-mpnet-base-v2`** (768-dim, 420MB): better quality than MiniLM but 5× larger and ~60ms inference. Marginal quality gain does not justify the resource cost at this scale.

**`nomic-embed-text`** (768-dim): strong benchmarks, requires accepting Nomic's terms. Adds a licence constraint without clear quality advantage over MiniLM for short incident text.
