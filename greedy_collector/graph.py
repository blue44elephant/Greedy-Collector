import logging

import httpx

from .config import get_settings
from .chains import get_chain_adapter
from .schemas import NormalizedTransaction

logger = logging.getLogger("GreedyCollector.Graph")


class GraphStore:
    """SQLite is canonical; Neo4j is an optional query-optimized mirror."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.backend = (
            "neo4j"
            if self.settings.graph_backend == "neo4j"
            and self.settings.neo4j_url
            else "sqlite"
        )
        if self.settings.graph_backend == "neo4j" and not self.settings.neo4j_url:
            logger.warning(
                "Neo4j graph backend requested without GREEDY_COLLECTOR_NEO4J_URL; "
                "using SQLite"
            )

    def status(self) -> dict:
        return {
            "requested": self.settings.graph_backend,
            "active": self.backend,
            "configured": self.backend == "sqlite"
            or bool(
                self.settings.neo4j_url
                and self.settings.neo4j_user
                and self.settings.neo4j_password
            ),
            "fallback": "sqlite",
        }

    def store_transactions(self, transactions: list[NormalizedTransaction]) -> None:
        if self.backend != "neo4j" or not transactions:
            return
        from .transaction_identity import build_event_key
        rows = []
        for tx in transactions:
            if not tx.from_address or not tx.to_address:
                continue
            rows.append(
                {
                    "edge_id": (
                        f"{tx.chain}:{tx.tx_hash}:{tx.from_address}:"
                        f"{tx.to_address}:{tx.token_symbol}:{tx.value_native}:"
                        f"{get_chain_adapter(tx.chain).transfer_identity(tx)}"
                    ),
                    "chain": tx.chain,
                    "tx_hash": tx.tx_hash,
                    "from_address": tx.from_address,
                    "from_normalized": get_chain_adapter(tx.chain).address_key(tx.from_address),
                    "to_address": tx.to_address,
                    "to_normalized": get_chain_adapter(tx.chain).address_key(tx.to_address),
                    "value_native": tx.value_native,
                    "token_symbol": tx.token_symbol,
                    "timestamp": tx.timestamp.isoformat() if tx.timestamp else None,
                    "block_number": tx.block_number,
                    "source_api": tx.source_api,
                    "event_key": tx.event_key or build_event_key(tx),
                    "event_index": tx.event_index,
                    "asset_contract": tx.asset_contract,
                }
            )
        statement = """
        UNWIND $rows AS row
        MERGE (source:Wallet {
            chain: row.chain,
            address_normalized: row.from_normalized
        })
        SET source.address = row.from_address
        MERGE (target:Wallet {
            chain: row.chain,
            address_normalized: row.to_normalized
        })
        SET target.address = row.to_address
        MERGE (source)-[tx:TRANSACTION {edge_id: row.edge_id}]->(target)
        SET tx += row
        """
        try:
            self._execute([{"statement": statement, "parameters": {"rows": rows}}])
        except Exception as exc:
            logger.warning("Neo4j mirror write failed; SQLite remains canonical: %s", exc)

    def query_graph(self, chain: str, address: str, hops: int) -> dict | None:
        if self.backend != "neo4j":
            return None
        hops = max(1, min(int(hops), 3))
        path = (
            "MATCH p=(focus:Wallet {chain: $chain, address_normalized: $address})"
            f"-[:TRANSACTION*1..{hops}]-(other) "
        )
        statements = [
            {
                "statement": (
                    path
                    + "UNWIND nodes(p) AS n "
                    "RETURN DISTINCT n.address AS id, "
                    "coalesce(n.label, n.address) AS label, "
                    "coalesce(n.type, 'Wallet') AS type, "
                    "n.chain AS chain"
                ),
                "parameters": {"chain": chain, "address": get_chain_adapter(chain).address_key(address)},
            },
            {
                "statement": (
                    path
                    + "UNWIND relationships(p) AS r "
                    "RETURN DISTINCT r.edge_id AS id, "
                    "r.from_address AS source, r.to_address AS target, "
                    "r.tx_hash AS tx_hash, r.value_native AS value_native, "
                    "r.token_symbol AS token_symbol, r.timestamp AS timestamp"
                ),
                "parameters": {"chain": chain, "address": get_chain_adapter(chain).address_key(address)},
            },
        ]
        try:
            results = self._execute(statements)
            nodes = [
                {
                    **dict(zip(results[0]["columns"], row["row"])),
                    "is_focus": get_chain_adapter(chain).address_key(row["row"][0]) == get_chain_adapter(chain).address_key(address),
                }
                for row in results[0]["data"]
            ]
            if not nodes:return None  # A missing/stale optional mirror falls back to canonical SQLite.
            edges = [
                dict(zip(results[1]["columns"], row["row"]))
                for row in results[1]["data"]
            ]
            return {
                "nodes": nodes,
                "edges": edges,
                "requested_hops": hops,
                "available_hops": hops if edges else 0,
                "backend": "neo4j",
                "note": "Graph paths were queried from the optional Neo4j mirror.",
            }
        except Exception as exc:
            logger.warning("Neo4j graph query failed; using SQLite fallback: %s", exc)
            return None

    def _execute(self, statements: list[dict]) -> list[dict]:
        endpoint = (
            self.settings.neo4j_url.rstrip("/")
            + "/db/neo4j/tx/commit"
        )
        response = httpx.post(
            endpoint,
            json={"statements": statements},
            auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            timeout=self.settings.request_timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(payload["errors"][0].get("message", "Neo4j query failed"))
        return payload.get("results", [])

    @staticmethod
    def response_graph(
        focus_address: str,
        transactions: list[NormalizedTransaction],
        labels: list[dict],
        max_hops: int = 1,
        available_hops: int = 1,
    ) -> dict:
        chain_ids={tx.chain for tx in transactions}
        label_map = {(chain,get_chain_adapter(chain).address_key(item['address'])):item
                     for chain in chain_ids for item in labels if item.get('chain',chain) in (chain,'any')}
        # Single-chain API IDs retain their historical address spelling. Mixed internal
        # graphs qualify IDs so identical text on different chains cannot collide.
        def node_id(chain,address):return address if len(chain_ids)<=1 else chain+':'+address
        nodes = {}
        edges = []
        from .transaction_identity import build_event_key
        for tx in transactions:
            for address in [tx.from_address, tx.to_address]:
                if not address:
                    continue
                key=(tx.chain,get_chain_adapter(tx.chain).address_key(address))
                label = label_map.get(key)
                nodes[key] = {
                    "id": node_id(tx.chain,address),
                    "label": label.get("label") if label else address,
                    "type": label.get("type") if label else "Wallet",
                    "chain": tx.chain,
                    "is_focus": get_chain_adapter(tx.chain).address_key(address) == get_chain_adapter(tx.chain).address_key(focus_address),
                }
            if tx.from_address and tx.to_address:
                edges.append(
                    {
                        "id": (
                            f"{tx.chain}:{tx.tx_hash}:{tx.from_address}:"
                            f"{tx.to_address}:{tx.token_symbol}:{tx.value_native}:"
                            f"{get_chain_adapter(tx.chain).transfer_identity(tx)}"
                        ),
                        "source": node_id(tx.chain,tx.from_address),
                        "target": node_id(tx.chain,tx.to_address),
                        "tx_hash": tx.tx_hash,
                        "value_native": tx.value_native,
                        "token_symbol": tx.token_symbol,
                        "event_key": tx.event_key or build_event_key(tx),
                        "event_index": tx.event_index,
                        "asset_contract": tx.asset_contract,
                        "timestamp": tx.timestamp.isoformat() if tx.timestamp else None,
                    }
                )
        return {
            "nodes": list(nodes.values()),
            "edges": edges,
            "requested_hops": max_hops,
            "available_hops": available_hops,
            "backend": "sqlite",
            "note": (
                "Graph paths use locally stored public transactions. Expanding a "
                "counterparty through lookup adds its edges for deeper traversal."
            ),
        }
