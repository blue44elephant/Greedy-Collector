# Transaction event identity

MC-3A adds a stable event key to each normalized activity row. The database
uniqueness boundary is `(chain, tx_hash, event_key)`: a transaction hash still
identifies the chain transaction, while `event_key` distinguishes transfer
events within it. Existing transaction row IDs and references are preserved by
the migration.

| Activity | Event key |
| --- | --- |
| Native transaction | `tx` |
| EVM token log with a valid provider log index | `evm-log:<canonical decimal index>` |
| TRON provider event | `provider:<existing provider event ID>` |
| Bitcoin wallet-relative activity | `activity:<stable tuple digest>` |
| Token event without a protocol index | `legacy:<stable tuple and contract digest>` |

Event indexes are stored as canonical decimal strings. `asset_contract` is
stored separately when the provider supplies it, so transfers of similarly
named assets remain distinct. BTC's stable tuple key retains the previous
wallet-relative de-duplication behavior. TRON monitoring retains its existing
provider event identity; EVM monitoring now distinguishes logs in one
transaction. Graph edges retain event-level IDs and expose the event key,
index and contract where available.

Migration `20260923_02` adds and backfills these fields without changing the
provider retrieval logic or adding chain support. Downgrade is refused before
schema changes if distinct events would collide under the old transaction
uniqueness rule. A safe downgrade stores the event key metadata in the existing
raw payload so a later upgrade can restore it. Tests use isolated SQLite files;
the configured user database is not inspected or migrated.
