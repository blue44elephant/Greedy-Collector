"""NARC-1 real commands over migrated, isolated SQLite; no live collection."""
import json
import pytest
from sqlalchemy import text, select
from sqlalchemy.orm import Session
from tests.test_attribution_api import api, migrated_template, API, BTC, ETH, ok

N = API + "/narcotics"
def create(client, title="NARC test Case"):
    return ok(client.post(API+"/cases", json={"title": title}))
def fact(value, **p): return {"value": value, "provenance": p or {"kind": "analyst_entry"}}
def profile(client, case, **extra):
    payload = {"fields": {"vendor_alias": [fact("greenfox")], "marketplace": [fact("Analyst entered market")],
        "origin_country": [fact("NL")], "destination_country": [fact("GB")], "logistics_method": [fact("international_post")],
        "concealment": [fact("ordinary_packaging")], "platform": [fact("darknet_market")]},
        "wallets": [{"chain": "bitcoin", "address": BTC}],
        "substances": [{"source_name": "Source term", "category": "Analyst category", "quantity": "1.250", "unit": "g"}],
        "logistics": [{"kind": "parcel", "fields": {"origin_country": [fact("NL")], "carrier_service": [fact("Lawfully entered carrier")],
            "packaging": [fact("envelope")], "vendor_alias": [fact("greenfox")]}}],
        "period_start": "2026-01-01T00:00:00Z", "period_end": "2026-02-01T00:00:00Z", **extra}
    return ok(client.put(N+"/cases/"+case["id"]+"/profile", json=payload))
def related(client, a, b): return ok(client.post(N+"/cases/"+a["id"]+"/related", json={"case_ids": [b["id"]]}))

def test_optional_profile_and_case_scoped_structured_facts(api):
    client, _ = api; a,b = create(client),create(client)
    assert ok(client.get(N+"/cases/"+a["id"]+"/profile"))["profile"] is None
    saved = profile(client, a)
    assert saved["revision"] == 1 and saved["case_id"] == a["id"]
    assert saved["substances"][0]["quantity"] == "1.250"
    assert saved["substances"][0]["source_name"] == "Source term"
    assert saved["logistics"][0]["id"] and saved["wallets"][0]["address"] == BTC
    assert saved["fields"]["vendor_alias"][0]["provenance"]["kind"] == "analyst_entry"
    assert ok(client.get(N+"/cases/"+b["id"]+"/profile"))["profile"] is None
    assert ok(client.get(API+"/cases/"+a["id"]))["timeline"][-1]["kind"] == "narcotics_profile_saved"

def test_empty_profile_optional_values(api):
    client,_=api; a=create(client)
    saved=ok(client.put(N+"/cases/"+a["id"]+"/profile",json={}))
    assert not saved["fields"] and not saved["substances"]

@pytest.mark.parametrize("patch", [
    {"fields":{"platform":[fact("uncontrolled")]}}, {"wallets":[{"chain":"bitcoin","address":"unsupported"}]},
    {"substances":[{"source_name":"term","quantity":"NaN"}]}, {"substances":[{"source_name":"term","quantity":"-2"}]},
    {"period_start":"2026-01-01"}, {"period_start":"2026-02-01T00:00:00Z","period_end":"2026-01-01T00:00:00Z"},
    {"fields":{"arbitrary":[fact("bad")]}}, {"fields":{"domain":[fact("test.example",kind="case_note",reference_id="missing")]}},
    {"logistics":[{"entity_reference_ids":["missing"]}]}, {"private_phone_records":["x"]}
])
def test_invalid_inputs_rejected_without_source_requests(api,patch):
    client,_=api;a=create(client)
    assert client.put(N+"/cases/"+a["id"]+"/profile",json=patch).status_code==422

def test_source_note_provenance_frozen_and_wrong_case_rejected(api):
    client,_=api;a,b=create(client),create(client)
    note=ok(client.post(API+"/cases/"+a["id"]+"/notes",json={"body":"explicit source observation"}))
    fields={"vendor_alias":[fact("greenfox",kind="case_note",reference_id=note["id"])]}
    saved=profile(client,a,fields=fields)
    assert saved["fields"]["vendor_alias"][0]["provenance"]["source_snapshot"]["body"]==note["body"]
    assert client.put(N+"/cases/"+b["id"]+"/profile",json={"fields":fields}).status_code==422

