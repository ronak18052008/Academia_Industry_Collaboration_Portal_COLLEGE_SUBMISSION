function toggleSidebar(){document.getElementById('sidebar')?.classList.toggle('open')}
document.querySelectorAll('.sidebar nav a').forEach(a=>{if(location.pathname===new URL(a.href).pathname)a.classList.add('active')})
setTimeout(()=>document.querySelectorAll('.flash').forEach(x=>x.classList.add('fade')),4500)
