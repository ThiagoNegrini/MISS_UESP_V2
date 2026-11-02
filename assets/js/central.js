
let previewRows=[];
let auditionCandidates=[];
let auditionArrivalData={};
let contestArrivalData={};
let auditionScores={};
let contestScores={};
let evaluatorRoster=[];
let contestEvaluatorRoster=[];
let contestCandidates=[];
let evaluatorSyncReports=[];
let agulhaProgressData={evaluators:[],results:[]};
const $=id=>document.getElementById(id);
const api=(path,options={})=>requestJSON(path,options)
async function loadRoster(){try{const stage=$('rosterStage').value;const j=await api('/api/evaluators?stage='+stage);$('rosterNames').value=(j.evaluators||[]).join('\n');$('rosterStatus').textContent='Lista '+stage+' carregada ('+(j.evaluators||[]).length+' avaliador(es)).'}catch(e){$('rosterStatus').textContent='Falha ao carregar lista: '+e.message}}
$('loadRoster').addEventListener('click',loadRoster);$('rosterStage').addEventListener('change',loadRoster);$('saveRoster').addEventListener('click',async()=>{try{const stage=$('rosterStage').value,evaluators=$('rosterNames').value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);const j=await api('/api/evaluators',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({stage,evaluators})});$('rosterNames').value=j.evaluators.join('\n');$('rosterStatus').textContent='Lista '+stage+' salva: '+j.evaluators.length+' avaliador(es).'}catch(e){$('rosterStatus').textContent='Falha ao salvar: '+e.message}});loadRoster();
let refreshInFlight=false;
async function refresh(){
 if(refreshInFlight||document.visibilityState==='hidden')return;
 refreshInFlight=true;
 try{
   const loaded=await Promise.allSettled([api('/api/arrival-candidates'),api('/api/candidates'),api('/api/arrivals?stage=AUDICAO'),api('/api/arrivals?stage=CONCURSO'),api('/api/scores'),api('/api/evaluators?stage=AUDICAO'),api('/api/contest-candidates'),api('/api/evaluators?stage=CONCURSO'),api('/api/evaluator-sync-status'),api('/api/agulha/data')]);
   const values=loaded.map(result=>result.status==='fulfilled'?result.value:null),errors=loaded.map((result,index)=>result.status==='rejected'?`/api/${['arrival-candidates','candidates','arrivals?stage=AUDICAO','arrivals?stage=CONCURSO','scores','evaluators?stage=AUDICAO','contest-candidates','evaluators?stage=CONCURSO','evaluator-sync-status','agulha/data'][index]}: ${result.reason?.message||'falha de comunicação'}`:null).filter(Boolean);
   if(loaded[1].status==='rejected')throw new Error('/api/candidates — '+loaded[1].reason.message);
   const d=values[0]||{candidates:[]},c=values[1],auditionArrivals=values[2]||{arrivals:{}},contestArrivals=values[3]||{arrivals:{}},s=values[4]||{scores:{}},e=values[5]||{evaluators:[]},contest=values[6]||{candidates:[],scores:{}},contestEvaluators=values[7]||{evaluators:[]},sync=values[8]||{reports:[]},agulha=values[9]||{evaluators:[],results:[]};
   previewRows=d.candidates||[]; auditionCandidates=c.candidates||[]; auditionArrivalData=auditionArrivals.arrivals||{}; contestArrivalData=contestArrivals.arrivals||{}; auditionScores=s.scores||{}; contestScores=contest.scores||{}; contestCandidates=contest.candidates||[]; evaluatorRoster=e.evaluators||[]; contestEvaluatorRoster=contestEvaluators.evaluators||[]; evaluatorSyncReports=sync.reports||[]; agulhaProgressData=agulha||{evaluators:[],results:[]}; render();renderScoreProgress();
   const presentes=(previewRows.length?previewRows:auditionCandidates).filter(x=>arrivalFor(x,previewRows.length?'CONCURSO':'AUDICAO')).length;
   $('dbStatus').textContent='Banco da Audição conectado. '+auditionCandidates.length+' participante(s) cadastrado(s); '+(contest.candidates||[]).length+' classificado(s) para o Concurso; '+presentes+' chegada(s) confirmada(s).'+(errors.length?' Algumas áreas secundárias não responderam: '+errors.join(' | '):' Sincronização automática ativa.');
 }catch(e){$('dbStatus').textContent='Não foi possível atualizar o painel: '+e.message+'. Confirme que a Central está aberta pelo endereço do servidor local.'}
 finally{refreshInFlight=false}
}
function normCategory(value){
 const s=String(value||'').trim().toLocaleLowerCase('pt-BR').normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').replace(/\\s+/g,' ');
 if(s.includes('rainha')) return 'Rainha do Samba';
 if(s.includes('passista')) return 'Passista de Ouro';
 if(s.includes('diva') || s.includes('miss plus') || s.includes('plus size')) return 'Diva do Samba (Plus Size)';
 return String(value||'').trim();
}
function candidateCategory(candidate){return normCategory(candidate?.category||candidate?.categoria||candidate?.modalidade||candidate?.category_name||'')}
function arrivalFor(candidate,stage=$('globalStage')?.value==='concurso'?'CONCURSO':'AUDICAO'){const arrivals=stage==='CONCURSO'?contestArrivalData:auditionArrivalData;return arrivals[String(candidate.id)]||null}
function evaluatorProgress(candidate){
 const stage=$('globalStage')?.value==='concurso'?'CONCURSO':'AUDICAO';
 const saved=(stage==='concurso'?contestScores:auditionScores)[String(candidate.id)]||{};
 const roster=stage==='concurso'?contestEvaluatorRoster:evaluatorRoster;
 const hasScore=(v,criterion)=>v&&v[criterion]!==null&&v[criterion]!==undefined&&String(v[criterion]).trim()!=='';
 // Cada avaliador cadastrado conta no máximo uma vez. Normalizar nomes evita
 // diferenças de acento/espaços; limitar ao total impede estados inválidos como 5/2.
 const evaluatorKey=value=>String(value??'').normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').replace(/\\s+/g,' ').trim().toLocaleLowerCase('pt-BR');
 const savedByEvaluator=new Map(Object.entries(saved).map(([name,values])=>[evaluatorKey(name),values]));
 const total=roster.length;
 const count=criterion=>{
   // A prévia só conta notas vinculadas aos avaliadores atualmente cadastrados.
   // Não usar fallback por quantidade de registros: isso marca todos os participantes
   // como avaliados quando existem notas antigas de outros avaliadores.
   return roster.filter(name=>hasScore(savedByEvaluator.get(evaluatorKey(name)),criterion)).length;
 };
 const status=criterion=>{const n=count(criterion);return `<span class="presence ${total>0&&n>=total?'yes':'no'}">${n}/${total}</span>`};
 if(stage==='CONCURSO'){const category=candidateCategory(candidate);const eligible=category==='Rainha do Samba'||category==='Diva do Samba (Plus Size)';return {aesthetics:eligible?status('aesthetics_sympathy'):'—',communication:status('communication_elegance'),samba:status('samba')}}
 return {aesthetics:'—',communication:status('communication'),samba:status('samba')};
}
function formatTime(value){if(!value)return '—';const d=new Date(value);return Number.isNaN(d.getTime())?String(value):d.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}
function render(){
 const stage=$('globalStage')?.value||'audicao';
 const baseRows=stage==='concurso'?previewRows:auditionCandidates;
 const f=$('filter').value, pf=$('presenceFilter') ? $('presenceFilter').value : '';
 const q=($('candidateSearch')?.value||'').trim().toLocaleLowerCase('pt-BR');
 $('arrivalTitle').textContent=stage==='concurso'?'3. Classificados na Audição — controle de chegada':'3. Chegada da Audição — controle de chegada';
 $('arrivalHelp').textContent=stage==='concurso'?'Exibe somente candidatas classificadas e publicadas na Audição. Confira as chegadas registradas.':'Exibe a lista geral de candidatas da Audição. Confira as chegadas registradas.';
 const categoryOrder=['Passista de Ouro','Diva do Samba (Plus Size)','Rainha do Samba'];
 let rows=baseRows.filter(x=>(!q||String(x.name||'').toLocaleLowerCase('pt-BR').includes(q))&&(!f||normCategory(x.category)===f));
 rows=rows.filter(x=>!pf||(pf==='present'?!!arrivalFor(x):!arrivalFor(x)));
 rows.sort((a,b)=>{const ca=normCategory(a.category),cb=normCategory(b.category);const ia=categoryOrder.indexOf(ca),ib=categoryOrder.indexOf(cb);return (ia<0?categoryOrder.length:ia)-(ib<0?categoryOrder.length:ib)||String(a.name||'').localeCompare(String(b.name||''),'pt-BR')});
 $('total').textContent=baseRows.length;
 const cats={'Rainha do Samba':'rainha','Passista de Ouro':'passista','Diva do Samba (Plus Size)':'diva'};
 for(const [c,id] of Object.entries(cats))$(id).textContent=baseRows.filter(x=>normCategory(x.category)===c).length;
 const presentes=baseRows.filter(x=>!!arrivalFor(x)).length;
 $('presentes').textContent=presentes; $('aguardando').textContent=Math.max(0,baseRows.length-presentes);
 $('categories').innerHTML=Object.keys(cats).map(c=>{const list=baseRows.filter(x=>normCategory(x.category)===c);const count=list.filter(x=>!!arrivalFor(x)).length;return `<div class="category"><div><b>${c}</b><br><span>${count} presente(s) de ${list.length}</span></div><b>${count}/${list.length}</b></div>`}).join('');
 if(!rows.length){$('rows').innerHTML='<tr><td colspan="6">Nenhum candidato para este filtro.</td></tr>'}
 else{
   let rowNumber=0;
   const grouped=categoryOrder.map(category=>({category,items:rows.filter(x=>normCategory(x.category)===category)})).filter(group=>group.items.length);
   const other=rows.filter(x=>!categoryOrder.includes(normCategory(x.category)));
   if(other.length)grouped.push({category:'Outras categorias',items:other});
   $('rows').innerHTML=grouped.map(group=>`<tr class="category-group"><td colspan="6" style="background:#fff5f5;color:#a50d25;font-weight:800;border-top:2px solid #e5b7be">${esc(group.category)} — ${group.items.length} participante(s)</td></tr>`+group.items.map(x=>{const a=arrivalFor(x);rowNumber++;return `<tr><td>${rowNumber}</td><td>${esc(normCategory(x.category))}</td><td>${esc(x.name)}</td><td><span class="presence ${a?'yes':'no'}">${a?'Presente':'Aguardando'}</span></td><td>${a?esc(formatTime(a.arrived_at)):'—'}</td><td>${a?esc(a.device||'—'):'—'}</td></tr>`}).join('')).join('');
 }
}
function renderScoreProgress(){
 const stage=$('scoreProgressStage')?.value||'AUDICAO';
 const roster=stage==='CONCURSO'?contestEvaluatorRoster:stage==='AGULHA'?(agulhaProgressData.evaluators||[]):evaluatorRoster;
 const source=stage==='CONCURSO'?contestCandidates:stage==='AGULHA'?(agulhaProgressData.results||[]):auditionCandidates;
 const candidates=source.filter(candidate=>stage==='AGULHA'||(()=>{const arrival=arrivalFor(candidate,stage);return !!arrival&&String(arrival.status||'PRESENTE').toUpperCase()!=='AUSENTE'})());
 const scores=stage==='CONCURSO'?contestScores:stage==='AGULHA'?{}:auditionScores;
 const criteriaFor=candidate=>{
  if(stage==='AUDICAO')return ['communication','samba'];
  if(stage==='AGULHA')return ['score'];
  const category=candidateCategory(candidate);
  return category==='Passista de Ouro'?['communication_elegance','samba']:['aesthetics_sympathy','communication_elegance','samba'];
 };
 const progress=roster.map(evaluator=>{
  let expected=0,received=0,partial=0;
  for(const candidate of candidates){
   const criteria=criteriaFor(candidate),saved=stage==='AGULHA'?{score:candidate.scores?.[evaluator]}:((scores[String(candidate.id)]||{})[evaluator]||{});
   expected+=criteria.length;
   const count=criteria.filter(name=>saved[name]!==null&&saved[name]!==undefined&&String(saved[name]).trim()!=='').length;
   received+=count;if(count>0&&count<criteria.length)partial++;
  }
  return {evaluator,expected,received,missing:Math.max(0,expected-received),partial,percent:expected?Math.min(100,Math.round(received*100/expected)):0};
 });
 const expected=progress.reduce((sum,row)=>sum+row.expected,0),received=progress.reduce((sum,row)=>sum+row.received,0),missing=Math.max(0,expected-received);
 $('scoreNotesReceived').textContent=received.toLocaleString('pt-BR');$('scoreNotesMissing').textContent=missing.toLocaleString('pt-BR');
 $('scoreProgressHelp').textContent=stage==='CONCURSO'?'Notas recebidas e pendentes nos critérios aplicáveis aos participantes presentes do Concurso.':stage==='AGULHA'?'Notas de vestido/roupa recebidas e pendentes entre as participantes elegíveis do Agulha de Ouro.':'Notas de Comunicação e Samba recebidas e pendentes entre participantes presentes na Audição.';
 $('scoreProgressUpdated').textContent='Atualizado às '+new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
 $('scoreProgressRows').innerHTML=progress.length?progress.map(row=>`<tr><td><strong>${esc(row.evaluator)}</strong></td><td>${row.received} / ${row.expected}</td><td>${row.missing}</td><td>${row.partial}</td><td><div class="evaluator-progress"><progress max="100" value="${row.percent}">${row.percent}%</progress><span>${row.percent}%</span></div></td></tr>`).join(''):'<tr><td colspan="5">Nenhum avaliador cadastrado nesta etapa.</td></tr>';
 const matching=evaluatorSyncReports.map(report=>({...report,pending:(report.pending||[]).filter(item=>item.stage===stage)})).filter(report=>report.pending.length);
 const pendingDevices=new Set(matching.map(report=>report.device)).size,pendingNotes=matching.reduce((sum,report)=>sum+report.pending.reduce((n,item)=>n+Number(item.count||0),0),0);
 $('scorePendingDevices').textContent=pendingDevices.toLocaleString('pt-BR');
 $('pendingDeviceDetails').innerHTML=matching.length?'<h3>Tablets com notas aguardando sincronização</h3><ul>'+matching.map(report=>{const details=report.pending.map(item=>`${item.stage==='CONCURSO'?'Concurso':item.stage==='AGULHA'?'Agulha de Ouro':'Audição'} — ${esc(item.evaluator)}: ${Number(item.count).toLocaleString('pt-BR')} registro(s) de nota`).join(' · '),age=Math.max(0,Math.floor(Date.now()/1000-Number(report.last_seen||0))),lastSeen=age<60?`há ${age} s`:`há ${Math.floor(age/60)} min`;return `<li><strong>${esc(report.device)}</strong> — ${details}<span>Último contato ${lastSeen}</span></li>`}).join('')+'</ul><p class="help">'+pendingNotes.toLocaleString('pt-BR')+' registro(s) de nota ainda não confirmados pelo banco da Central.</p>':'<p class="help">Nenhum tablet está reportando notas pendentes nesta etapa.</p>';
}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
$('file').addEventListener('change',()=>{$('importBtn').disabled=!$('file').files.length;$('importStatus').textContent=$('file').files.length?'Arquivo selecionado: '+$('file').files[0].name:'Aguardando arquivo Excel.'});
$('importBtn').addEventListener('click',async()=>{
 const file=$('file').files[0];if(!file)return;
 if(!confirm('A reimportação substituirá a lista de candidatas e apagará as chegadas, notas da Audição e publicação atual. O sistema criará um conjunto de backup dos três bancos antes de continuar. Deseja reimportar?'))return;
 $('importBtn').disabled=true;$('importStatus').textContent='Importando e validando candidatos…';
 try{const fd=new FormData();fd.append('file',file);const r=await fetch('/api/import',{method:'POST',headers:{'X-Uesp-Confirm-Import':'true'},body:fd});const j=await r.json();if(!r.ok||!j.ok)throw new Error(j.error||'Erro ao importar');$('importStatus').textContent=`Importação concluída: ${j.imported} candidato(s). Conjunto de backup dos três bancos: ${j.backup_set_id||j.backup||'não criado'}.`;await refresh();await loadBackupSets()}
 catch(e){$('importStatus').textContent='Falha na importação: '+e.message}finally{$('importBtn').disabled=false}
});
$('refreshBtn').addEventListener('click',refresh);$('filter').addEventListener('change',render);if($('candidateSearch'))$('candidateSearch').addEventListener('input',render);
async function applyGlobalStage(stage,persist=true){$('globalStage').value=stage;$('scoreProgressStage').value=stage.toUpperCase();const rosterStage=$('rosterStage');if(rosterStage){rosterStage.value=stage.toUpperCase();loadRoster()}const link=$('evaluatorLink');link.href='avaliador.html?stage='+encodeURIComponent(stage);link.textContent='Abrir avaliador — '+(stage==='concurso'?'Concurso':'Audição');document.querySelector('header small').textContent=(stage==='concurso'?'CONCURSO':'AUDIÇÃO')+' MISS UESP • CARNAVAL 2027';try{localStorage.setItem('uesp_active_stage',stage)}catch(e){};render();renderScoreProgress();if(persist){try{const response=await api('/api/active-stage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({stage:stage==='concurso'?'CONCURSO':'AUDICAO'})});if(response.stage!==(stage==='concurso'?'CONCURSO':'AUDICAO'))throw new Error('O servidor retornou uma etapa diferente.');$('dbStatus').textContent='Etapa '+(stage==='concurso'?'Concurso':'Audição')+' sincronizada com o servidor.'}catch(e){$('dbStatus').textContent='ERRO ao sincronizar etapa: '+e.message+' — confira se a Central está aberta pelo mesmo endereço do servidor.'}}}
$('globalStage').addEventListener('change',()=>applyGlobalStage($('globalStage').value,true));
$('scoreProgressStage').addEventListener('change',renderScoreProgress);
(async()=>{try{const current=await api('/api/active-stage');await applyGlobalStage(String(current.stage||'AUDICAO').toLowerCase()==='concurso'?'concurso':'audicao',false)}catch(e){console.warn('Não foi possível carregar a etapa do servidor:',e)}})();if($('presenceFilter')) $('presenceFilter').addEventListener('change',render);

$('clearContestBtn').addEventListener('click',async()=>{
 if(!confirm('Confirma apagar TODAS as notas do Concurso? A lista de avaliadores do Concurso, as notas e os avaliadores da Audição, candidatos, fotos, categorias, ordem e publicação da Audição serão preservados.'))return;
 const b=$('clearContestBtn');b.disabled=true;$('clearContestStatus').textContent='Limpando somente as notas do Concurso…';
 try{const j=await api('/api/clear-contest-scores',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirm:true})});$('clearContestStatus').textContent=`Concluído: ${j.deleted} nota(s) do Concurso removida(s). Lista de avaliadores e dados da Audição preservados.`;}catch(e){$('clearContestStatus').textContent='Falha: '+e.message}finally{b.disabled=false}
});
async function loadBackupSets(){
 const select=$('backupSetSelect'),button=$('restoreBackupBtn'),status=$('backupRestoreStatus');
 $('refreshBackupsBtn').disabled=true;button.disabled=true;status.textContent='Carregando conjuntos de backup…';
 try{
  const j=await api('/api/backups'),sets=j.sets||[];
  const reasons={antes_limpeza_total:'Antes da limpeza total',antes_restauracao:'Antes de uma restauração',antes_reimportacao:'Antes de reimportar a lista'};
  select.innerHTML='<option value="">— Selecione um conjunto —</option>'+sets.map(item=>{
   const date=new Date(item.created_at),dateLabel=Number.isNaN(date.getTime())?item.created_at:date.toLocaleString('pt-BR');
   const size=(Number(item.size_bytes||0)/1048576).toLocaleString('pt-BR',{maximumFractionDigits:1});
   return `<option value="${esc(item.id)}">${esc(dateLabel)} · ${esc(reasons[item.reason]||'Backup completo')} · ${size} MB</option>`;
  }).join('');
  select.disabled=!sets.length;status.textContent=sets.length?`${sets.length} conjunto(s) completo(s) disponível(is). A política mantém os ${j.retention||30} mais recentes.`:'Nenhum conjunto completo disponível na pasta backup de banco.';
 }catch(e){select.innerHTML='<option value="">Não foi possível carregar os backups</option>';select.disabled=true;status.textContent='Falha ao listar backups: '+e.message}
 finally{$('refreshBackupsBtn').disabled=false;button.disabled=!select.value}
}
$('refreshBackupsBtn').addEventListener('click',loadBackupSets);
$('backupSetSelect').addEventListener('change',()=>{$('restoreBackupBtn').disabled=!$('backupSetSelect').value});
$('restoreBackupBtn').addEventListener('click',async()=>{
 const setId=$('backupSetSelect').value;if(!setId)return;
 const selected=$('backupSetSelect').selectedOptions[0]?.textContent||setId;
 if(!confirm(`Restaurar este conjunto de três bancos?\n\n${selected}\n\nO estado atual também será salvo em um novo conjunto antes da restauração.`))return;
 const button=$('restoreBackupBtn');button.disabled=true;$('refreshBackupsBtn').disabled=true;$('backupRestoreStatus').textContent='Protegendo o estado atual e restaurando os três bancos…';
 try{
  const restored=await api('/api/restore-backup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({backup_set_id:setId,confirm:true})});
  const active=await api('/api/active-stage'),stage=String(active.stage||'AUDICAO').toUpperCase()==='CONCURSO'?'concurso':'audicao';
  $('globalStage').value=stage;await applyGlobalStage(stage,false);await refresh();await loadRoster();
  await loadBackupSets();
  $('backupRestoreStatus').textContent=`Restauração concluída. Estado anterior preservado no conjunto ${restored.recovery_set_id}.`;
 }catch(e){await loadBackupSets();$('backupRestoreStatus').textContent='Falha ao restaurar: '+e.message;button.disabled=!$('backupSetSelect').value;$('refreshBackupsBtn').disabled=false}
});
$('clearScoresBtn').addEventListener('click',async()=>{
 const confirmed=confirm('ATENÇÃO: esta limpeza total apagará TODOS os dados dos três bancos: lista de participantes, chegadas, fotos, dados de cadastro, notas, avaliadores, resultados publicados e configurações de Audição, Concurso e Agulha de Ouro. Serão criados backups dos três bancos na pasta "backup de banco" antes da exclusão. Depois, será necessário importar uma nova lista. Deseja continuar?');
 if(!confirmed)return;
 const btn=$('clearScoresBtn');btn.disabled=true;$('clearScoresStatus').textContent='Criando backups dos três bancos antes da limpeza total…';
 try{
  const j=await api('/api/clear-scores',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirm:true})});
  $('globalStage').value='audicao';await applyGlobalStage('audicao',false);await refresh();await loadRoster();
  $('clearScoresStatus').textContent=`Limpeza total concluída: ${j.deleted_records||0} registro(s) apagados. Backup dos três bancos: ${j.backup_set_id}. Importe uma nova lista para iniciar.`;
  await loadBackupSets();
 }catch(e){$('clearScoresStatus').textContent='Falha na exclusão: '+e.message}
 finally{btn.disabled=false}
});
$('exportBtn').addEventListener('click',()=>{
 const f=$('filter').value,pf=$('presenceFilter') ? $('presenceFilter').value : '';let rows=previewRows.filter(x=>!f||normCategory(x.category)===f);rows=rows.filter(x=>!pf||(pf==='present'?!!arrivalFor(x):!arrivalFor(x)));
 const csv=['Categoria;Nome do candidato;Chegada;Horário;Dispositivo',...rows.map(x=>{const a=arrivalFor(x,'CONCURSO');return `"${normCategory(x.category).replaceAll('"','""')}";"${String(x.name||'').replaceAll('"','""')}";"${a?'Presente':'Aguardando'}";"${a?formatTime(a.arrived_at):''}";"${a?String(a.device||'').replaceAll('"','""'):''}"`})].join('\r\n');
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));a.download='candidatos_uesp_2027.csv';a.click();URL.revokeObjectURL(a.href)
});
refresh();loadBackupSets();setInterval(refresh,5000);document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')refresh()});
