/* Optional libraries are loaded once, only when their view is requested. */
const viewAssets=new Map();
function loadViewAsset(url,css=false){
 if(viewAssets.has(url))return viewAssets.get(url);
 const pending=new Promise((resolve,reject)=>{
  const node=document.createElement(css?'link':'script');
  if(css){node.rel='stylesheet';node.href=url}else{node.src=url;node.async=false}
  node.onload=()=>resolve();node.onerror=()=>{viewAssets.delete(url);node.remove();reject(Error('Could not load this view. Reopen it to retry.'))};
  document.head.append(node);
 });viewAssets.set(url,pending);return pending;
}
async function ensureChartAssets(){
 for(const url of ['/vendor/d3-array.min.js','/vendor/d3-path.min.js','/vendor/d3-shape.min.js','/vendor/d3-sankey.min.js','/sankey-data.js'])await loadViewAsset(url);
}
async function ensureMapAssets(){await loadViewAsset('/vendor/leaflet.css',true);await loadViewAsset('/vendor/leaflet.js')}

// A structural comparison avoids retaining a second serialized copy of an email
// (including its body and prompt proposals) in a DOM data attribute.
function sameViewData(a,b){
 if(a===b)return true;
 if(!a||!b||typeof a!=='object'||typeof b!=='object'||Array.isArray(a)!==Array.isArray(b))return false;
 const keys=Object.keys(a);return keys.length===Object.keys(b).length&&keys.every(k=>Object.prototype.hasOwnProperty.call(b,k)&&sameViewData(a[k],b[k]));
}
