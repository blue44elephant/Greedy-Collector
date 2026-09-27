import {walletClustering} from './clustering.js';
import {chains, chainMetadata, hasCapability} from './chains.js';
import {manualSourceAction} from './discovery_manual_source.js';
import {discoveryAction} from "./discovery_handoff.js";
import {attributionSummary} from "./attribution_summary.js";
import {addToCaseButton} from "./case_actions.js";
import {readLabels, labelsFor, labelCards} from "./label_ui.js";
import {api} from "./api.js";
import {byId, text, element, dateText, shortValue, action, run, UserError} from "./ui.js";
const providerNames = {blockstream:"Blockstream", mempool_space:"Mempool.space", litecoinspace:"Litecoin Space", etherscan:"Etherscan", alchemy:"Alchemy", trongrid:"TronGrid", trongrid_trc20:"TronGrid TRC-20", "solana-json-rpc":"Solana JSON-RPC"};
const supportedIdentifierTypes = "Supported: Bitcoin addresses and bare 64-hex transaction IDs; Ethereum-compatible 0x + 40-hex addresses and 0x + 64-hex transaction hashes; TRON addresses and hinted transaction IDs; Solana addresses and transaction signatures; Litecoin transparent addresses and hinted 64-hex transaction IDs; Monero mainnet addresses (observation only).";
let navigate;
export function investigate(chain, address) {
  if (byId("lookup-form").dataset.busy === "true") return;
  // A new investigation replaces this result; do not refresh its old attribution.
  byId("results").hidden = true;
  navigate("wallet");
  byId("wallet-address").value = address;
  return lookup(false, chain);
}
function renderLookup(data, stored = false, labels = [], labelsUnavailable = false) {
  const profile = data.address;
  byId("wallet-clustering").replaceChildren(walletClustering(profile.chain,profile.address));
  byId("observation-result").hidden = true;
  byId("wallet-case-action").replaceChildren(hasCapability(profile.chain, "cases") ? addToCaseButton("wallet", profile.chain, profile.address) : element("span", "Case references are unavailable for this chain."));
  byId("wallet-graph").hidden = !hasCapability(profile.chain, "graph");
  byId("wallet-labels").replaceChildren(element("h3", "Wallet labels"),
    labelCards(labelsFor(labels, profile.chain, profile.address), "No stored labels for this wallet."));
  byId("wallet-labels").append(element("p", labelsUnavailable ? "Current labels could not be loaded. Returned lookup annotations are shown where available." : "Current stored annotations. Risk evidence reflects labels at evaluation time; labels do not prove ownership.", "muted small"));
  const transactions = data.transactions;
  const risk = data.risk || {findings: []};
  text("data-mode", stored ? "Stored local state" : "Fresh provider lookup");
  byId("stored-note").hidden = !stored;
  text("transactions-mode", stored ? "Stored transaction rows" : "Fresh lookup records");
  byId("risk-time").hidden = !stored || !data.risk;
  text("risk-time", `Stored risk calculated: ${dateText(risk.calculated_at)}`);
  const bitcoin = profile.chain === "bitcoin";
  text("retrieval-label", stored ? "Stored profile updated" : "Retrieved");
  text("result-chain", chainMetadata(profile.chain)?.display_name ?? profile.chain);
  text("result-address", profile.address);
  text("balance", `${profile.balance_native} ${chainMetadata(profile.chain)?.native_symbol ?? ""}`);
  text("risk-score", risk.score == null ? "Not available" : `${risk.score} / 100`);
  text("risk-level", risk.level);
  text("record-count", transactions.length);
  text("first-seen", dateText(profile.first_seen));
  text("last-activity", dateText(profile.last_activity));
  text("provider", providerNames[data.provenance?.source_api ?? profile.metadata_json?.source_api] ?? "Not available");
  text("retrieved-at", dateText(data.provenance?.retrieved_at ?? profile.updated_at));
  // Ethereum metadata uses the fetched count, not a separate provider total.
  const providerCount = profile.metadata_json?.transaction_count;
  const hasProviderCount = bitcoin || profile.chain === "litecoin";
  byId("provider-count").hidden = !hasProviderCount || providerCount === null || providerCount === undefined;
  text("provider-count", hasProviderCount ? "Provider-reported " + (chainMetadata(profile.chain)?.display_name ?? profile.chain) + " address transaction count: " + (providerCount ?? "Not available") + ". This may differ from bounded records returned." : "");

  const rows = document.createDocumentFragment();
  for (const tx of transactions) {
    const row = element("tr");
    const unconfirmed = hasCapability(tx.chain,'pending_transactions') && !tx.timestamp && !tx.block_number;
    for (const value of [tx.tx_hash, tx.direction, tx.from_address, tx.to_address, tx.value_native, tx.token_symbol, unconfirmed ? "Unconfirmed" : dateText(tx.timestamp), unconfirmed ? "—" : (tx.block_number || "Not available")]) {
      const cell = element("td", value ?? "Not available");
      row.append(cell);
    }
    [0, 2, 3].forEach((index) => {
      row.children[index].replaceChildren(shortValue([tx.tx_hash, tx.direction, tx.from_address, tx.to_address][index]));
    });
    row.children[4].className = "numeric";
    if (["trc20", "erc20", "spl_token", "token2022"].includes(tx.asset_type)) {
      const details = [tx.token_name, tx.token_contract || tx.token_mint || tx.asset_contract, tx.token_decimals != null ? `${tx.token_decimals} decimals` : null, tx.raw_value != null ? `raw ${tx.raw_value}` : null, tx.confirmed === true ? "Confirmed" : null].filter(Boolean).join(" · ");
      row.children[5].replaceChildren(element("span", tx.token_symbol || "TOKEN"), element("span", details, "muted small"));
    }
    rows.append(row);
  }
  byId("transaction-rows").replaceChildren(rows);
  byId("transactions-empty").hidden = transactions.length !== 0;
  byId("transactions-table").hidden = transactions.length === 0;

  const breakdown = byId("risk-breakdown");
  breakdown.replaceChildren();
  if (risk.category_contributions) {
    const summary = element("dl", undefined, "metadata");
    for (const [key, label] of [["direct_evidence", "Direct evidence"], ["exposure", "Exposure"], ["behavioral", "Behavioral"], ["context", "Context"]]) {
      const category = risk.category_contributions[key];
      if (!category) continue;
      const value = key === "behavioral" && risk.behavioral_supported === false ? "Not available for this chain" : `${category.applied} points (raw ${category.raw}; cap ${category.cap})`;
      const row = element("div"); row.append(element("dt", label), element("dd", value)); summary.append(row);
    }
    breakdown.append(element("h3", "Score breakdown"), summary, element("p", "Activity context adds no risk points. Applied contributions sum to the score; overlapping evidence and category caps can reduce raw points.", "muted small"));
  } else if (stored && data.risk) {
    breakdown.append(element("p", "This saved result has no versioned category breakdown. Its original score is preserved. A fresh lookup uses the current scoring policy.", "muted small"));
  }
  const findings = Array.isArray(risk.findings) ? risk.findings : [];
  const findingNodes = document.createDocumentFragment();
  for (const finding of findings) {
    const card = element("article", undefined, "finding");
    card.append(element("h3", finding.rule_name ?? finding.rule_id ?? "Risk finding"));
    const metadata = [];
    if (finding.severity != null) metadata.push(`Severity: ${finding.severity}`);
    if (finding.confidence != null) metadata.push(`Confidence: ${finding.confidence}`);
    if (finding.score_contribution != null) metadata.push(`Score contribution: ${finding.score_contribution}`);
    card.append(element("p", metadata.join(" · "), "finding-meta"));
    if (finding.raw_score_contribution != null) card.append(element("p", `Category: ${finding.category} · Raw points: ${finding.raw_score_contribution} · ${finding.score_adjustment}`, "finding-meta"));
    if (finding.explanation) card.append(element("p", finding.explanation));
    if (finding.evidence != null) {
      const observations = finding.evidence.observations || [finding.evidence];
      const evidenceLabels = [...new Map(observations.filter(item => item.label).map(item => [JSON.stringify(item.label), item.label])).values()];
      if (evidenceLabels.length) card.append(labelCards(evidenceLabels));
      const details = element("details");
      details.append(element("summary", `Evidence${finding.rule_id ? ` · ${finding.rule_id}` : ""}`));
      details.append(element("pre", JSON.stringify(finding.evidence, null, 2)));
      card.append(details);
    }
    findingNodes.append(card);
  }
  byId("risk-findings").replaceChildren(findingNodes);
  byId("risk-empty").hidden = findings.length !== 0;
  text("risk-empty", stored && !data.risk ? "No stored risk result is available for this address." : "No risk findings were produced for the returned activity.");
  text("risk-disclaimer", risk.disclaimer || "Risk findings are rule-based indicators and are not proof of wrongdoing.");

  const counterparties = Array.isArray(data.counterparties) ? data.counterparties : [];
  const counterpartyNodes = document.createDocumentFragment();
  for (const counterparty of counterparties) {
    const item = element("li");
    item.append(shortValue(counterparty.address), element("span", `${counterparty.transaction_count} transaction records`, "muted small"));
    item.append(labelCards(labelsFor(labels, profile.chain, counterparty.address)));
    item.append(action("Investigate", () => investigate(profile.chain, counterparty.address)));
    counterpartyNodes.append(item);
  }
  byId("counterparties").replaceChildren(counterpartyNodes);
  byId("counterparties-empty").hidden = counterparties.length !== 0;
  byId("wallet-discovery").replaceChildren(element("h3", "Discovery"),
    element("p", "Public-source pivots and candidate clues. Choose pivots explicitly in Discovery.", "muted small"),
    manualSourceAction({chain:profile.chain,address:profile.address}, () => !byId("results").hidden && byId("lookup-form").dataset.busy !== "true"),
    discoveryAction({chain:profile.chain,address:profile.address}, "wallet", () => !byId("results").hidden && byId("lookup-form").dataset.busy !== "true"));
  byId("wallet-attribution").replaceChildren(attributionSummary({chain:profile.chain,address:profile.address}));
  byId("results").hidden = false;
}


