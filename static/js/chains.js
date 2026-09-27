import {api} from './api.js';
export const chains = [];
const definitions = new Map();
export function setChainMetadata(rows) {
  definitions.clear(); chains.splice(0);
  for (const row of rows) { definitions.set(row.id, Object.freeze(row)); chains.push([row.id,row.display_name]); }
}
export async function loadChains() { setChainMetadata((await api('/chains')).chains); }
export const chainMetadata = id => definitions.get(id);
export const supportedChain = id => definitions.has(id);
export const hasCapability = (id, capability) => definitions.get(id)?.capabilities.includes(capability) ?? false;
export function addressKey(chain, address) {
  const mode = definitions.get(chain)?.address_case;
  return mode === 'insensitive' || (mode === 'bech32_insensitive' && /^(?:bc1|ltc1)/i.test(address)) ? address.toLowerCase() : address;
}
