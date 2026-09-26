import csv
from datetime import datetime, timezone
from io import StringIO

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .chains import get_chain_adapter, get_chain, Capability
from .database import initialize_database
from .graph import GraphStore
from .kyc import KycScreeningEngine
from .models import (
    Address,
    AnalystNote,
    Case,
    CaseEntity,
    KycMatch,
    KycScreeningRun,
    Label,
    MonitoringRun,
    RiskResult,
    Transaction,
    WalletAlert,
    WatchlistWallet,
)
from .reporting import case_html, case_json, case_markdown, case_pdf
from .risk import ExplainableRiskEngine
from .risk.engine import SCORING_MODEL, contribution_summary
from .schemas import KycQuery, LookupRequest, NormalizedTransaction, ManualLabelCreate


def row_dict(row) -> dict:
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
    }


class GreedyCollectorService:
    def __init__(self):
        initialize_database()
        self.risk_engine = ExplainableRiskEngine()
        self.kyc_engine = KycScreeningEngine()
        self.graph_store = GraphStore()

    async def lookup_address(self, db: Session, request: LookupRequest) -> dict:
        get_chain(request.chain).require(Capability.BALANCE,Capability.TRANSACTION_HISTORY,Capability.RISK)
        adapter = get_chain_adapter(request.chain)
        profile = await adapter.lookup_address(request.address)
        transactions = await adapter.transactions(request.address)
        labels = self._labels_for_transactions(db, transactions)

        from .transaction_identity import persist_normalized_event
        for tx in transactions:
            persist_normalized_event(db, tx)
        db.flush()

        exposure_paths = self._exposure_paths(db, request.chain, request.address, 3)
        risk = self.risk_engine.evaluate(
            request.address, transactions, labels, exposure_paths,
            include_behavioral=adapter.behavioral_risk,
        )
        risk["behavioral_supported"] = adapter.behavioral_risk
        # Encode nested evidence once for both the JSON column and API response.
        risk["findings"] = jsonable_encoder(risk["findings"])

        address = db.scalar(
            select(Address).where(
                Address.chain == request.chain, self._address_membership(request.chain,Address.address,{adapter.address_key(request.address)})
            )
        )
        if address is None:
            address = Address(chain=request.chain, address=adapter.normalize_address(request.address))
            db.add(address)
        address.balance_native = profile.get("balance_native", "0")
        address.risk_score = risk["score"]
        address.risk_level = risk["level"]
        address.updated_at = datetime.now(timezone.utc)
        if transactions:
            dated = [tx.timestamp for tx in transactions if tx.timestamp]
            address.first_seen = min(dated) if dated else None
            address.last_activity = max(dated) if dated else None
        address.metadata_json = {
            "source_api": profile.get("source_api"),
            "transaction_count": profile.get("transaction_count", len(transactions)),
        }

        db.add(
            RiskResult(
                chain=request.chain,
                address=request.address,
                score=risk["score"],
                level=risk["level"],
                findings=risk["findings"],
            )
        )
        db.commit()
        self.graph_store.store_transactions(transactions)
        return {
            "address": row_dict(address),
            "transactions": [self._tx_dict(tx) for tx in transactions],
            "counterparties": self._counterparties(request.address, transactions),
            "labels": labels,
            "risk": risk,
            "provenance": {
                "source_api": profile.get("source_api"),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    async def lookup_transaction(self, chain: str, tx_hash: str) -> dict:
        get_chain(chain).require(Capability.TRANSACTION_LOOKUP)
        tx = await get_chain_adapter(chain).lookup_transaction(tx_hash)
        return self._tx_dict(tx)

    def address_record(self, db: Session, chain: str, address: str) -> dict | None:
        row = db.scalar(
            select(Address).where(Address.chain == chain, self._address_membership(chain,Address.address,{get_chain(chain).adapter().address_key(address)}))
        )
        return row_dict(row) if row else None

    def address_transactions(self, db: Session, chain: str, address: str) -> list[dict]:
        rows = db.scalars(
            select(Transaction)
            .where(
                Transaction.chain == chain,
                or_(
                    self._address_membership(chain,Transaction.from_address,{get_chain(chain).adapter().address_key(address)}),
                    self._address_membership(chain,Transaction.to_address,{get_chain(chain).adapter().address_key(address)}),
                ),
            )
            .order_by(Transaction.timestamp.desc())
        ).all()
        return [row_dict(row) for row in rows]

    def address_risk(self, db: Session, chain: str, address: str) -> dict | None:
        row = db.scalar(
            select(RiskResult)
            .where(RiskResult.chain == chain, self._address_membership(chain,RiskResult.address,{get_chain(chain).adapter().address_key(address)}))
            .order_by(RiskResult.calculated_at.desc())
        )
        if row is None:
            return None
        result = row_dict(row)
        # Historical scores stay unchanged. Only versioned saved findings can explain
        # the new category totals; never infer a new model for legacy/empty findings.
        if row.findings and all(item.get("scoring_model") == SCORING_MODEL for item in row.findings):
            result["scoring_model"] = SCORING_MODEL
            result["category_contributions"] = contribution_summary(row.findings)
        return result

    def address_graph(
        self, db: Session, chain: str, address: str, hops: int
    ) -> dict:
        get_chain(chain).require(Capability.GRAPH)
        adapter = get_chain(chain).adapter()
        external_graph = self.graph_store.query_graph(chain, address, hops)
        if external_graph:
            return external_graph
        frontier = {adapter.address_key(address)}
        visited = set()
        transactions_by_hash = {}
        available_hops = 0
        for _ in range(hops):
            if not frontier:
                break
            rows = db.scalars(
                select(Transaction).where(
                    Transaction.chain == chain,
                    or_(
                        self._address_membership(chain,Transaction.from_address,frontier),
                        self._address_membership(chain,Transaction.to_address,frontier),
                    ),
                )
            ).all()
            if not rows:
                break
            available_hops += 1
            next_frontier = set()
            for row in rows:
                transactions_by_hash[row.id] = row
                for candidate in [row.from_address, row.to_address]:
                    normalized = adapter.address_key(candidate) if candidate else ""
                    if normalized and normalized not in visited and normalized not in frontier:
                        next_frontier.add(normalized)
            visited.update(frontier)
            frontier = next_frontier
        transaction_fields = (
            NormalizedTransaction.model_fields
            if hasattr(NormalizedTransaction, "model_fields")
            else NormalizedTransaction.__fields__
        )
        transactions = [
            NormalizedTransaction(
                **{
                    key: value
                    for key, value in row_dict(row).items()
                    if key in transaction_fields
                }
            )
            for row in transactions_by_hash.values()
        ]
        labels = self._labels_for_transactions(db, transactions)
        return self.graph_store.response_graph(
            address, transactions, labels, hops, available_hops
        )

    def add_watchlist(self, db: Session, payload) -> dict:
        get_chain(payload.chain).require(Capability.MONITORING)
        payload.address = get_chain_adapter(payload.chain).normalize_address(payload.address)
        existing = db.scalar(
            select(WatchlistWallet).where(
                WatchlistWallet.chain == payload.chain,
                self._address_membership(payload.chain,WatchlistWallet.address,{payload.address}),
            )
        )
        if existing:
            return row_dict(existing)
        row = WatchlistWallet(**(payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()))
        db.add(row)
        db.commit()
        db.refresh(row)
        return row_dict(row)

    def watchlist(self, db: Session) -> list[dict]:
        rows = db.scalars(
            select(WatchlistWallet).order_by(WatchlistWallet.created_at.desc())
        ).all()
        output = []
        for row in rows:
            data = row_dict(row)
            address = db.scalar(
                select(Address).where(
                    Address.chain == row.chain, self._address_membership(row.chain,Address.address,{get_chain(row.chain).adapter().address_key(row.address)})
                )
            )
            data.update(
                {
                    "balance_native": address.balance_native if address else None,
                    "last_activity": address.last_activity if address else None,
                    "risk_score": address.risk_score if address else 0,
                    "last_monitoring_status": db.scalar(
                        select(MonitoringRun.status)
                        .where(MonitoringRun.wallet_id == row.id)
                        .order_by(MonitoringRun.started_at.desc())
                        .limit(1)
                    ),
                    "alert_count": db.scalar(
                        select(func.count(WalletAlert.id)).where(
                            WalletAlert.wallet == row.address,
                            WalletAlert.chain == row.chain,
                        )
                    )
                    or 0,
                }
            )
            output.append(data)
        return output

    def alerts(self, db: Session, status: str | None = None) -> list[dict]:
        query = select(WalletAlert)
        if status:
            query = query.where(WalletAlert.status == status)
        rows = db.scalars(query.order_by(WalletAlert.timestamp.desc())).all()
        return [row_dict(row) for row in rows]

    def dashboard(self, db: Session) -> dict:
        watchlist = self.watchlist(db)
        alerts = self.alerts(db)
        return {
            "statistics": {
                "total_watched_wallets": len(watchlist),
                "new_alerts": sum(item["status"] == "New" for item in alerts),
                "high_risk_wallets": sum(
                    int(item.get("risk_score") or 0) >= 71 for item in watchlist
                ),
                "recent_transactions": db.scalar(select(func.count(Transaction.id))) or 0,
            },
            "watchlist": watchlist,
            "alerts": alerts[:20],
        }

    async def kyc_screen(self, db: Session, query: KycQuery) -> dict:
        from .kyc.presentation import sanitize_research

        result = sanitize_research(await self.kyc_engine.screen(query))
        run = KycScreeningRun(
            query=result["query"],
            checked_sources=result["checked_sources"],
            unavailable_sources=result["unavailable_sources"],
            manual_sources=result["manual_sources"],
        )
        db.add(run)
        db.flush()
        stored_matches = []
        for item in result["matches"]:
            match = KycMatch(run_id=run.id, **item)
            db.add(match)
            db.flush()
            stored_matches.append(row_dict(match))
        db.commit()
        result.update({"run_id": run.id, "matches": stored_matches})
        return result

    def import_labels(self, db: Session, content: str) -> dict:
        reader = csv.DictReader(StringIO(content), strict=True)
        required = {"address", "label", "type", "source", "confidence"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(f"CSV requires columns: {', '.join(sorted(required))}")
        # Validate the entire file before staging database writes. CSV and manual
        # creation share one schema; a rejected file must not partially import rows.
        validated = []
        for item in reader:
            if None in item or any(item.get(key) is None for key in required):
                raise ValueError("CSV row has an incorrect number of columns")
            payload = {key: item[key] for key in required}
            payload["chain"] = item.get("chain") or "any"
            validated.append(ManualLabelCreate.model_validate(payload).model_dump())
        count = 0
        for item in validated:
            chain = item["chain"]
            existing = db.scalar(
                select(Label).where(
                    Label.chain == chain,
                    Label.address == item["address"],
                    Label.label == item["label"],
                    Label.source == item["source"],
                )
            )
            row = existing or Label(
                chain=chain,
                address=item["address"],
                label=item["label"],
                source=item["source"],
            )
            row.type = item["type"]
            row.confidence = float(item["confidence"])
            row.last_updated = datetime.now(timezone.utc)
            db.add(row)
            count += 1
        db.commit()
        return {"imported": count}

    def case_detail(self, db: Session, case_id: str) -> dict | None:
        case = db.get(Case, case_id)
        if not case:
            return None
        return {
            **row_dict(case),
            "entities": [
                row_dict(row)
                for row in db.scalars(
                    select(CaseEntity).where(CaseEntity.case_id == case_id)
                ).all()
            ],
            "notes": [
                row_dict(row)
                for row in db.scalars(
                    select(AnalystNote).where(AnalystNote.case_id == case_id)
                ).all()
            ],
            "alerts": [
                row_dict(row)
                for row in db.scalars(
                    select(WalletAlert).where(WalletAlert.case_id == case_id)
                ).all()
            ],
        }

    def case_report(self, db: Session, case_id: str, format_name: str) -> tuple[str | bytes, str]:
        # Pin/current/evidence reads belong to one SQLite snapshot, without writes.
        connection = db.connection()
        if connection.dialect.name == 'sqlite' and not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql('BEGIN')
        case = db.get(Case, case_id)
        if not case:
            raise KeyError(case_id)
        entities = [
            row_dict(row)
            for row in db.scalars(
                select(CaseEntity).where(CaseEntity.case_id == case_id)
            ).all()
        ]
        alerts = [
            row_dict(row)
            for row in db.scalars(
                select(WalletAlert).where(WalletAlert.case_id == case_id)
            ).all()
        ]
        notes = [
            row_dict(row)
            for row in db.scalars(
                select(AnalystNote).where(AnalystNote.case_id == case_id)
            ).all()
        ]
        from .attribution.cases import report_attribution, KINDS
        attribution = report_attribution(db,case_id)
        # Attribution pins have their own typed report section, not raw legacy metadata.
        entities = [row for row in entities if row['entity_type'] not in KINDS]
        args = (row_dict(case), entities, alerts, notes, attribution)
        if format_name == "pdf":
            return case_pdf(*args), "application/pdf"
        if format_name == "html":
            return case_html(*args), "text/html"
        if format_name == "json":
            return case_json(*args), "application/json"
        return case_markdown(*args), "text/markdown"

    def _labels_for_transactions(
        self, db: Session, transactions: list[NormalizedTransaction]
    ) -> list[dict]:
        identities = {(tx.chain,get_chain(tx.chain).adapter().address_key(value))
                      for tx in transactions for value in (tx.from_address,tx.to_address) if value}
        if not identities:return []
        by_chain={}
        for chain,address in identities:by_chain.setdefault(chain,set()).add(address)
        conditions=[self._address_membership(chain,Label.address,addresses) & Label.chain.in_((chain,'any'))
                    for chain,addresses in by_chain.items()]
        return [row_dict(row) for row in db.scalars(select(Label).where(or_(*conditions))).all()]

    @staticmethod
    def _address_membership(chain,column,addresses):
        adapter=get_chain(chain).adapter()
        insensitive={v for v in addresses if adapter.address_case_insensitive(v)}
        sensitive=set(addresses)-insensitive
        return or_(column.in_(sensitive),func.lower(column).in_(insensitive))

    def _exposure_paths(
        self, db: Session, chain: str, start_address: str, max_hops: int
    ) -> list[dict]:
        adapter=get_chain(chain).adapter()
        frontier = {adapter.address_key(start_address): [start_address]}
        visited = {adapter.address_key(start_address)}
        paths = []
        for hop in range(1, max_hops + 1):
            if not frontier:
                break
            addresses = set(frontier)
            rows = db.scalars(
                select(Transaction).where(
                    Transaction.chain == chain,
                    or_(
                        self._address_membership(chain,Transaction.from_address,addresses),
                        self._address_membership(chain,Transaction.to_address,addresses),
                    ),
                )
            ).all()
            next_frontier = {}
            for row in rows:
                left = adapter.address_key(row.from_address) if row.from_address else ""
                right = adapter.address_key(row.to_address) if row.to_address else ""
                for current, candidate in [(left, right), (right, left)]:
                    if current not in frontier or not candidate or candidate in visited:
                        continue
                    next_frontier[candidate] = frontier[current] + [candidate]
            if next_frontier:
                labels = db.scalars(
                    select(Label).where(
                        self._address_membership(chain,Label.address,set(next_frontier)),
                        Label.chain.in_((chain,'any'))
                    )
                ).all()
                for label in labels:
                    if label.type in {"Sanctioned", "Mixer", "Scam"}:
                        paths.append(
                            {
                                "hops": hop,
                                "path": next_frontier.get(adapter.address_key(label.address), []),
                                "terminal_address": label.address,
                                "terminal_type": label.type,
                                "source": label.source,
                                "confidence": label.confidence,
                            }
                        )
            visited.update(next_frontier)
            frontier = next_frontier
        return paths

    @staticmethod
    def _counterparties(
        address: str, transactions: list[NormalizedTransaction]
    ) -> list[dict]:
        counts = {}
        for tx in transactions:
            cp = tx.to_address if tx.direction == "outgoing" else tx.from_address
            if cp and get_chain(tx.chain).adapter().address_key(cp) != get_chain(tx.chain).adapter().address_key(address):
                counts[cp] = counts.get(cp, 0) + 1
        return [
            {"address": cp, "transaction_count": count}
            for cp, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
        ]

    @staticmethod
    def _tx_dict(tx: NormalizedTransaction) -> dict:
        data = tx.model_dump(exclude={"raw_payload"}) if hasattr(tx, "model_dump") else tx.dict(exclude={"raw_payload"})
        from .transaction_identity import build_event_key, event_identity
        data["event_key"] = build_event_key(tx)
        data["event_identity"] = event_identity(tx, data["event_key"])
        public = tx.raw_payload.get("_public") if isinstance(tx.raw_payload, dict) else None
        if isinstance(public, dict):
            data.update(public)
        if tx.timestamp:
            data["timestamp"] = tx.timestamp.isoformat()
        return data
