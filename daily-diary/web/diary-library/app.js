'use strict';
const $ = id => document.getElementById(id);
let entries = [], days = [], selectedDate = '', selectedId = '', loadedRevision = '', view = 'read', token = 0;
const weekdays = ['星期日','星期一','星期二','星期三','星期四','星期五','星期六'];
async function request(path) { const r = await fetch(path, {cache:'no-store'}); const data = await r.json(); if (!r.ok) throw new Error(data.error || '读取失败'); return data; }
function variants(day) { return entries.filter(e => e.date === day); }
function renderDates() {
  days = [...new Set(entries.map(e => e.date))].filter(d => !$('month').value || d.startsWith($('month').value));
  const scrollTop=$('days').scrollTop; $('days').replaceChildren(); $('count').textContent = `${days.length} 天`;
  for (const day of days) {
    const first = variants(day)[0], b = document.createElement('button'); b.className = 'day' + (day === selectedDate ? ' selected' : '');
    const top = document.createElement('div'); top.className = 'day-row'; const strong = document.createElement('strong'); strong.textContent = day;
    const mark = document.createElement('span'); mark.className = 'mini'; mark.textContent = first.draft ? '草稿' : '日记'; top.append(strong,mark);
    const excerpt = document.createElement('small'); excerpt.textContent = first.excerpt.slice(0,54) || first.label; b.append(top,excerpt); b.addEventListener('click', () => choose(day)); $('days').append(b);
  }
  if (!days.length) { const p=document.createElement('p'); p.className='empty'; p.textContent='没有找到匹配的日记'; $('days').append(p); }
  $('days').scrollTop=scrollTop; const i = days.indexOf(selectedDate); $('older').disabled = i < 0 || i >= days.length - 1; $('newer').disabled = i <= 0;
  $('position').textContent = i >= 0 ? `${i + 1} / ${days.length} 天` : '';
}
async function choose(day, id) {
  selectedDate = day; const vs = variants(day); const item = vs.find(e => e.id === id) || vs[0]; if (!item) return;
  selectedId=item.id; loadedRevision=item.revision; $('versions').replaceChildren(...vs.map(e => { const o=document.createElement('option'); o.value=e.id; o.textContent=e.label; return o; })); $('versions').value=item.id;
  $('date').textContent=day; $('crumb-date').textContent=day; $('weekday').textContent=weekdays[new Date(day+'T12:00:00').getDay()]+' · DAILY JOURNAL';
  $('status').textContent = item.label + (item.draft ? ' · 未确认' : '');
  const base='/diary/api/entries/'+item.id; $('pdf-download').href=base+'/pdf'; $('md-download').href=base+'/markdown';
  for (const id of ['pdf-download','md-download']) $(id).classList.toggle('disabled',!item.ready);
  renderDates(); document.querySelector('.sidebar').classList.remove('open');
  history.replaceState(null,'','#'+day+(id?'&version='+id:'')); const myToken=++token;
  if (!item.ready) { $('article').replaceChildren(); const p=document.createElement('p'); p.className='empty'; p.textContent='这份日记的 PDF 正在生成，完成后会自动出现在这里。'; $('article').append(p); $('reading-note').textContent='准备中'; $('pdf-frame').removeAttribute('src'); return; }
  try { const data=await request(base+'/content'); if (myToken!==token) return; $('article').innerHTML=data.html;
    const heading=[...$('article').querySelectorAll('h2')].find(h=>h.textContent.includes('来源状态'));
    if (heading) { const details=document.createElement('details'), summary=document.createElement('summary'); summary.textContent='查看资料来源与缺口'; details.append(summary); let node=heading.nextSibling; while(node) { const next=node.nextSibling; details.append(node); node=next; } heading.replaceWith(details); }
    $('reading-note').textContent='Markdown 与 PDF 同一版本'; if(view==='pdf') $('pdf-frame').src=base+'/pdf';
  } catch(e) { $('article').textContent=e.message; }
}
async function load() {
  try { const data=await request('/diary/api/index?q='+encodeURIComponent($('search').value.trim())); entries=data.entries;
    const current=$('month').value, months=[...new Set(entries.map(e=>e.date.slice(0,7)))]; $('month').replaceChildren(new Option('全部月份',''),...months.map(m=>new Option(m,m))); $('month').value=months.includes(current)?current:'';
    const ready=entries.filter(e=>e.ready).length; $('notice').textContent=data.progress.running ? `正在准备日记与 PDF：${ready} / ${entries.length} 份已可阅读。` : ready<entries.length ? `${entries.length-ready} 份PDF暂未生成，正在重试；已有日记可正常阅读。` : '';
    renderDates(); const hash=location.hash.slice(1).split('&version='); const day=days.includes(selectedDate)?selectedDate:days.includes(hash[0])?hash[0]:days[0];
    if(day) { const now=variants(day).find(e=>e.id===selectedId); if(!now || now.revision!==loadedRevision || $('article').textContent.includes('正在生成') || !selectedDate) await choose(day,hash[1]); }
    else { selectedDate=''; selectedId=''; $('date').textContent='没有匹配的日记'; $('article').textContent='试试其他日期、人物或关键词。'; $('pdf-frame').removeAttribute('src'); for(const id of ['pdf-download','md-download']) $(id).classList.add('disabled'); }
  } catch(e) { $('notice').textContent=e.message; }
}
$('versions').addEventListener('change',()=>choose(selectedDate,$('versions').value));
$('month').addEventListener('change',()=>{renderDates(); if(!days.includes(selectedDate)&&days.length) choose(days[0]);});
$('older').addEventListener('click',()=>choose(days[days.indexOf(selectedDate)+1])); $('newer').addEventListener('click',()=>choose(days[days.indexOf(selectedDate)-1]));
$('menu').addEventListener('click',()=>document.querySelector('.sidebar').classList.toggle('open')); $('refresh').addEventListener('click',()=>{selectedId='';load();});
let searchTimer; $('search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(load,250);});
for(const b of document.querySelectorAll('[data-view]')) b.addEventListener('click',()=>{view=b.dataset.view; for(const t of document.querySelectorAll('[data-view]')) t.classList.toggle('active',t===b); $('article').hidden=view!=='read'; $('pdf-frame').hidden=view!=='pdf'; if(view==='pdf'&&selectedId&&entries.find(e=>e.id===selectedId)?.ready) $('pdf-frame').src='/diary/api/entries/'+selectedId+'/pdf';});
load(); setInterval(load,30000);
