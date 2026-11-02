/* Durable, device-local queue for scores that could not reach the server. */
(function(){
 const STORAGE_KEY='uesp_pending_score_sync';
 function read(){
  try{
   const value=JSON.parse(localStorage.getItem(STORAGE_KEY)||'[]');
   return Array.isArray(value)?value.filter(item=>item&&typeof item==='object'):[];
  }catch(e){return []}
 }
 function sameDraft(a,b){
  return a.stage===b.stage&&String(a.id)===String(b.id)&&a.criterion===b.criterion&&a.evaluator===b.evaluator;
 }
 function list(){return read()}
 function enqueue(item){
  try{
   const queue=read(),entry={...item,updated_at:Date.now()+'_'+Math.random().toString(36).slice(2)};
   const index=queue.findIndex(existing=>sameDraft(existing,entry));
   if(index<0)queue.push(entry);else queue[index]=entry;
   localStorage.setItem(STORAGE_KEY,JSON.stringify(queue));
   return entry;
  }catch(e){return null}
 }
 function remove(item){
  try{
   const queue=read().filter(existing=>!sameDraft(existing,item)||existing.updated_at!==item.updated_at);
   localStorage.setItem(STORAGE_KEY,JSON.stringify(queue));
   return queue.length;
  }catch(e){return read().length}
 }
 window.uespOfflineScoreQueue={list,enqueue,remove};
})();
