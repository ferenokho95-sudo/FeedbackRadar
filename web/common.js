const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=(x,n=2)=>x==null?'—':Number(x).toLocaleString('ru-RU',{maximumFractionDigits:n});
async function api(path,data){const r=await fetch(path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const v=await r.json();if(!r.ok)throw Error(v.error||r.status);return v;}
async function task(fn,button){$('error').textContent='';if(button)button.disabled=true;try{return await fn()}catch(e){$('error').textContent=e.message}finally{if(button)button.disabled=false}}
function table(headers,rows){return '<div class="scroll"><table><thead><tr>'+headers.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(x=>'<td>'+esc(x)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>'}
function stat(label,value){return '<div class="card"><div class="label">'+esc(label)+'</div><div class="stat">'+esc(value)+'</div></div>'}
function download(name,data,type='application/json'){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([data],{type}));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),2000)}
