import {supportedChain} from './chains.js';
import {element, UserError} from './ui.js';
import {graphSubjectIsUnambiguous} from './attribution_summary.js';

// Envelope guard only. The existing local resolver and Discovery planner remain
// authoritative for addresses; no provider or persistence operation belongs here.
export function walletContext(value) {
  if (!value || !['wallet','graph'].includes(value.origin) || !supportedChain(value.chain) || typeof value.address !== 'string' || !value.address.trim() || value.address.length > 128) return null;
  return {origin:value.origin,chain:value.chain,address:value.address.trim(),isCurrent:typeof value.isCurrent === 'function' ? value.isCurrent : null};
}
export function graphWalletEligible(graph, node) {
  if (!node || typeof node.id !== 'string') return false;
  // The existing blockchain graph's `type` is a Label category (for example
  // Wallet, Exchange or Unknown), not its structural entity kind.
  if ([node.kind,node.entity_type,node.node_type].some(type => type != null && !['wallet','address','blockchain_address'].includes(type))) return false;
  if (['transaction','entity','repository'].includes(String(node.type).toLowerCase())) return false;
  return !!walletContext({origin:'graph',chain:node.chain,address:node.id}) && graphSubjectIsUnambiguous(graph,node);
}
export function discoveryAction({chain,address}, origin, isCurrent = () => true) {
  const context = walletContext({chain,address,origin});
  if (!context) return element('span','Discovery requires a supported wallet subject.','muted small');
  const button = element('button','Discover public evidence','secondary'); button.type = 'button';
  button.dataset.discoveryAction = origin;
  const current = () => button.isConnected && isCurrent();
  button.addEventListener('click', () => {
    if (!current()) return;
    document.dispatchEvent(new CustomEvent('open-discovery',{detail:{...context,isCurrent:current}}));
  });
  return button;
}
export function returnFromDiscovery(context) {
  const value = walletContext(context);
  if (!value?.isCurrent || !value.isCurrent()) throw new UserError('The original view has changed. Use the workspace tabs to open the current Wallet or Graph view.');
  document.dispatchEvent(new CustomEvent('return-discovery',{detail:{workspace:value.origin}}));
}
