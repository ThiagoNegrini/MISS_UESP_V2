
const $=id=>document.getElementById(id);let candidates=[],scores={},arrivals={},category='Rainha do Samba',auditionView='pending';let mode='audition',contestCandidates=[],contestScores={},contestCriterion='aesthetics_sympathy',contestView='pending',agulhaResults=[],agulhaView='pending';const contestScoreOptions='<option value="">— Selecione —</option>'+Array.from({length:11},(_,i)=>{const n=(9+i/10).toFixed(1);return `<option value="${n}">${n.replace('.',',')}</option>`}).join('');const params=new URLSearchParams(location.search);if(params.get('categoria')==='passista')category='Passista de Ouro';if(params.get('categoria')==='diva')category='Diva do Samba (Plus Size)';if(params.get('stage')==='agulha')mode='agulha';
let evaluatorRoster=[];async function loadEvaluatorRoster(){try{let j;if(mode==='agulha')j=await api('/api/agulha/data');else j=await api('/api/evaluators?stage='+(mode==='contest'?'CONCURSO':'AUDICAO'));evaluatorRoster=j.evaluators||[];const saved=localStorage.getItem('uesp_evaluator_name')||'';$('evaluator').innerHTML='<option value="">— Selecione o avaliador —</option>'+evaluatorRoster.map(n=>'<option>'+esc(n)+'</option>').join('');if(evaluatorRoster.includes(saved))$('evaluator').value=saved;}catch(e){$('evaluator').innerHTML='<option value="">Lista de avaliadores indisponível</option>'}}$('evaluator').addEventListener('change',()=>{localStorage.setItem('uesp_evaluator_name',$('evaluator').value.trim());if(mode==='audition')render();else if(mode==='contest')renderContest();else renderAgulha()});$('search').addEventListener('input',()=>{if(mode==='audition')render();else if(mode==='contest')renderContest();else renderAgulha()});$('refreshAudition').addEventListener('click',async()=>{$('list').innerHTML='<div class="empty">Atualizando lista por ordem de chegada…</div>';try{await load()}catch(e){$('list').innerHTML='<div class="empty">Não foi possível atualizar a lista. Verifique a conexão e tente novamente.</div>'}});$('toggleAudited').addEventListener('click',()=>{auditionView=auditionView==='pending'?'audited':'pending';$('toggleAudited').textContent=auditionView==='pending'?'AUDITADOS':'VER PENDENTES';render()});
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}const api=(path,opt={})=>requestJSON(path,opt)
async function load(){try{const [c,s,a]=await Promise.all([api('/api/candidates'),api('/api/scores'),api('/api/arrivals')]);candidates=c.candidates||[];scores=s.scores||{};arrivals=a.arrivals||{};serverAvailable=true;$('connection').textContent='Conectado ao notebook. As notas são compartilhadas com a Central.';$('connection').className='status ok';render();updatePendingQueueUi();return true}catch(e){serverAvailable=false;$('connection').textContent='Erro de conexão: '+e.message;$('connection').className='status';updatePendingQueueUi();return false}}function getScore(id){return (scores[String(id)]||{})[$('evaluator').value.trim()]||{}}
function draftKey(id,evaluator=$('evaluator').value.trim()){return 'uesp_draft_'+evaluator.toLocaleLowerCase('pt-BR')+'_'+id}
function getDraft(id,evaluator=$('evaluator').value.trim()){try{return JSON.parse(localStorage.getItem(draftKey(id,evaluator))||'{}')}catch(e){return {}}}
function saveDraft(id,evaluator=$('evaluator').value.trim()){
 const values={communication:$('c'+id)?.value||'',samba:$('s'+id)?.value||''};
 try{localStorage.setItem(draftKey(id,evaluator),JSON.stringify(values))}catch(e){return false}
 const alreadyQueued=pendingQueue().some(item=>pendingMatch(item,'audition',id,'both',evaluator));
 if((!navigator.onLine||!serverAvailable||alreadyQueued)&&(values.communication||values.samba)){
  if(!queuePendingScore('audition',id,'both',evaluator,{...values,allow_partial:false}))updatePendingQueueUi('Não foi possível guardar a nota offline neste tablet. Verifique o espaço disponível no armazenamento do navegador.');
  else if(navigator.onLine&&serverAvailable)syncPendingScores();
 }
 return true;
}
function scoringDraftKey(stage,id,criterion,evaluator=$('evaluator').value.trim()){return 'uesp_scoring_draft_'+stage+'_'+encodeURIComponent(evaluator.toLocaleLowerCase('pt-BR'))+'_'+id+'_'+criterion}
function getScoringDraft(stage,id,criterion,evaluator=$('evaluator').value.trim()){try{return localStorage.getItem(scoringDraftKey(stage,id,criterion,evaluator))}catch(e){return null}}
function setScoringDraft(stage,id,criterion,value,evaluator=$('evaluator').value.trim()){try{localStorage.setItem(scoringDraftKey(stage,id,criterion,evaluator),String(value));return true}catch(e){return false}}
function clearScoringDraft(stage,id,criterion,evaluator=$('evaluator').value.trim()){try{localStorage.removeItem(scoringDraftKey(stage,id,criterion,evaluator))}catch(e){}}
let serverAvailable=navigator.onLine,syncInFlight=false,syncAgainRequested=false,retryTimer=null,retryDelay=5000;
function setConnectedStatus(){
 const message=mode==='audition'?'Conectado ao notebook. As notas são compartilhadas com a Central.':mode==='contest'?'Conectado ao notebook. A lista mostra participantes com chegada registrada pela Recepção.':'Conectado. Notas e avaliadores do Agulha de Ouro são armazenados separadamente.';
 $('connection').textContent=message;$('connection').className='status ok';
}
function pendingQueue(){return window.uespOfflineScoreQueue?.list()||[]}
function pendingMatch(entry,stage,id,criterion,evaluator){return entry.stage===stage&&String(entry.id)===String(id)&&entry.criterion===criterion&&entry.evaluator===evaluator}
function candidateForStage(stage,id){const rows=stage==='audition'?candidates:stage==='contest'?contestCandidates:agulhaResults;return rows.find(item=>String(item.id)===String(id))}
function queuePendingScore(stage,id,criterion,evaluator,values={}){
 const candidate=candidateForStage(stage,id);if(!candidate||!evaluator)return null;
 const entry=window.uespOfflineScoreQueue?.enqueue({stage,id:Number(id),criterion,evaluator,name:candidate.name,category:candidate.category,...values})||null;
 updatePendingQueueUi();return entry;
}
function removePendingByValues(stage,id,criterion,evaluator,values){
 const entry=pendingQueue().find(item=>pendingMatch(item,stage,id,criterion,evaluator));
 if(!entry)return;
 const keys=Object.keys(values);
 if(keys.every(key=>String(entry[key]??'')===String(values[key]??'')))window.uespOfflineScoreQueue.remove(entry);
 updatePendingQueueUi();
}
function clearAuditionDraftIfSame(id,evaluator,values){
 const stored=getDraft(id,evaluator);
 if(String(stored.communication||'')===String(values.communication||'')&&String(stored.samba||'')===String(values.samba||'')){
  try{localStorage.removeItem(draftKey(id,evaluator))}catch(e){}
 }
}
function clearScoringDraftIfSame(stage,id,criterion,evaluator,value){
 if(String(getScoringDraft(stage,id,criterion,evaluator)??'')===String(value??''))clearScoringDraft(stage,id,criterion,evaluator);
}
function updatePendingQueueUi(message=''){
 const queue=pendingQueue(),status=$('offlineSyncStatus'),button=$('syncPendingScores');
 if(!status||!button)return;
 button.hidden=!queue.length;button.disabled=syncInFlight||!navigator.onLine;
 status.hidden=!queue.length&&!message;
 if(message){status.textContent=message;return}
 if(!queue.length){status.textContent='';return}
 const incomplete=queue.filter(item=>item.stage==='audition'&&!item.allow_partial&&(!item.communication||!item.samba)).length;
 status.textContent=serverAvailable?`${queue.length} rascunho(s) neste tablet aguardando sincronização.${incomplete?' Complete Comunicação e Samba para enviar automaticamente.':''}`:`${queue.length} rascunho(s) guardado(s) neste tablet. Serão enviados quando a conexão com a Central voltar.${incomplete?' Complete Comunicação e Samba para envio automático.':''}`;
}
async function savePendingEntry(entry){
 if(entry.stage==='audition'){
  if(!entry.communication&&!entry.samba)return false;
  if((!entry.communication||!entry.samba)&&!entry.allow_partial)return false;
  await api('/api/score',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidate_id:Number(entry.id),evaluator:entry.evaluator,communication:entry.communication?String(entry.communication).replace(',','.'):null,samba:entry.samba?String(entry.samba).replace(',','.'):null})});
  if(!scores[String(entry.id)])scores[String(entry.id)]={};
  scores[String(entry.id)][entry.evaluator]={communication:entry.communication?Number(String(entry.communication).replace(',','.')):null,samba:entry.samba?Number(String(entry.samba).replace(',','.')):null};
  clearAuditionDraftIfSame(entry.id,entry.evaluator,entry);removePendingByValues('audition',entry.id,'both',entry.evaluator,{communication:entry.communication,samba:entry.samba});
 }else if(entry.stage==='contest'){
  if(!entry.value)return false;
  await api('/api/contest-score',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidate_id:Number(entry.id),evaluator:entry.evaluator,[entry.criterion]:entry.value})});
  if(!contestScores[String(entry.id)])contestScores[String(entry.id)]={};
  if(!contestScores[String(entry.id)][entry.evaluator])contestScores[String(entry.id)][entry.evaluator]={};
  contestScores[String(entry.id)][entry.evaluator][entry.criterion]=Number(entry.value);
  clearScoringDraftIfSame('contest',entry.id,entry.criterion,entry.evaluator,entry.value);removePendingByValues('contest',entry.id,entry.criterion,entry.evaluator,{value:entry.value});
 }else if(entry.stage==='agulha'){
  if(!entry.value)return false;
  await api('/api/agulha/score',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidate_id:Number(entry.id),evaluator:entry.evaluator,score:entry.value})});
  clearScoringDraftIfSame('agulha',entry.id,'score',entry.evaluator,entry.value);removePendingByValues('agulha',entry.id,'score',entry.evaluator,{value:entry.value});
  await loadAgulha();
 }
 return true;
}
async function syncPendingScores(){
 if(syncInFlight){syncAgainRequested=true;return}
 if(!navigator.onLine)return;
 const initial=pendingQueue();if(!initial.length){updatePendingQueueUi();return}
 syncInFlight=true;updatePendingQueueUi(`${initial.length} rascunho(s) aguardando sincronização…`);
 let sent=0,conflicts=0,failed=null,retry=false;
 try{
  await api('/api/active-stage');
  const stages=new Set(initial.map(item=>item.stage)),loaded=[];
  if(stages.has('audition'))loaded.push(await load());
  if(stages.has('contest'))loaded.push(await loadContest());
  if(stages.has('agulha'))loaded.push(await loadAgulha());
  serverAvailable=loaded.every(Boolean);
  if(!serverAvailable)throw new TypeError('A Central ainda não está disponível.');
  setConnectedStatus();
  for(const entry of pendingQueue()){
   const candidate=candidateForStage(entry.stage,entry.id);
   if(!candidate||candidate.name!==entry.name||candidate.category!==entry.category){conflicts++;continue}
   try{if(await savePendingEntry(entry))sent++}
   catch(e){failed=e;if(!e.status||e.status>=500){retry=true;serverAvailable=false;break}}
  }
 }catch(e){failed=e;if(!e.status||e.status>=500){retry=true;serverAvailable=false}}
 finally{
  syncInFlight=false;
  const runAgain=syncAgainRequested;syncAgainRequested=false;
  if(retry){clearTimeout(retryTimer);retryTimer=setTimeout(()=>{retryDelay=Math.min(retryDelay*2,30000);probeAndSyncPendingScores()},retryDelay)}else if(!failed)retryDelay=5000;
  if(sent&&mode==='audition')render();else if(sent&&mode==='contest')renderContest();
  if(failed)updatePendingQueueUi(`Não foi possível enviar todas as notas: ${failed.message}. Os rascunhos continuam neste tablet.`);
  else if(conflicts)updatePendingQueueUi(`${conflicts} rascunho(s) não enviado(s): a lista atual não corresponde à lista em que as notas foram feitas. Confira antes de reenviar.`);
  else if(pendingQueue().length)updatePendingQueueUi();
  else updatePendingQueueUi(sent?`${sent} nota(s) sincronizada(s) com a Central.`:'');
  if(runAgain&&!retry)setTimeout(syncPendingScores,0);
 }
}
async function probeAndSyncPendingScores(){
 if(!navigator.onLine){serverAvailable=false;updatePendingQueueUi();return}
 try{await api('/api/active-stage');serverAvailable=true;await syncPendingScores()}
 catch(e){serverAvailable=false;updatePendingQueueUi(e.status===401||e.status===403?'A sessão expirou ou não tem autorização. Entre novamente para enviar as notas pendentes.':'Sem conexão com a Central. As notas continuam guardadas neste tablet.');if(!e.status||e.status>=500){clearTimeout(retryTimer);retryTimer=setTimeout(()=>probeAndSyncPendingScores(),retryDelay)}}
}
function schedulePendingSyncRetry(){clearTimeout(retryTimer);retryTimer=setTimeout(()=>{retryDelay=Math.min(retryDelay*2,30000);probeAndSyncPendingScores()},retryDelay)}
window.addEventListener('offline',()=>{document.getElementById('connection').textContent='Sem conexão com a Central. As notas selecionadas ficam guardadas neste tablet.';document.getElementById('connection').className='status';serverAvailable=false;updatePendingQueueUi()});
window.addEventListener('online',probeAndSyncPendingScores);
$('syncPendingScores').addEventListener('click',probeAndSyncPendingScores);
window.addEventListener('storage',event=>{if(event.key==='uesp_pending_score_sync'){updatePendingQueueUi();if(navigator.onLine)probeAndSyncPendingScores()}});
function categoryBadge(value){const n=String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();if(n.includes('rainha'))return '<div class="category-highlight cat-rainha">RAINHA DO SAMBA 👑</div>';if(n.includes('diva'))return '<div class="category-highlight cat-diva">DIVA DO SAMBA (PLUS SIZE) 👑</div>';if(n.includes('passista'))return '<div class="category-highlight cat-passista">PASSISTA DE OURO 🎩</div>';return '<div class="category-highlight">'+esc(value)+'</div>'}
function render(){const q=$('search').value.trim().toLocaleLowerCase('pt-BR');const norm=v=>String(v??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/\s+/g,' ').trim().toLocaleLowerCase('pt-BR');const arrivedRows=candidates.filter(c=>{const a=arrivals[String(c.id)];return !!a&&String(a.status||'PRESENTE').toUpperCase()!=='AUSENTE'&&norm(c.name).includes(norm(q))}).sort((a,b)=>String(arrivals[String(a.id)]?.arrived_at||'').localeCompare(String(arrivals[String(b.id)]?.arrived_at||'')));const isAudited=c=>getScore(c.id).communication!=null&&getScore(c.id).samba!=null&&!pendingQueue().some(item=>pendingMatch(item,'audition',c.id,'both',$('evaluator').value.trim()));const rows=arrivedRows.filter(c=>auditionView==='audited'?isAudited(c):!isAudited(c));const done=arrivedRows.filter(isAudited).length;$('progressText').textContent=auditionView==='pending'?`${rows.length} participantes aguardando avaliação; ${done} já auditados`:`${rows.length} participantes já auditados — selecione as notas para corrigir se necessário`;$('bar').style.width=(rows.length?100*done/rows.length:0)+'%';$('list').innerHTML=rows.length?rows.map(c=>{const s=getScore(c.id),sum=s.communication!=null&&s.samba!=null?(Number(s.communication)+Number(s.samba)).toFixed(1).replace('.',','):'—';const evaluated=s.communication!=null&&s.samba!=null;return `<article class="candidate ${evaluated?'evaluated':''}"><div class="candidate-layout"><div>${c.photo?`<img class="candidate-photo" src="${String(c.photo).replace(/"/g,'&quot;')}" alt="Foto de ${esc(c.name)}" loading="lazy">`:`<div class="candidate-photo-placeholder">Foto não cadastrada</div>`}</div><div class="candidate-info"><h3>${esc(c.name)}</h3>${categoryBadge(c.category)}<div>${evaluated?'<span class=\"evaluated-badge\">✓ AVALIADA — NOTAS SALVAS</span>':'<span class=\"draft-badge\">PENDENTE DE SALVAR</span>'}</div><p class="sum">Total deste avaliador: ${sum}</p><div class="grid"><div><label for="c${c.id}">Comunicação</label><select id="c${c.id}"><option value="">— Selecione —</option><option value="9,0">9,0</option><option value="9,1">9,1</option><option value="9,2">9,2</option><option value="9,3">9,3</option><option value="9,4">9,4</option><option value="9,5">9,5</option><option value="9,6">9,6</option><option value="9,7">9,7</option><option value="9,8">9,8</option><option value="9,9">9,9</option><option value="10,0">10,0</option></select></div><div><label for="s${c.id}">Samba</label><select id="s${c.id}"><option value="">— Selecione —</option><option value="9,0">9,0</option><option value="9,1">9,1</option><option value="9,2">9,2</option><option value="9,3">9,3</option><option value="9,4">9,4</option><option value="9,5">9,5</option><option value="9,6">9,6</option><option value="9,7">9,7</option><option value="9,8">9,8</option><option value="9,9">9,9</option><option value="10,0">10,0</option></select></div></div><div class="tools" style="margin-top:10px"><button data-save="${c.id}">Salvar notas</button><span id="m${c.id}" class="sub">Notas não alteradas</span></div></div></div></article>`}).join(''):(auditionView==='pending'?'<div class="empty">Nenhum participante pendente. Use AUDITADOS para consultar ou alterar notas já salvas.</div>':'<div class="empty">Nenhum participante auditado encontrado.</div>');for(const c of rows){const s=getScore(c.id);$(`c${c.id}`).innerHTML='<option value="">— Selecione —</option><option value="9,0">9,0</option><option value="9,1">9,1</option><option value="9,2">9,2</option><option value="9,3">9,3</option><option value="9,4">9,4</option><option value="9,5">9,5</option><option value="9,6">9,6</option><option value="9,7">9,7</option><option value="9,8">9,8</option><option value="9,9">9,9</option><option value="10,0">10,0</option>';$(`s${c.id}`).innerHTML='<option value="">— Selecione —</option><option value="9,0">9,0</option><option value="9,1">9,1</option><option value="9,2">9,2</option><option value="9,3">9,3</option><option value="9,4">9,4</option><option value="9,5">9,5</option><option value="9,6">9,6</option><option value="9,7">9,7</option><option value="9,8">9,8</option><option value="9,9">9,9</option><option value="10,0">10,0</option>';const localDraft=getDraft(c.id),queued=pendingQueue().find(item=>pendingMatch(item,'audition',c.id,'both',$('evaluator').value.trim()));$(`c${c.id}`).value=queued?queued.communication:(s.communication==null?(localDraft.communication||''):Number(s.communication).toFixed(1));$(`s${c.id}`).value=queued?queued.samba:(s.samba==null?(localDraft.samba||''):Number(s.samba).toFixed(1));[$(`c${c.id}`),$(`s${c.id}`)].forEach(el=>el.addEventListener('change',()=>saveDraft(c.id)))}document.querySelectorAll('[data-save]').forEach(b=>b.addEventListener('click',()=>save(Number(b.dataset.save),b)))}
async function save(id,b){
 const evaluator=$('evaluator').value.trim();if(!evaluator){alert('Informe o nome do avaliador antes de salvar.');$('evaluator').focus();return}
 const communication=$('c'+id).value,samba=$('s'+id).value,allowPartial=!communication||!samba;
 if(allowPartial&&!confirm('Há uma nota em branco. Deseja salvar mesmo assim?'))return;
 const values={communication,samba};try{localStorage.setItem(draftKey(id,evaluator),JSON.stringify(values))}catch(e){}b.disabled=true;$('m'+id).textContent='Salvando…';
 try{
  await api('/api/score',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidate_id:id,evaluator,communication:communication?communication.replace(',','.'):null,samba:samba?samba.replace(',','.'):null})});
  if(!scores[String(id)])scores[String(id)]={};scores[String(id)][evaluator]={communication:communication?Number(communication.replace(',','.')):null,samba:samba?Number(samba.replace(',','.')):null};
  clearAuditionDraftIfSame(id,evaluator,values);removePendingByValues('audition',id,'both',evaluator,values);render();$('connection').textContent='Notas salvas no servidor. Você pode continuar para a próxima participante.';
 }catch(e){
  const latest=getDraft(id,evaluator),queued=queuePendingScore('audition',id,'both',evaluator,{...latest,allow_partial:allowPartial&&latest.communication===communication&&latest.samba===samba});
  $('m'+id).textContent=queued?'Falha de conexão. Rascunho mantido neste tablet e será reenviado automaticamente.':'Falha ao salvar: '+e.message;
  if(!e.status||e.status>=500){serverAvailable=false;schedulePendingSyncRetry()}
  updatePendingQueueUi(queued?`Nota de ${$('connection').textContent.includes('Agulha')?'Agulha de Ouro':mode==='contest'?'Concurso':'Audição'} guardada neste tablet e aguardando a Central.`:'Não foi possível guardar a nota pendente neste tablet.');
 }finally{b.disabled=false}
}load();
async function loadAgulha(){try{const j=await api('/api/agulha/data');agulhaResults=j.results||[];serverAvailable=true;$('connection').className='status ok';$('connection').textContent='Conectado. Notas e avaliadores do Agulha de Ouro são armazenados separadamente.';renderAgulha();updatePendingQueueUi();return true}catch(e){serverAvailable=false;$('agulhaList').innerHTML='<div class="empty">Não foi possível carregar as candidatas elegíveis: '+esc(e.message)+'</div>';updatePendingQueueUi();return false}}
function renderAgulha(){if(mode!=='agulha')return;const evaluator=$('evaluator').value.trim(),q=$('search').value.trim().toLocaleLowerCase('pt-BR'),norm=v=>String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('pt-BR');const eligible=agulhaResults.filter(c=>norm(c.name).includes(norm(q)));const done=eligible.filter(c=>c.scores&&c.scores[evaluator]!=null);const rows=eligible.filter(c=>c.tied_for_first||getScoringDraft('agulha',c.id,'score',evaluator)!==null||(agulhaView==='evaluated'?(c.scores&&c.scores[evaluator]!=null):!(c.scores&&c.scores[evaluator]!=null)));$('toggleAgulhaEvaluated').textContent=agulhaView==='pending'?'JÁ AVALIADAS':'VER PENDENTES';$('toggleAgulhaEvaluated').classList.toggle('active',agulhaView==='evaluated');$('agulhaProgress').textContent=evaluator?done.length+' de '+eligible.length+' candidatas avaliadas por '+evaluator+'.':'Selecione seu nome na lista de avaliadores.';const scoreOptions='<option value="">— Selecione a nota —</option>'+Array.from({length:11},(_,i)=>{const n=(9+i/10).toFixed(1);return '<option value="'+n+'">'+n.replace('.',',')+'</option>'}).join('');$('agulhaList').innerHTML=rows.length?rows.map(c=>{const savedValue=c.scores?c.scores[evaluator]:null,draftValue=getScoringDraft('agulha',c.id,'score',evaluator),value=draftValue??savedValue;return '<article class="candidate '+(savedValue!=null&&draftValue===null?'evaluated':'')+'"><div class="candidate-layout"><div>'+(c.photo?'<img class="candidate-photo" src="'+String(c.photo).replace(/"/g,'&quot;')+'" alt="Foto de '+esc(c.name)+'" loading="lazy">':'<div class="candidate-photo-placeholder">Foto não cadastrada</div>')+'</div><div class="candidate-info"><h3>'+esc(c.name)+'</h3>'+categoryBadge(c.category)+(c.tied_for_first?'<div class="draft-badge">EMPATE GERAL EM 1º — REAVALIE/EDITE ESTA NOTA ATÉ HAVER UMA VENCEDORA</div>':'')+'<div>'+(draftValue!==null?'<span class="draft-badge">RASCUNHO LOCAL — AINDA NÃO ENVIADO</span>':(savedValue!=null?'<span class="evaluated-badge">✓ NOTA SALVA — EDITÁVEL</span>':'<span class="draft-badge">PENDENTE DE AVALIAÇÃO</span>'))+'</div><div class="contest-criteria"><label for="agulhaScore'+c.id+'">Vestido / roupa</label><select id="agulhaScore'+c.id+'">'+scoreOptions+'</select></div><div class="tools" style="margin-top:10px;flex-wrap:wrap"><button type="button" data-agulha-save="'+c.id+'">'+(c.tied_for_first&&value!=null?'Reavaliar nota':'Salvar nota')+'</button><span id="am'+c.id+'" class="sub">Nota independente do Concurso</span></div></div></div></article>'}).join(''):(agulhaView==='pending'?'<div class="empty">Nenhuma candidata pendente. Use JÁ AVALIADAS para consultar ou editar notas salvas.</div>':'<div class="empty">Nenhuma avaliação encontrada.</div>');for(const c of rows){const saved=c.scores?c.scores[evaluator]:null,draft=getScoringDraft('agulha',c.id,'score',evaluator),v=draft??saved;if(v!=null)$('agulhaScore'+c.id).value=Number(v).toFixed(1);$('agulhaScore'+c.id).addEventListener('change',()=>{const value=$('agulhaScore'+c.id).value,queued=pendingQueue().some(item=>pendingMatch(item,'agulha',c.id,'score',evaluator));if(!setScoringDraft('agulha',c.id,'score',value,evaluator))$('am'+c.id).textContent='Não foi possível guardar o rascunho neste dispositivo.';else{$('am'+c.id).textContent='Rascunho local neste tablet.';if((!navigator.onLine||!serverAvailable||queued)&&value){if(!queuePendingScore('agulha',c.id,'score',evaluator,{value}))updatePendingQueueUi('Não foi possível guardar a nota pendente neste tablet.');else if(navigator.onLine&&serverAvailable)syncPendingScores()}}})}document.querySelectorAll('[data-agulha-save]').forEach(b=>b.addEventListener('click',()=>saveAgulha(Number(b.dataset.agulhaSave),b)))}
async function saveAgulha(id,b){
 const evaluator=$('evaluator').value.trim(),score=$('agulhaScore'+id)?.value;if(!evaluator){alert('Selecione o avaliador do Agulha de Ouro antes de salvar.');$('evaluator').focus();return}if(!score){alert('Selecione uma nota para vestido/roupa.');return}
 setScoringDraft('agulha',id,'score',score,evaluator);b.disabled=true;$('am'+id).textContent='Salvando nota independente…';
 try{
  const result=await api('/api/agulha/score',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidate_id:id,evaluator,score})});
  clearScoringDraftIfSame('agulha',id,'score',evaluator,score);removePendingByValues('agulha',id,'score',evaluator,{value:score});
  if(result.results)agulhaResults=result.results;else await loadAgulha();serverAvailable=true;renderAgulha();$('connection').textContent='Nota do Agulha de Ouro salva no servidor.';
 }catch(e){
  const latest=getScoringDraft('agulha',id,'score',evaluator)??score,queued=queuePendingScore('agulha',id,'score',evaluator,{value:latest});
  $('am'+id).textContent=queued?'Falha de conexão. Nota mantida neste tablet e será reenviada automaticamente.':'Erro: '+e.message;
  if(!e.status||e.status>=500){serverAvailable=false;schedulePendingSyncRetry()}
  updatePendingQueueUi(queued?'Nota do Agulha de Ouro guardada neste tablet e aguardando a Central.':'Não foi possível guardar a nota pendente neste tablet.');
 }finally{b.disabled=false}
}
$('toggleAgulhaEvaluated').addEventListener('click',()=>{agulhaView=agulhaView==='pending'?'evaluated':'pending';renderAgulha()});
document.getElementById('modeAudition').addEventListener('click',()=>setMode('audition'));
document.getElementById('modeContest').addEventListener('click',()=>setMode('contest'));
document.getElementById('modeAgulha').addEventListener('click',()=>setMode('agulha'));
async function setMode(next){mode=next;const audition=next==='audition',contest=next==='contest',agulha=next==='agulha';$('stageHeading').textContent=(audition?'AUDIÇÃO':contest?'CONCURSO':'AGULHA DE OURO')+' MISS UESP • CARNAVAL 2027';$('evaluatorHeading').textContent='Área do Avaliador(a) — '+(audition?'Audição':contest?'Concurso':'Agulha de Ouro');$('auditionMode').style.display=audition?'block':'none';$('contestMode').style.display=contest?'block':'none';$('agulhaMode').style.display=agulha?'block':'none';$('auditionProgress').style.display=audition?'block':'none';$('progressText').style.display=audition?'block':'none';$('search').placeholder=audition?'Digite parte do nome':'Use a busca para localizar participantes';for(const [id,active] of [['modeAudition',audition],['modeContest',contest],['modeAgulha',agulha]]){$(id).classList.toggle('active',active);$(id).classList.toggle('secondary',!active)}await loadEvaluatorRoster();if(audition){$('connection').textContent='Conectado ao notebook. As notas são compartilhadas com a Central.';render()}else if(contest){loadContest()}else{loadAgulha()}}
async function syncCentralStage(){
 const wasAvailable=serverAvailable;
 try{
  const r=await fetch('/api/active-stage?ts='+Date.now(),{cache:'no-store'});
  if(r.status===401){serverAvailable=false;updatePendingQueueUi('A sessão expirou. Entre novamente para enviar as notas pendentes.');return}
  if(!r.ok){serverAvailable=false;updatePendingQueueUi();return}
  const j=await r.json(),active=String(j.stage||'AUDICAO').toUpperCase(),next=active==='CONCURSO'?'contest':'audition';serverAvailable=true;
  if(mode!=='agulha'&&next!==mode)await setMode(next);
  if(!wasAvailable&&pendingQueue().length)probeAndSyncPendingScores();
 }catch(e){serverAvailable=false;updatePendingQueueUi()}
}
window.addEventListener('storage',e=>{if(e.key==='uesp_active_stage')syncCentralStage()});
// Poll as a fallback so this page honors the Central even after reloads or missed storage events.
syncCentralStage();setInterval(()=>{if(document.visibilityState==='visible')syncCentralStage()},5000);
window.addEventListener('focus',syncCentralStage);
$('toggleContestEvaluated').addEventListener('click',()=>{contestView=contestView==='pending'?'evaluated':'pending';renderContest()});document.querySelectorAll('[data-contest-criterion]').forEach(b=>b.addEventListener('click',async()=>{contestCriterion=b.dataset.contestCriterion;document.querySelectorAll('[data-contest-criterion]').forEach(x=>x.classList.toggle('active',x===b));$('contestList').innerHTML='<div class="empty">Atualizando participantes…</div>';await loadContest()}));
async function loadContest(){try{const [j,a]=await Promise.all([api('/api/contest-candidates'),api('/api/arrivals')]);arrivals=a.arrivals||{};contestCandidates=(j.candidates||[]).filter(x=>{const a=arrivals[String(x.id)];return !!(a&&a.arrived_at)&&String(a.status||'PRESENTE').toUpperCase()!=='AUSENTE'}).sort((x,y)=>{const ax=arrivals[String(x.id)],ay=arrivals[String(y.id)];return String(ax.arrived_at).localeCompare(String(ay.arrived_at))||(Number(x.position||9999)-Number(y.position||9999))||String(x.name||'').localeCompare(String(y.name||''),'pt-BR')});contestScores=j.scores||{};serverAvailable=true;$('connection').className='status ok';$('connection').textContent='Conectado ao notebook. A lista mostra somente participantes com chegada registrada pela Recepção, em ordem de chegada.';renderContest();updatePendingQueueUi();return true}catch(e){serverAvailable=false;$('contestList').innerHTML='<div class="empty">Não foi possível carregar os classificados do Concurso: '+esc(e.message)+'. Confira se o servidor atualizado está em execução e se a migração dos 25 classificados foi concluída.</div>';$('contestProgress').textContent='Falha ao carregar classificados.';updatePendingQueueUi();return false}}
function getContestScore(id){return (contestScores[String(id)]||{})[$('evaluator').value.trim()]||{}}
function renderContest(){if(mode!=='contest')return;const q=$('search').value.trim().toLocaleLowerCase('pt-BR');const norm=v=>String(v??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('pt-BR');const categoryKey=v=>norm(v).replace(/[()]/g,'').replace(/\s+/g,' ').trim();const categoryOf=c=>categoryKey([c.category,c.modalidade,c.categoria].filter(Boolean).join(' '));const aesthetics=contestCriterion==='aesthetics_sympathy';const isRainhaDiva=c=>{const k=categoryOf(c);return /rainha/.test(k)||/diva/.test(k)||/plus\s*size/.test(k)};const isPassistaRainhaDiva=c=>{const k=categoryOf(c);return /passista/.test(k)||/rainha/.test(k)||/diva/.test(k)||/plus\\s*size/.test(k)};const eligibleRows=contestCandidates.filter(c=>(aesthetics?isRainhaDiva(c):isPassistaRainhaDiva(c))&&norm(c.name).includes(norm(q))).sort((a,b)=>String(arrivals[String(a.id)]?.arrived_at||'').localeCompare(String(arrivals[String(b.id)]?.arrived_at||'')));const field=contestCriterion;const done=eligibleRows.filter(c=>getContestScore(c.id)[field]!=null&&getContestScore(c.id)[field]!=='').length;const rows=eligibleRows.filter(c=>{const saved=getContestScore(c.id)[field],draft=getScoringDraft('contest',c.id,field);return draft!==null||(contestView==='evaluated'?(saved!=null&&saved!==''):(saved==null||saved===''))});const toggle=$('toggleContestEvaluated');toggle.textContent=contestView==='pending'?'JÁ AVALIADAS':'VER PENDENTES';toggle.classList.toggle('active',contestView==='evaluated');$('contestProgress').textContent=`${done} de ${eligibleRows.length} participantes avaliadas neste critério.`;$('contestCriteria').textContent=contestCriterion==='aesthetics_sympathy'?'Estética Corporal + Simpatia — Rainhas e Divas do Samba (Plus Size).':contestCriterion==='communication_elegance'?'Comunicação + Elegância — Passistas, Rainhas e Divas do Samba (Plus Size).':'Samba no Pé — Passistas, Rainhas e Divas do Samba (Plus Size).';const label=contestCriterion==='aesthetics_sympathy'?'Estética Corporal + Simpatia':contestCriterion==='communication_elegance'?'Comunicação + Elegância':'Samba no Pé';$('contestList').innerHTML=rows.length?rows.map(c=>{const v=getContestScore(c.id),draftValue=getScoringDraft('contest',c.id,field),value=draftValue??v[field],complete=v[field]!=null&&draftValue===null;return `<article class="candidate ${complete?'evaluated':''}"><div class="candidate-layout"><div>${c.photo?`<img class="candidate-photo" src="${String(c.photo).replace(/"/g,'&quot;')}" alt="Foto de ${esc(c.name)}" loading="lazy">`:`<div class="candidate-photo-placeholder">Foto não cadastrada</div>`}</div><div class="candidate-info"><h3>${esc(c.name)}</h3>${c.artistic_name?`<div class="sub"><strong>Nome artístico:</strong> ${esc(c.artistic_name)}</div>`:'<div class="sub">Nome artístico não cadastrado</div>'}<div class="sub">Dados da Audição disponíveis</div>${categoryBadge(c.category)}${draftValue!==null?'<span class="draft-badge">RASCUNHO LOCAL — AINDA NÃO ENVIADO</span>':(complete?'<span class="evaluated-badge">✓ CRITÉRIO SALVO</span>':'<span class="draft-badge">PENDENTE DE SALVAR</span>')}<div class="contest-criteria"><label for="score${c.id}">${label}</label><select id="score${c.id}">${contestScoreOptions}</select></div><div class="tools" style="margin-top:10px;flex-wrap:wrap"><button type="button" data-contest-save="${c.id}" data-criterion="${field}">Salvar ${label}</button><span id="cm${c.id}" class="sub"></span></div></div></div></article>`}).join(''):'<div class="empty">Nenhum participante correspondente encontrado nesta lista.</div>';for(const c of rows){const v=getContestScore(c.id),draft=getScoringDraft('contest',c.id,field),value=draft??v[field];$('score'+c.id).value=value==null?'':Number(value).toFixed(1);$('score'+c.id).addEventListener('change',()=>{const value=$('score'+c.id).value,evaluator=$('evaluator').value.trim(),queued=pendingQueue().some(item=>pendingMatch(item,'contest',c.id,field,evaluator));if(!setScoringDraft('contest',c.id,field,value,evaluator))$('cm'+c.id).textContent='Não foi possível guardar o rascunho neste dispositivo.';else{$('cm'+c.id).textContent='Rascunho local neste tablet.';if((!navigator.onLine||!serverAvailable||queued)&&value){if(!queuePendingScore('contest',c.id,field,evaluator,{value}))updatePendingQueueUi('Não foi possível guardar a nota pendente neste tablet.');else if(navigator.onLine&&serverAvailable)syncPendingScores()}}})}document.querySelectorAll('[data-contest-save]').forEach(b=>b.addEventListener('click',()=>saveContest(Number(b.dataset.contestSave),b.dataset.criterion,b)))}
async function saveContest(id,criterion,b){
 const evaluator=$('evaluator').value.trim();if(!evaluator){alert('Informe o nome do avaliador(a) antes de salvar.');$('evaluator').focus();return}
 const value=$('score'+id)?.value;if(value==null||value===''){alert('Selecione uma nota para este critério.');return}
 setScoringDraft('contest',id,criterion,value,evaluator);b.disabled=true;$('cm'+id).textContent='Salvando critério…';
 try{
  await api('/api/contest-score',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidate_id:id,evaluator,[criterion]:value})});
  clearScoringDraftIfSame('contest',id,criterion,evaluator,value);removePendingByValues('contest',id,criterion,evaluator,{value});
  if(!contestScores[String(id)])contestScores[String(id)]={};if(!contestScores[String(id)][evaluator])contestScores[String(id)][evaluator]={};contestScores[String(id)][evaluator][criterion]=Number(value);
  serverAvailable=true;renderContest();$('connection').textContent='Critério salvo no servidor. Você pode continuar para a próxima participante.';
 }catch(e){
  const latest=getScoringDraft('contest',id,criterion,evaluator)??value,queued=queuePendingScore('contest',id,criterion,evaluator,{value:latest});
  $('cm'+id).textContent=queued?'Falha de conexão. Nota mantida neste tablet e será reenviada automaticamente.':'Erro ao salvar: '+e.message;
  if(!e.status||e.status>=500){serverAvailable=false;schedulePendingSyncRetry()}
  updatePendingQueueUi(queued?'Nota do Concurso guardada neste tablet e aguardando a Central.':'Não foi possível guardar a nota pendente neste tablet.');
 }finally{b.disabled=false}
}
if(mode==='agulha')setMode('agulha');else{loadEvaluatorRoster();load();if(mode==='contest')setMode('contest')}
updatePendingQueueUi();if(pendingQueue().length&&navigator.onLine)setTimeout(probeAndSyncPendingScores,500);
window.addEventListener('focus',()=>{if(pendingQueue().length)probeAndSyncPendingScores()});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'&&pendingQueue().length)probeAndSyncPendingScores()});
// A lista do Concurso não é recarregada automaticamente durante a digitação para preservar a seleção das notas e a visualização de JÁ AVALIADAS.
// Para atualizar os dados, troque de critério/etapa ou recarregue a página quando não houver notas em edição.