def test_fingerprint_determinism_version_weights_and_profile_history(api):
    client,_=api;a=create(client);profile(client,a)
    path=N+"/cases/"+a["id"]+"/fingerprints"
    first,second=[ok(client.post(path,json={})) for _ in range(2)]
    assert first["id"]!=second["id"] and first["content_fingerprint"]==second["content_fingerprint"]
    changed=profile(client,a,expected_revision=1,fields={"vendor_alias":[fact("new explicit alias")]})
    third=ok(client.post(path,json={"weights":{"wallet":50}}))
    assert third["source_case_version"]>first["source_case_version"] and third["weights"]["wallet"]==50
    assert ok(client.get(N+"/runs/mo_fingerprint/"+first["id"]))==first
    assert changed["revision"]==2
    assert len(ok(client.get(N+"/cases/"+a["id"]+"/history"))["profiles"])==2
    assert client.put(N+"/cases/"+a["id"]+"/profile",json={"expected_revision":1}).status_code==409
    assert client.post(path,json={"weights":{"wallet":0}}).status_code==422

def test_exact_wallet_alias_normalized_mo_and_missing_denominator(api):
    client,_=api;a,b=create(client,"A"),create(client,"B")
    profile(client,a,logistics=[],fields={"vendor_alias":[fact("greenfox")],"origin_country":[fact(" NL ")],"platform":[fact("unknown")]})
    profile(client,b,logistics=[],fields={"vendor_alias":[fact("greenfox")],"origin_country":[fact("nl")],"platform":[fact("website")]})
    run=related(client,a,b);result=run["related_cases"][0]["similarity"]
    fields={r["field"]:r for r in result["contributions"]}
    assert fields["wallet"]["state"]==fields["vendor_alias"]["state"]=="EXACT MATCH"
    assert fields["origin_country"]["state"]=="NORMALIZED MATCH"
    assert fields["platform"]["state"]=="UNKNOWN" and fields["platform"]["effective_weight"]==0
    assert result["score"]==100
    assert {"EXACT_WALLET_REUSE","EXACT_ALIAS_REUSE","SIMILAR_MO"} <= {l["link_type"] for l in run["links"]}
    repeat=related(client,a,b)["related_cases"][0]["similarity"]
    assert repeat["score"]==result["score"] and repeat["denominator"]==result["denominator"]
    assert run["related_cases"][0]["temporal_relation"]=="OVERLAPPING"
    assert "same_cartel" not in json.dumps(run)

def test_weak_matches_do_not_overwhelm_strong_contradiction(api):
    client,_=api;a,b=create(client),create(client)
    fields={k:[fact("same")] for k in ["origin_country","origin_region","origin_city","destination_country",
        "destination_region","destination_city","concealment","packaging","delivery_method","drop_method","mo_tag"]}
    profile(client,a,fields=fields,substances=[],logistics=[])
    profile(client,b,fields=fields,substances=[],logistics=[],wallets=[{"chain":"ethereum","address":ETH}])
    result=related(client,a,b)["related_cases"][0]["similarity"]
    assert result["score"]<=33.34
    assert result["matched_weight"]<=20 and result["denominator"]>=40

def test_cross_chain_wallets_never_match_or_merge(api):
    client,_=api;a,b=create(client),create(client)
    for case,chain in [(a,"ethereum"),(b,"base")]: profile(client,case,wallets=[{"chain":chain,"address":ETH}],fields={},logistics=[],substances=[])
    run=related(client,a,b)
    assert not any(l["link_type"]=="EXACT_WALLET_REUSE" for l in run["links"])
    graph=ok(client.post(N+"/nexus",json={"case_ids":[a["id"],b["id"]]}))
    assert len([n for n in graph["nodes"] if n["type"]=="wallet"])==2

