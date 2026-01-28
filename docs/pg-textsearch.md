# Optimize full text search with BM25

**Source:** https://www.tigerdata.com/docs/use-timescale/latest/extensions/pg-textsearch

## Overview

Postgres full-text search at scale consistently hits a wall where performance degrades catastrophically. Tiger Data's `pg_textsearch` brings modern BM25-based full-text search directly into Postgres, with a memtable architecture for efficient indexing and ranking.

`pg_textsearch` integrates seamlessly with SQL and provides better search quality and performance than the Postgres built-in full-text search. With Block-Max WAND optimization, `pg_textsearch` delivers up to **4x faster top-k queries** compared to native BM25 implementations. Advanced compression using delta encoding and bitpacking reduces index sizes by **41%** while improving query performance by 10-20% for shorter queries.

BM25 scores in `pg_textsearch` are returned as negative values, where lower (more negative) numbers indicate better matches.

### Key Features

- **Corpus-aware ranking**: BM25 uses inverse document frequency to weight rare terms higher
- **Term frequency saturation**: prevents documents with excessive term repetition from dominating results
- **Length normalization**: adjusts scores based on document length relative to corpus average
- **Relative ranking**: focuses on rank order rather than absolute score values

### Best Practices

- **Language configuration**: choose appropriate text search configurations for your data language
- **Hybrid search**: combine with pgvector or pgvectorscale for applications requiring both semantic and keyword search
- **Query optimization**: use score thresholds to filter low-relevance results
- **Index monitoring**: regularly check index usage and memory consumption

## Prerequisites

To follow the steps on this page:

- Create a target Tiger Cloud service with the Real-time analytics capability
- You need your connection details
- This procedure also works for self-hosted TimescaleDB

## Install pg_textsearch

To install this Postgres extension:

1. **Connect to your Tiger Cloud service**

   In Tiger Console open an SQL editor. You can also connect to your service using psql.

2. **Enable the extension on your Tiger Cloud service**

   For new services, simply enable the extension:

   ```sql
   CREATE EXTENSION pg_textsearch;
   ```

   For existing services, update your instance, then enable the extension. The extension may not be available until after your next scheduled maintenance window. To pick up the update immediately, manually pause and restart your service.

3. **Verify the installation**

   ```sql
   SELECT * FROM pg_extension WHERE extname = 'pg_textsearch';
   ```

## Create BM25 indexes on your data

BM25 indexes provide modern relevance ranking that outperforms Postgres's built-in ts_rank functions by using corpus statistics and better algorithmic design.

To create a BM25 index with pg_textsearch:

1. **Create a table with text content**

   ```sql
   CREATE TABLE products (
       id serial PRIMARY KEY,
       name text,
       description text,
       category text,
       price numeric
   );
   ```

2. **Insert sample data**

   ```sql
   INSERT INTO products (name, description, category, price) VALUES
   ('Mechanical Keyboard', 'Durable mechanical switches with RGB backlighting for gaming and productivity', 'Electronics', 149.99),
   ('Ergonomic Mouse', 'Wireless mouse with ergonomic design to reduce wrist strain during long work sessions', 'Electronics', 79.99),
   ('Standing Desk', 'Adjustable height desk for better posture and productivity throughout the workday', 'Furniture', 599.99);
   ```

3. **Create a BM25 index**

   ```sql
   CREATE INDEX products_search_idx ON products
   USING bm25(description)
   WITH (text_config='english');
   ```

   BM25 supports single-column indexes only. For optimal performance, load your data first, then create the index.

## Optimize search queries for performance

Use efficient query patterns to leverage BM25 ranking and optimize search performance. The `<@>` operator provides BM25-based ranking scores as negative values, where lower (more negative) scores indicate better matches.

### Perform ranked searches using the distance operator

```sql
-- Simplified syntax: index is automatically detected in ORDER BY
SELECT name, description, description <@> 'ergonomic work' as score
FROM products
ORDER BY score
LIMIT 3;

-- Alternative explicit syntax (works in all contexts)
SELECT name, description, description <@> to_bm25query('ergonomic work', 'products_search_idx') as score
FROM products
ORDER BY score
LIMIT 3;
```

### Filter results by score threshold

For filtering with WHERE clauses, use explicit index specification with `to_bm25query()`:

```sql
SELECT name, description <@> to_bm25query('wireless', 'products_search_idx') as score
FROM products
WHERE description <@> to_bm25query('wireless', 'products_search_idx') < -0.5;
```

### Combine with standard SQL operations

```sql
SELECT category, name, description <@> to_bm25query('ergonomic', 'products_search_idx') as score
FROM products
WHERE price < 500
  AND description <@> to_bm25query('ergonomic', 'products_search_idx') < -0.5
ORDER BY score
LIMIT 5;
```

### Verify index usage with EXPLAIN

