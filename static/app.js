const $ = (id) => document.getElementById(id);
const shortHash = (value, a=12, b=8) => value ? `${value.slice(0,a)}…${value.slice(-b)}` : '—';
const esc = (value) => String(value ?? '').replace(/[&<>\"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[ch]));
const timeText = (stamp) => { if (!stamp) return '—'; const d = new Date(Number(stamp)*1000); return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString(); };
const showNotice = (id, message, error=false) => { const el=$(id); el.hidden=false; el.textContent=message; el.classList.toggle('error',error); };
async function api(path, options={}) { const response=await fetch(path,{headers:{'Content-Type':'application/json',...(options.headers||{})},...options}); const data=await response.json().catch(()=>({detail:`HTTP ${response.status}`})); if(!response.ok) throw new Error(data.detail||data.message||`Request failed (${response.status})`); return data; }
async function loadDashboard(){
  try {
    const [status,wallet,chain,mempool,peerData]=await Promise.all([api('/api/status'),api('/api/wallet'),api('/api/chain'),api('/api/mempool'),api('/api/peers')]);
    $('status-dot').className='pulse online'; $('network-label').textContent='Node responding';
    $('height').textContent=status.height ?? Math.max(0,chain.length-1); $('peer-count').textContent=Array.isArray(peerData.peers)?peerData.peers.length:Object.keys(peerData.peers||{}).length;
    $('pending-count').textContent=mempool.count ?? mempool.transactions.length; $('network-state').textContent='ONLINE'; $('node-version').textContent=`${status.service||'Blockchain Node'} · ${status.version||''}`;
    $('address').textContent=wallet.address||status.address||'No wallet address'; $('balance').textContent=Number(wallet.balance||0).toLocaleString(undefined,{maximumFractionDigits:8});
    renderBlocks(chain); renderMempool(mempool.transactions||[]); $('last-updated').textContent=`Updated ${new Date().toLocaleTimeString()}`;
  } catch(error){ $('status-dot').className='pulse offline'; $('network-label').textContent='Node API unavailable'; $('network-state').textContent='OFFLINE'; $('last-updated').textContent=error.message; }
}
function renderBlocks(chain){const body=$('blocks-body');if(!Array.isArray(chain)||!chain.length){body.innerHTML='<tr><td colspan="4" class="empty">No blocks returned.</td></tr>';return;}body.innerHTML=chain.slice(-8).reverse().map(block=>`<tr><td>#${block.index}</td><td><code title="${esc(block.hash||'')}">${esc(shortHash(block.hash,16,8))}</code></td><td>${(block.transactions||[]).length}</td><td>${timeText(block.timestamp)}</td></tr>`).join('');}
function renderMempool(txs){const list=$('mempool-list');$('mempool-tag').textContent=`${txs.length} ITEM${txs.length===1?'':'S'}`;if(!txs.length){list.innerHTML='<p class="empty">No pending transactions.</p>';return;}list.innerHTML=txs.slice(0,8).map(tx=>`<div class="list-item"><code title="${esc(tx.txid||'')}">${esc(shortHash(tx.txid,14,7))}</code><span>${Number(tx.amount||0).toLocaleString()} GEN</span></div>`).join('');}
$('refresh-btn').addEventListener('click',loadDashboard);
$('copy-address').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('address').textContent);$('copy-address').textContent='Copied';setTimeout(()=>$('copy-address').textContent='Copy',1200);}catch(e){showNotice('send-notice','Could not access clipboard. Select and copy the address manually.',true);}});
$('send-form').addEventListener('submit',async(event)=>{event.preventDefault();const btn=$('send-btn');btn.disabled=true;btn.textContent='Submitting…';try{const result=await api('/api/send',{method:'POST',body:JSON.stringify({recipient:$('recipient').value.trim(),amount:Number($('amount').value)})});showNotice('send-notice',`Transaction accepted and broadcast. ID: ${result.txid}`);$('send-form').reset();await loadDashboard();}catch(error){showNotice('send-notice',error.message,true);}finally{btn.disabled=false;btn.innerHTML='Send transaction <span>→</span>';}});
$('mine-btn').addEventListener('click',async()=>{const btn=$('mine-btn');btn.disabled=true;btn.textContent='Mining… keep this page open';try{const result=await api('/api/mine',{method:'POST',body:'{}'});showNotice('mine-notice',`Block #${result.block?.index??'?'} mined. Hash: ${result.block?.hash||'unknown'}`);await loadDashboard();}catch(error){showNotice('mine-notice',error.message,true);}finally{btn.disabled=false;btn.textContent='⚒ Mine a block';}});
loadDashboard();setInterval(loadDashboard,15000);
