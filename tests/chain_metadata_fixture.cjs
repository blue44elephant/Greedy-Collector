// Test-only metadata for pure modules; browser tests exercise the real endpoint.
const {pathToFileURL}=require('node:url');
const path=require('node:path');
module.exports=async()=>{
  const module=await import(pathToFileURL(path.join(__dirname,'../static/js/chains.js')));
  module.setChainMetadata([
    {id:'bitcoin',display_name:'Bitcoin',native_symbol:'BTC',address_case:'bech32_insensitive',capabilities:['discovery','labels']},
    {id:'ethereum',display_name:'Ethereum',native_symbol:'ETH',address_case:'insensitive',capabilities:['discovery','labels']}
  ]);
  return module;
};