def test_link_reviews_append_only_and_pins_scoped(api):
    client,engine=api;a,b,c=create(client),create(client),create(client)
    profile(client,a);profile(client,b);run=related(client,a,b)
    link=next(l for l in run["links"] if l["link_type"]=="EXACT_WALLET_REUSE")
    pinpath=N+"/cases/"+a["id"]+"/pins"
    assert client.post(pinpath,json={"kind":"reviewed_link","reference_id":link["id"]}).status_code==409
    reviewed=ok(client.post(N+"/links/"+link["id"]+"/reviews",json={"expected_sequence":0,"status":"RELEVANT","rationale":"Explicit technical linkage"}))
    pin=ok(client.post(pinpath,json={"kind":"reviewed_link","reference_id":link["id"]}))
    assert pin["metadata_json"]["narcotics_pin"]["snapshot"]["review"]["status"]=="RELEVANT"
    assert client.post(N+"/cases/"+c["id"]+"/pins",json={"kind":"case_comparison","reference_id":run["id"]}).status_code==422
    assert client.post(N+"/links/"+link["id"]+"/reviews",json={"expected_sequence":0,"status":"IRRELEVANT","rationale":"stale"}).status_code==409
    revised=ok(client.post(N+"/links/"+link["id"]+"/reviews",json={"expected_sequence":1,"status":"IRRELEVANT","rationale":"Expected lawful shared service"}))
    assert len(revised["review"]["history"])==2 and revised["source_objects"]==link["source_objects"]
    with Session(engine) as db:
        from greedy_collector.models import CaseEntity
        assert db.get(CaseEntity,pin["id"]).metadata_json==pin["metadata_json"]

def test_graph_typed_multi_case_provenance_bounded_priority_no_analytical_writes(api):
    client,engine=api;a,b=create(client),create(client);profile(client,a);profile(client,b)
    with Session(engine) as db: before={t:db.scalar(text("SELECT count(*) FROM "+t)) for t in ["risk_results","attribution_claims","attribution_entities"]}
    run=related(client,a,b)
    link=next(l for l in run["links"] if l["link_type"]=="EXACT_WALLET_REUSE")
    ok(client.post(N+"/links/"+link["id"]+"/reviews",json={"expected_sequence":0,"status":"RELEVANT","rationale":"Technical identifier confirmed in Cases"}))
    graph=ok(client.post(N+"/nexus",json={"case_ids":[b["id"],a["id"]],"link_run_ids":[run["id"]]}))
    assert {"case","wallet","alias","marketplace","location","logistics","consignment","substance"}<={n["type"] for n in graph["nodes"]}
    assert {"CASE_HAS_WALLET","CASE_HAS_ALIAS","CASE_HAS_CONSIGNMENT","CONSIGNMENT_ORIGIN","CASE_RELATED_TO_CASE"}<={e["type"] for e in graph["edges"]}
    assert all(e["provenance"] and e["source"]!=e["target"] for e in graph["edges"])
    assert len({n["id"] for n in graph["nodes"]})==len(graph["nodes"])
    assert "positions" not in json.dumps(graph)
    score=ok(client.post(N+"/priority",json={"nexus_id":graph["id"]}))
    repeat=ok(client.post(N+"/priority",json={"nexus_id":graph["id"]}))
    assert repeat["metrics"]==score["metrics"]
    shared=next(m for m in score["metrics"] if m["node_type"]=="wallet")
    assert shared["case_count"]==2 and shared["independent_source_count"]==0
    assert shared["score"]>next(m["score"] for m in score["metrics"] if m["node_type"]=="consignment")
    assert "leadership probability" in score["disclaimer"]
    small=ok(client.post(N+"/nexus",json={"case_ids":[a["id"]],"max_nodes":3,"max_edges":1}))
    assert small["bounds"]["truncated"] and len(small["nodes"])==3 and len(small["edges"])<=1
    assert client.post(N+"/nexus",json={"case_ids":[a["id"]],"link_run_ids":[run["id"]]}).status_code==422
    for kind,id in [("mo_fingerprint",run["origin_fingerprint"]["id"]),("case_comparison",run["id"]),("nexus",graph["id"]),("priority",score["id"])]:
        ok(client.post(N+"/cases/"+a["id"]+"/pins",json={"kind":kind,"reference_id":id}))
    with Session(engine) as db: assert before=={t:db.scalar(text("SELECT count(*) FROM "+t)) for t in before}

def test_archived_case_read_history_no_writes(api):
    client,_=api;a=create(client);profile(client,a)
    current=ok(client.get(API+"/cases/"+a["id"]))
    ok(client.patch(API+"/cases/"+a["id"],json={"expected_version":current["version"],"archived":True}))
    assert ok(client.get(N+"/cases/"+a["id"]+"/profile"))["profile"]
    assert client.put(N+"/cases/"+a["id"]+"/profile",json={"expected_revision":1}).status_code==409
    assert client.post(N+"/cases/"+a["id"]+"/fingerprints",json={}).status_code==409
    assert client.delete(API+"/cases/"+a["id"]).status_code==405
