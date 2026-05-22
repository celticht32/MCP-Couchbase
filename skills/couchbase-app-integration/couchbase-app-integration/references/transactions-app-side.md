# Transactions — application side

Couchbase Distributed ACID Transactions provide atomicity across multiple documents. They're a separate library shipped alongside the SDK, with its own programming model. This reference covers when to use them, the patterns, and the gotchas.

## When transactions are the right answer

Couchbase has three concurrency tools, in increasing order of cost and capability:

| Tool | Scope | Use when |
|---|---|---|
| Single-document KV write | One document | Atomic update of a single doc; most operations |
| Subdocument ops (`mutate_in`) | One document, multiple fields | Atomic update of multiple fields of one doc |
| Distributed Transactions | Multiple documents | Atomicity required across docs |

Reach for transactions only when atomicity genuinely matters across documents — typically:
- Financial transfers (debit one account, credit another)
- Multi-step workflows where partial completion is a bug
- Document references that must stay consistent (create parent + first child)
- Inventory adjustments tied to order placement

Don't reach for transactions when:
- A single doc's worth of state would suffice (use subdoc instead)
- Eventual consistency is OK (use independent writes + reconciliation)
- The "transaction" is really a workflow with retry logic baked in (often simpler)

Transactions are 3-5x slower than equivalent KV ops. The cost is real.

## How they work, briefly

Couchbase transactions use a two-phase commit protocol:

1. **Begin** — transaction context created
2. **Operations phase** — reads and writes recorded but not visible to others
3. **Commit** — writes become visible atomically across all affected documents
4. **OR Rollback** — if commit fails or app calls rollback, all changes discarded

The mechanism uses Active Transaction Records (ATRs) — special docs that track in-flight transactions, allowing recovery if a client crashes mid-transaction.

## Code pattern — Python

```python
from couchbase.transactions import TransactionResult, TransactionOptions

def transfer_funds(cluster, from_account_id, to_account_id, amount):
    def transaction_logic(ctx):
        from_doc = ctx.get(accounts_coll, f"account::{from_account_id}")
        to_doc = ctx.get(accounts_coll, f"account::{to_account_id}")

        from_content = from_doc.content_as[dict]
        to_content = to_doc.content_as[dict]

        if from_content["balance"] < amount:
            raise InsufficientFundsException()

        from_content["balance"] -= amount
        to_content["balance"] += amount

        ctx.replace(from_doc, from_content)
        ctx.replace(to_doc, to_content)

    result = cluster.transactions.run(transaction_logic)
    return result.transaction_id
```

The `transaction_logic` callable runs inside the transaction context. The SDK handles begin, commit, rollback, and retry on conflict.

## Code pattern — Java

```java
TransactionResult result = cluster.transactions().run(ctx -> {
    TransactionGetResult fromDoc = ctx.get(accountsCollection, "account::" + fromId);
    TransactionGetResult toDoc = ctx.get(accountsCollection, "account::" + toId);

    JsonObject from = fromDoc.contentAsObject();
    JsonObject to = toDoc.contentAsObject();

    if (from.getDouble("balance") < amount) {
        throw new InsufficientFundsException();
    }

    from.put("balance", from.getDouble("balance") - amount);
    to.put("balance", to.getDouble("balance") + amount);

    ctx.replace(fromDoc, from);
    ctx.replace(toDoc, to);
});
```

Same pattern. The transactions library is built into the SDK in recent versions.

## Operations supported inside transactions

- `ctx.get(collection, id)` — read with locking
- `ctx.insert(collection, id, content)` — create new doc
- `ctx.replace(doc, content)` — update existing
- `ctx.remove(doc)` — delete
- `ctx.query(statement, options)` — N1QL inside the transaction (joins, multi-doc updates)

Not supported inside transactions:
- KV operations directly on the collection (`collection.upsert(...)`) — only via `ctx.*`
- Most admin operations
- Subdocument operations (`mutate_in`) — use `ctx.replace` with the full content

## Retry behavior

Transactions automatically retry on conflict (two transactions touching the same docs). The library uses backoff to avoid livelock.