function renderObservationOnly(chain, address, labels = [], labelsUnavailable = false) {
  const host = byId("observation-result");
  const heading = element("h2", "Public-source observation"); heading.tabIndex = -1;
  const metadata = chainMetadata(chain);
  host.replaceChildren(heading, element("p", metadata?.display_name ?? chain, "badge"), element("p", address, "full-address"),
    element("p", "Observation-only / public-source investigation.", "bounded-note"),
    element("p", "Public on-chain address history is unavailable from the address alone.", "bounded-note"),
    element("p", "This limitation is not evidence of inactivity, and Greedy Collector has not checked a public balance or transaction history.", "muted small"));
  const available = (metadata?.capabilities || []).map(value => ({address_validation:"Address validation",labels:"Local Labels",cases:"Cases",attribution:"Attribution",discovery:"Discovery"}[value])).filter(Boolean);
  host.append(element("p", "Available actions: " + (available.join(", ") || "None") + ".", "muted small"));
  host.append(element("h3", "Wallet labels"), labelCards(labelsFor(labels, chain, address), "No stored labels for this address."));
  host.append(element("p", labelsUnavailable ? "Current labels could not be loaded." : "Labels are analyst/source annotations, not proof of ownership.", "muted small"));
  const actions = element("div", undefined, "toolbar");
  if (hasCapability(chain, "labels")) actions.append(action("Add local label", () => {
    document.dispatchEvent(new CustomEvent("open-label-address", {detail:{chain,address}}));
  }));
  if (hasCapability(chain, "cases")) actions.append(addToCaseButton("wallet", chain, address));
  const current = () => host.isConnected && !host.hidden && byId("lookup-form").dataset.busy !== "true";
  if (hasCapability(chain, "discovery")) {
    actions.append(manualSourceAction({chain,address}, current));
    actions.append(discoveryAction({chain,address}, "wallet", current));
  }
  if (hasCapability(chain, "attribution")) host.append(attributionSummary({chain,address}));
  host.append(actions, element("p", "No blockchain provider request is made when this address is resolved.", "muted small"));
  host.hidden = false;
  heading.focus();
}