```sql
EXPLAIN SELECT * FROM products
ORDER BY description <@> to_bm25query('ergonomic', 'products_search_idx')
LIMIT 5;
```

## Build hybrid search with semantic and keyword search

Combine `pg_textsearch` with `pgvector` or `pgvectorscale` to build powerful hybrid search systems that use both semantic vector search and keyword BM25 search.

1. **Enable the vectorscale extension**

   ```sql
   CREATE EXTENSION IF NOT EXISTS vectorscale CASCADE;
   ```

2. **Create a table with both text content and vector embeddings**

   ```sql
   CREATE TABLE articles (
       id serial PRIMARY KEY,
       title text,
       content text,
       embedding vector(3)  -- Using 3 dimensions for this example; use 1536 for OpenAI ada-002
   );
   ```

3. **Create indexes for both search types**

   ```sql
   -- Vector index for semantic search
   CREATE INDEX articles_embedding_idx ON articles
   USING hnsw (embedding vector_cosine_ops);

   -- Keyword index for BM25 search
   CREATE INDEX articles_content_idx ON articles
   USING bm25(content)
   WITH (text_config='english');
   ```

4. **Perform hybrid search using reciprocal rank fusion**

   ```sql
   WITH vector_search AS (
     SELECT id,
            ROW_NUMBER() OVER (ORDER BY embedding <=> '[0.1, 0.2, 0.3]'::vector) AS rank
     FROM articles
     ORDER BY embedding <=> '[0.1, 0.2, 0.3]'::vector
     LIMIT 20
   ),
   keyword_search AS (
     SELECT id,
            ROW_NUMBER() OVER (ORDER BY content <@> to_bm25query('query performance', 'articles_content_idx')) AS rank
     FROM articles
     ORDER BY content <@> to_bm25query('query performance', 'articles_content_idx')
     LIMIT 20
   )
   SELECT a.id,
          a.title,
          COALESCE(1.0 / (60 + v.rank), 0.0) + COALESCE(1.0 / (60 + k.rank), 0.0) AS combined_score
   FROM articles a
   LEFT JOIN vector_search v ON a.id = v.id
   LEFT JOIN keyword_search k ON a.id = k.id
   WHERE v.id IS NOT NULL OR k.id IS NOT NULL
   ORDER BY combined_score DESC
   LIMIT 10;
   ```

## Configuration options

Customize `pg_textsearch` behavior for your specific use case and data characteristics.

### Configure memory and performance settings

To manage memory usage, you control when the in-memory index spills to disk segments. When the memtable reaches the threshold, it automatically flushes to a segment at transaction commit.

```sql
-- Set memtable spill threshold (default 32000000 posting entries, ~1M docs/segment)
SET pg_textsearch.memtable_spill_threshold = 32000000;

-- Set bulk load spill threshold (default 100000 terms per transaction)
SET pg_textsearch.bulk_load_threshold = 150000;

-- Set default query limit when no LIMIT clause is present (default 1000)
SET pg_textsearch.default_limit = 5000;

-- Enable Block-Max WAND optimization for faster top-k queries (enabled by default)
SET pg_textsearch.enable_bmw = true;

-- Log block skip statistics for debugging query performance (disabled by default)
SET pg_textsearch.log_bmw_stats = false;

-- Enable segment compression using delta encoding and bitpacking (enabled by default)
-- Reduces index size by ~41% with 10-20% query performance improvement for shorter queries
SET pg_textsearch.compress_segments = on;
```

### Configure language-specific text processing

You can create multiple BM25 indexes on the same column with different language configurations:

```sql
-- Create an additional index with simple tokenization (no stemming)
CREATE INDEX products_simple_idx ON products
USING bm25(description)
WITH (text_config='simple');

-- Example: French language configuration for a French products table
-- CREATE INDEX products_fr_idx ON products_fr
-- USING bm25(description)
-- WITH (text_config='french');
```

### Tune BM25 parameters

```sql
-- Adjust term frequency saturation (k1) and length normalization (b)
CREATE INDEX products_custom_idx ON products
USING bm25(description)
WITH (text_config='english', k1=1.5, b=0.8);
```

### Monitor index usage and memory consumption

```sql
-- Check index usage statistics
SELECT schemaname, relname, indexrelname, idx_scan, idx_tup_read
FROM pg_stat_user_indexes
WHERE indexrelid::regclass::text ~ 'bm25';

-- View index summary with corpus statistics and memory usage
SELECT bm25_summarize_index('products_search_idx');

-- View detailed index structure
SELECT bm25_dump_index('products_search_idx');

-- Export full index dump to a file for detailed analysis
SELECT bm25_dump_index('products_search_idx', '/tmp/index_dump.txt');

-- Force memtable spill to disk (useful for testing or memory management)
SELECT bm25_spill_index('products_search_idx');
```

## Current limitations

This preview release focuses on core BM25 functionality. In this release, you cannot search for exact multi-word phrases.
