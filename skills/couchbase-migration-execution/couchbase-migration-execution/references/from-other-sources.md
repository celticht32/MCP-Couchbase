# Migrating from other sources

**Contents:** [From DynamoDB](#from-dynamodb) · [From Cassandra](#from-cassandra) · [From files (CSV/JSON/Parquet)](#from-files-csv-json-parquet) · [From custom application exports](#from-custom-application-exports) · [From data warehouses](#from-data-warehouses) · [Cross-cutting patterns](#cross-cutting-patterns) · [Quick decision tree](#quick-decision-tree)

DynamoDB, Cassandra, flat files, and custom-format sources. Each has its own quirks, but the migration pattern is similar: export → optionally transform → bulk load → validate.

## From DynamoDB

DynamoDB is conceptually similar to Couchbase: key-value with secondary indexes, JSON-like document content. The migration is mostly mechanical.

### Concept mapping

| DynamoDB | Couchbase | Notes |
|---|---|---|
| Table | Collection | DynamoDB tables → Couchbase collections |
| Partition Key | Document key (with namespace prefix) | Recommend prefixing: `<table>::<pk>` |
| Sort Key | Part of the document key OR a field | Composite key: `<table>::<pk>::<sk>` |
| Item | Document | JSON-shaped |
| Global Secondary Index (GSI) | GSI in Couchbase | Same concept, different syntax |
| Local Secondary Index (LSI) | GSI in Couchbase | Couchbase doesn't have separate local/global; all GSI |
| Streams | Eventing functions | Server-side reactions |
| Time-to-Live (TTL) | Per-doc TTL | Pass `expiry` argument on writes |

### Export options

**AWS Data Pipeline (DynamoDB → S3):**

Use the built-in DynamoDB-to-S3 pipeline template. Exports JSON to S3 (one item per line, DynamoDB's marshalled JSON format).

**AWS Glue:**

Glue can read DynamoDB and write to many targets. Use a Glue job to read DynamoDB, transform with Python or Scala, and write to Couchbase (via the Couchbase Spark connector, or write to S3 then bulk load).

**Custom code via SDK:**

```python
import boto3
import json

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('my_table')

# Scan paginates automatically when using LastEvaluatedKey
last_key = None
with open('items.jsonl', 'w') as out:
    while True:
        kwargs = {'Limit': 100}
        if last_key:
            kwargs['ExclusiveStartKey'] = last_key
        response = table.scan(**kwargs)
        for item in response['Items']:
            out.write(json.dumps(item, default=str) + '\n')
        last_key = response.get('LastEvaluatedKey')
        if not last_key:
            break
```

Then transform and cbimport.

**DynamoDB Streams + Lambda (for ongoing sync):**

For zero-downtime migrations, set up a Lambda function triggered by DynamoDB Streams. Each change (insert/update/delete) invokes the Lambda, which transforms and writes to Couchbase via the SDK.

### DynamoDB marshalled JSON quirk

DynamoDB's export format wraps values with type tags:

```json
{
  "id": {"S": "user_42"},
  "age": {"N": "30"},
  "tags": {"SS": ["premium", "early-adopter"]}
}
```

Couchbase wants the underlying values:

```json
{
  "id": "user_42",
  "age": 30,
  "tags": ["premium", "early-adopter"]
}
```

The transform step needs to unwrap the type tags. The `boto3` library does this automatically when scanning; raw S3 exports do not.

### Migration timeline (DynamoDB → Couchbase)

| Phase | Duration | Activities |
|---|---|---|
| Planning + sizing | 1 week | Confirm key strategy, decide on Streams or one-shot |
| Tooling setup | 3-5 days | Pick: AWS Glue, custom script, or Streams + Lambda |
| Dry run | 1 week | Migrate a sample, validate |
| Full migration | Days to weeks | Depending on data size |
| Validation | 1 week | Count + sample comparison |
| Cutover | 1 day | App config switch |

Generally cleaner than relational migrations because the shape doesn't change much.

## From Cassandra

Cassandra is column-family / wide-column. The migration shape is wider than DynamoDB but still mostly shape-preserving.

### Concept mapping

| Cassandra | Couchbase | Notes |
|---|---|---|
| Keyspace | Bucket | Roughly |
| Column family / table | Collection | Each Cassandra table → a collection |
| Partition key | Part of document key | Often + clustering key for composite |
| Clustering key | Sometimes the rest of the key, sometimes a field | Depends on access pattern |
| Wide row | Embedded array in one document | OR multiple documents with composite keys |

### Wide-row consolidation

The most consequential modeling decision: a Cassandra wide row (one partition key, many clustering keys, many rows) becomes either:

**Option A: One Couchbase document per Cassandra row** (preserves wide row in flat collection):

```
sensor_data::sensor_42::2026-05-21T14:00  { value: 0.71 }
sensor_data::sensor_42::2026-05-21T14:01  { value: 0.73 }
sensor_data::sensor_42::2026-05-21T14:02  { value: 0.69 }
```

Easy to query individual rows. Many small documents.

**Option B: Document per partition with embedded array:**

```
sensor_data::sensor_42 {
  readings: [
    { ts: "2026-05-21T14:00", value: 0.71 },
    { ts: "2026-05-21T14:01", value: 0.73 },
    ...
  ]
}
```

Fewer documents. Single read returns the partition. But appending requires read-modify-write on the parent (or `cb_mutate_in` array_append).

Pick based on workload: append-only with time-series-style reads → option B with bucketing (see `couchbase-data-modeling`'s `time-series-and-ttl.md`). Random row access → option A.

### Export options

**DSBulk (DataStax Bulk Loader):**

```bash
dsbulk unload \
    -k mykeyspace \
    -t mytable \
    -url /tmp/cassandra_export \
    -h cassandra-host \
    -u username -p password
```

Exports to CSV by default. JSON unload is also supported.

**`cqlsh` COPY:**

```cql
COPY mykeyspace.mytable TO '/tmp/data.csv' WITH HEADER = true;
```

Simpler but slower for large tables.

**Spark Cassandra Connector + Couchbase Spark Connector:**

For TB-scale migrations, use Spark to read Cassandra and write Couchbase in one pipeline. Best performance and built-in retry/parallelism.

### CDC from Cassandra

Cassandra CDC is more complex than other sources. Options:
- **Debezium Cassandra connector** — experimental for some Cassandra versions
- **Triggers + Kafka** — write a Cassandra trigger that emits to Kafka, sink to Couchbase
- **Manual polling** — for low-volume change capture

For zero-downtime Cassandra migrations, often easier to dual-write at the application level than to set up CDC.

## From files (CSV, JSON, Parquet)

The simplest case. Files are a snapshot of data; load them as-is.

### CSV / JSON Lines

```bash
# JSON lines
cbimport json \
    --cluster ... --bucket app_data \
    --format lines \
    --dataset file://users.jsonl \
    --generate-key "user::%id%" \
    --threads 8

# CSV
cbimport csv \
    --cluster ... --bucket app_data \
    --dataset file://users.csv \
    --generate-key "user::%id%" \
    --threads 8
```

### Parquet

`cbimport` doesn't read Parquet directly. Convert to JSON or CSV first:

```bash
# Convert Parquet to JSON Lines using python-pandas
python3 -c "
import pandas as pd
df = pd.read_parquet('users.parquet')
df.to_json('users.jsonl', orient='records', lines=True)
"
```

Or use Spark with the Couchbase Spark Connector to read Parquet and write directly.

### Splitting large files

`cbimport` is single-process. For TB-scale files, split and parallelize:

```bash
split -l 1000000 huge.jsonl part_

# Run 8 parallel cbimports
for i in part_*; do
    cbimport json --dataset file://$PWD/$i --format lines ... &
done
wait
```

### Schema variance in files

Files exported from heterogeneous sources may have inconsistent schemas. Run a quick audit:

```bash
# Show field-frequency across the file
jq -r 'keys[]' users.jsonl | sort | uniq -c | sort -n
```

Decide on the canonical schema; transform before loading.

## From custom application exports

When the source is "whatever shape your app dumped" — log files, application-specific exports, data lake extracts.

The pattern is the same:
1. **Parse the source format** — your code
2. **Transform to Couchbase JSON** — your code
3. **Load** — cbimport or SDK `upsert_multi`

The custom case is usually:
- The source has weird format (proprietary binary, fixed-width text, XML, etc.)
- Or the transformation is so specific to your domain that no off-the-shelf tool fits

For these, a custom script + the Couchbase SDK is the right answer. See `couchbase-app-integration` skill's `performance-patterns.md` for bulk-write patterns.

## From data warehouses

For migrations OUT of a warehouse (Snowflake, BigQuery, Redshift) into Couchbase:

**Pattern 1 — Warehouse-to-S3/GCS, then cbimport:**

Most warehouses have efficient UNLOAD to object storage. Export, then pull files locally or use a connector to load into Couchbase.

**Pattern 2 — Spark migration:**

If your warehouse has a Spark connector, use Spark to read warehouse + write Couchbase. Snowflake/BigQuery/Redshift all have Spark integrations.

**Pattern 3 — Custom ETL service:**

Schedule a job that reads from the warehouse (via JDBC), transforms, writes to Couchbase. Best for ongoing pipelines.

For one-shot migrations, Pattern 1 is usually right. For ongoing data flow (warehouse → Couchbase for serving), Pattern 3 is the long-term answer.

## Cross-cutting patterns

### Handling binary data

DynamoDB, MongoDB, and others sometimes store binary blobs (images, files). Couchbase isn't designed for large binaries.

Migration approach:
1. Extract blobs to object storage (S3, GCS, Azure Blob)
2. Replace the blob in the document with a reference (URL or object key)
3. Application code reads metadata from Couchbase, fetches blob from object storage

### Handling very wide documents

If documents are > 1 MB during migration (some Cassandra wide rows, some MongoDB super-docs), see `couchbase-data-modeling`'s `document-shape.md` — split before loading.

### Preserving timestamps

Source databases use various timestamp formats. Standardize during migration:

| Source format | Convert to |
|---|---|
| MongoDB ISODate | ISO 8601 string |
| Postgres TIMESTAMP | ISO 8601 string |
| DynamoDB Number (epoch) | ISO 8601 string |
| Cassandra Timestamp | ISO 8601 string |
| Custom proprietary | Decide and document |

Couchbase has no native date type; store as ISO 8601 strings (sortable, parseable). Use `STR_TO_MILLIS()` and `MILLIS_TO_STR()` in N1QL for math.

### Preserving identity for traceability

For audit / compliance / debugging, preserve the original source identifier in the document:

```json
{
  "id": "user::42",
  "name": "Alice",
  "_migration": {
    "source": "postgres.users",
    "source_id": 42,
    "migrated_at": "2026-05-21T14:00:00Z"
  }
}
```

This costs a small amount of storage but is invaluable when something goes wrong: you can always trace a document back to its source.

## Quick decision tree

- **DynamoDB → Couchbase, one-shot?** → Data Pipeline OR custom boto3 script → transform → cbimport
- **DynamoDB → Couchbase, zero-downtime?** → DynamoDB Streams → Lambda → Couchbase SDK
- **Cassandra → Couchbase?** → DSBulk export OR Spark-based migration; decide wide-row strategy
- **Files (CSV, JSON)?** → cbimport directly; split large files for parallelism
- **Parquet?** → Convert to JSON via pandas/Spark, then cbimport. OR Spark Connector.
- **Data warehouse?** → UNLOAD to object storage, then load; or use Spark
- **Has binary blobs?** → Move blobs to object storage, store references in Couchbase
- **Migration timestamps?** → Standardize on ISO 8601 strings
- **Custom format?** → Custom script + Couchbase SDK; refer to `couchbase-app-integration`