**Implication:** your transaction logic may run multiple times. Make it idempotent — don't have side effects (logging, calling external services, modifying app state) inside the lambda that you wouldn't want to happen multiple times.

```python
# BAD — sends email N times on retry
def transaction_logic(ctx):
    doc = ctx.get(coll, "order::42")
    ctx.replace(doc, modified)
    send_confirmation_email(...)  # ← side effect inside lambda

# GOOD — side effect after commit
def transaction_logic(ctx):
    doc = ctx.get(coll, "order::42")
    ctx.replace(doc, modified)

result = cluster.transactions.run(transaction_logic)
if result.committed:
    send_confirmation_email(...)
```

## Failure modes

**Transaction commit succeeded:** `result.committed == True`. All changes are visible.

**Transaction commit failed:** the library raises `TransactionFailedException` (or language equivalent). All changes are rolled back. Your code decides what to do — retry the whole transaction, fail the request, etc.

**Application code threw exception inside transaction:** rolled back. Exception propagates to your caller.

**Client crashed mid-transaction:** the transaction is marked as in-flight in the ATR. Other clients reading the affected docs see the pre-transaction state. The transaction times out and is cleaned up by the next client to encounter it.

**Cluster lost replicas mid-transaction:** the library handles this; transaction may take longer but typically completes.

## Durability inside transactions

Transactions can request a durability level for their commits:

```python
options = TransactionOptions(
    durability_level=DurabilityLevel.MAJORITY
)
cluster.transactions.run(transaction_logic, options)
```

Higher durability = slower commits. `Majority` is the default and right for most cases. For financial workloads, `PERSIST_TO_MAJORITY` is appropriate.

## Performance characteristics

- Single-doc KV upsert: ~1-5ms
- Two-doc transaction (read + write 2 docs): ~10-30ms
- Five-doc transaction: ~30-80ms
- N1QL transaction (with index scans): adds query latency on top

The overhead is in the two-phase commit protocol (ATR writes, lock acquisition, commit phase). It's fixed-per-transaction, not per-doc.

**Practical implication:** prefer batching multi-doc work into one transaction over many small transactions. One transaction of 10 docs is faster than 10 transactions of 1 doc.

## Anti-patterns

- **Using transactions for single-doc operations** — overhead with no benefit. Use direct KV.
- **Side effects inside the transaction lambda** — runs multiple times on retry
- **Long-running transactions** — hold locks. Aim for sub-100ms total runtime
- **Reading many docs that don't need modification** — pulls them into the transaction's lock scope. Read outside, modify inside
- **Transactions across very many docs (>100)** — performance and reliability both suffer. Split into smaller transactions if possible

## When NOT to use transactions

Two patterns where transactions look tempting but aren't the best answer:

### Pattern 1: idempotent workflow

```
1. Reserve inventory
2. Charge card
3. Create order document
4. Send confirmation
```

This LOOKS like it needs a transaction. But it's actually better modeled as an idempotent state machine:

- Each step writes a state doc indicating progress
- On retry / failure, the next attempt picks up where the last left off
- Reservations and charges are themselves idempotent (use idempotency keys)
- No multi-doc atomicity needed; just resumability

Workflow engines (Temporal, Step Functions, custom) often suit this better than transactions.

### Pattern 2: eventually-consistent aggregation

```
Order created → user's "total_orders" counter should go up
```

Don't do this in a transaction. Two patterns work better:
- Eventing function reacts to order creation, updates user counter (eventually consistent)
- Compute the counter on read via N1QL aggregation (always consistent, slower reads)
- Materialized counter doc updated by a background job (eventually consistent, fast reads)

A transaction here would force the order-creation path to also update the user doc, coupling the two writes and slowing the hot path.

## Quick decision tree

- **Single doc atomic update?** → KV upsert / replace, no transaction
- **Multiple fields of one doc?** → `mutate_in`, no transaction
- **Multi-doc atomicity required?** → Transaction
- **Multi-doc but eventual consistency OK?** → Independent writes, reconcile if needed
- **Workflow with steps + idempotency?** → State machine pattern, not transaction
- **Cross-service atomicity (Couchbase + Stripe + email)?** → Saga pattern, not transaction
- **Inside a transaction, want a side effect?** → Defer it until after commit