async function lookup(stored, chain_hint = undefined) {
  const form = byId("lookup-form");
  const input = byId("wallet-address").value.trim();
  if (form.dataset.busy === "true") return;
  byId("results").hidden = byId("transaction-result").hidden = true;
  byId("observation-result").hidden = true;
  return run(form, async () => {
    if (!input) throw new UserError("Enter a supported wallet address or transaction hash.");
    const selectedHint = chain_hint ?? (byId("chain-hint").value || undefined);
    const resolved = await api("/resolve", {method:"POST", body:{input, ...(selectedHint ? {chain_hint:selectedHint} : {})}});
    if (resolved.kind === "ambiguous") {
      const choices = (resolved.possibilities || []).map(item => `${chainMetadata(item.chain)?.display_name ?? item.chain} ${item.kind}`).join(" / ");
      throw new UserError(`This value matches more than one supported identifier format (${choices}). Choose a Network hint to continue.`);
    }
    if (!["address", "transaction"].includes(resolved.kind)) {
      throw new UserError(`Greedy Collector could not identify this value as a supported wallet address or transaction hash. ${supportedIdentifierTypes}`);
    }
    const chain = resolved.chain, address = resolved.normalized;
    byId("wallet-address").value = address;
    if (resolved.kind === "transaction") {
      if (stored) throw new UserError("Stored-state views require a wallet address. Use Search to retrieve this transaction.");
      const tx = await api("/lookup/tx", {method:"POST", body:{chain, tx_hash:address}});
      renderTransaction(tx);
      return;
    }
    if (!hasCapability(chain, "balance") || !hasCapability(chain, "transaction_history")) {
      let labelsUnavailable = false;
      const labels = await readLabels().catch(() => {labelsUnavailable = true; return [];});
      renderObservationOnly(chain, address, labels, labelsUnavailable);
      return;
    }
    const path = `/address/${chain}/${encodeURIComponent(address)}`;
    let data;
    if (stored) {
      const profile = await api(path);
      const txs = await api(`${path}/transactions`);
      const risk = await api(`${path}/risk`).catch(error => {if(error.status === 404) return null; throw error;});
      data = {address: profile, transactions: txs.transactions, risk, counterparties: []};
    } else {
      data = await api("/lookup/address", {method: "POST", body: {chain, address}});
    }
    let labelsUnavailable = false;
    const labels = await readLabels().catch(() => {labelsUnavailable = true; return data.labels || [];});
    renderLookup(data, stored, labels, labelsUnavailable);
    byId("counterparties-empty").textContent = stored ? "Counterparties are included in fresh lookup results." : "No counterparties were returned.";
    document.dispatchEvent(new CustomEvent("wallet-selected", {detail:{chain, address}}));
    byId("overview-heading").focus();
  }, stored ? "Resolving and loading stored state…" : "Resolving identifier and retrieving public records…");
}
function renderTransaction(tx) {
  const host = byId("transaction-result");
  const heading = element("h2", "Transaction"); heading.tabIndex = -1;
  const events = Array.isArray(tx.events) ? tx.events : null;
  host.replaceChildren(heading, element("p", tx.tx_hash, "full-address"));
  if (events) host.append(element("p", `${events.length} normalized transfer event${events.length === 1 ? "" : "s"} returned.`, "muted small"));
  const records = events || [tx];
  for (const record of records) {
  const eventHeading = events ? element("h3", record.event_key || "Transaction activity") : null;
  if (eventHeading) host.append(eventHeading);
  const rows = element("dl", undefined, "metadata");
  for (const [label, value] of [["Chain", record.chain || tx.chain], ["Amount", record.value_native], ["Asset", record.token_symbol],
    ["Asset type", record.asset_type], ["Token mint", record.token_mint || record.asset_contract || record.token_contract], ["Token decimals", record.token_decimals], ["Raw value", record.raw_value], ["Execution", record.execution_status],
    ["Source token account", record.source_token_account], ["Destination token account", record.destination_token_account], ["Amount basis", record.amount_basis],
    ["Confirmation", record.confirmed === true ? "Confirmed" : null], ["Block", record.block_number], ["Timestamp", record.timestamp ? dateText(record.timestamp) : hasCapability(record.chain || tx.chain,'pending_transactions') && !record.block_number ? "Unconfirmed" : null],
    ["Fee", record.fee], ["Provider", providerNames[record.source_api]]]) {
    if (value == null || value === "") continue;
    const row = element("div"); row.append(element("dt", label), element("dd", value)); rows.append(row);
  }
  host.append(rows);
  for (const [label, address] of [["Sender", record.from_address], ["Recipient", record.to_address]]) {
    if (!address) continue;
    const row = element("div", undefined, "toolbar");
    row.append(element("strong", label), shortValue(address), action("Investigate wallet", () => investigate(record.chain || tx.chain,address)));
    host.append(row);
  }
  }
  host.append(addToCaseButton("transaction", tx.chain, tx.tx_hash));
  host.append(element("p", "This is the provider's normalized transaction record. Bitcoin sender/recipient endpoints are representative. Transaction lookup does not automatically persist a wallet graph; investigate a wallet to collect its records.", "bounded-note"));
  host.hidden = false; heading.focus();
}
export function initWallet(go) {
  navigate = go;
  const hint = byId("chain-hint");
  for (const [id, name] of chains) { const option = element("option", name); option.value = id; hint.append(option); }
  byId("lookup-form").addEventListener("submit", event => {event.preventDefault(); lookup(false);});
  byId("stored-button").addEventListener("click", () => lookup(true));
  byId("wallet-graph").addEventListener("click", () => navigate("graph"));
}
