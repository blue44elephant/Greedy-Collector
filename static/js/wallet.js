import {api} from "./api.js";
import {byId, text, element, dateText, shortValue, action, run, UserError} from "./ui.js";
const providerNames = {blockstream:"Blockstream", mempool_space:"Mempool.space", etherscan:"Etherscan", alchemy:"Alchemy"};
let navigate;
export function investigate(chain, address) {
  if (byId("lookup-form").dataset.busy === "true") return;
  navigate("wallet");
  byId("chain").value = chain;
  byId("wallet-address").value = address;
  return lookup(false);
}
function renderLookup(data, stored = false) {
  const profile = data.address;
  const transactions = data.transactions;
  const risk = data.risk || {findings: []};
  text("data-mode", stored ? "Stored local state" : "Fresh provider lookup");
  byId("stored-note").hidden = !stored;
  text("transactions-mode", stored ? "Stored transaction rows" : "Fresh lookup records");
  byId("risk-time").hidden = !stored || !data.risk;
  text("risk-time", `Stored risk calculated: ${dateText(risk.calculated_at)}`);
  const bitcoin = profile.chain === "bitcoin";
  text("retrieval-label", stored ? "Stored profile updated" : "Retrieved");
  text("result-chain", bitcoin ? "Bitcoin" : "Ethereum");
  text("result-address", profile.address);
  text("balance", `${profile.balance_native} ${bitcoin ? "BTC" : "ETH"}`);
  text("risk-score", risk.score == null ? "Not available" : `${risk.score} / 100`);
  text("risk-level", risk.level);
  text("record-count", transactions.length);
  text("first-seen", dateText(profile.first_seen));
  text("last-activity", dateText(profile.last_activity));
  text("provider", providerNames[data.provenance?.source_api ?? profile.metadata_json?.source_api] ?? "Not available");
  text("retrieved-at", dateText(data.provenance?.retrieved_at ?? profile.updated_at));
  // Ethereum metadata uses the fetched count, not a separate provider total.
  const providerCount = profile.metadata_json?.transaction_count;
  byId("provider-count").hidden = !bitcoin || providerCount === null || providerCount === undefined;
  text("provider-count", bitcoin ? `Provider-reported Bitcoin transaction count: ${providerCount ?? "Not available"}. This may differ from records returned.` : "");

  const rows = document.createDocumentFragment();
  for (const tx of transactions) {
    const row = element("tr");
    const unconfirmed = bitcoin && !tx.timestamp && !tx.block_number;
    for (const value of [tx.tx_hash, tx.direction, tx.from_address, tx.to_address, tx.value_native, tx.token_symbol, unconfirmed ? "Unconfirmed" : dateText(tx.timestamp), unconfirmed ? "—" : (tx.block_number || "Not available")]) {
      const cell = element("td", value ?? "Not available");
      row.append(cell);
    }
    [0, 2, 3].forEach((index) => {
      row.children[index].replaceChildren(shortValue([tx.tx_hash, tx.direction, tx.from_address, tx.to_address][index]));
    });
    row.children[4].className = "numeric";
    rows.append(row);
  }
  byId("transaction-rows").replaceChildren(rows);
  byId("transactions-empty").hidden = transactions.length !== 0;
  byId("transactions-table").hidden = transactions.length === 0;

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
    if (finding.explanation) card.append(element("p", finding.explanation));
    if (finding.evidence != null) {
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
    item.append(action("Investigate", () => investigate(profile.chain, counterparty.address)));
    counterpartyNodes.append(item);
  }
  byId("counterparties").replaceChildren(counterpartyNodes);
  byId("counterparties-empty").hidden = counterparties.length !== 0;
  byId("results").hidden = false;
}


async function lookup(stored) {
  const form = byId("lookup-form");
  const chain = byId("chain").value;
  const address = byId("wallet-address").value.trim();
  if (form.dataset.busy === "true") return;
  byId("results").hidden = true;
  return run(form, async () => {
    if (!address) throw new UserError("Enter a public wallet address.");
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
    renderLookup(data, stored);
    byId("counterparties-empty").textContent = stored ? "Counterparties are included in fresh lookup results." : "No counterparties were returned.";
    document.dispatchEvent(new CustomEvent("wallet-selected", {detail:{chain, address}}));
    byId("overview-heading").focus();
  }, stored ? "Loading stored state…" : "Retrieving public records…");
}
export function initWallet(go) {
  navigate = go;
  byId("lookup-form").addEventListener("submit", event => {event.preventDefault(); lookup(false);});
  byId("stored-button").addEventListener("click", () => lookup(true));
}
