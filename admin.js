(() => {
 const $ = id => document.getElementById(id);
 let allRows = [];
 const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
 async function api(url, options={}) {
   const response = await fetch(url, options);
   if (response.status === 401) { location.replace("/admin/login"); throw new Error("Sesión no válida."); }
   const data = response.headers.get("content-type")?.includes("application/json") ? await response.json() : null;
   if (!response.ok) throw new Error(data?.detail || "Ocurrió un error.");
   return data;
 }
 async function loadStats() {
   const s = await api("/api/admin/stats");
   $("responses").textContent=s.responses; $("attending").textContent=s.attending;
   $("declining").textContent=s.declining; $("people").textContent=s.people;
 }
 function render(rows) {
   $("rows").innerHTML = rows.length ? rows.map(r => `<tr>
    <td class="guest-name">${esc(r.guest)}</td>
    <td><span class="status ${r.attendance.startsWith("Sí")?"yes":"no"}">${esc(r.attendance)}</span></td>
    <td>${r.guests}</td><td class="message">${esc(r.message || "—")}</td>
    <td>${new Date(r.created_at).toLocaleString("es-MX")}</td>
    <td><button class="delete" data-id="${r.id}" aria-label="Eliminar registro">Eliminar</button></td>
   </tr>`).join("") : '<tr><td colspan="6" class="empty">Aún no hay confirmaciones registradas.</td></tr>';
   $("empty").textContent = `${rows.length} registro(s)`;
 }
 async function loadRows() {
   allRows = await api("/api/admin/rsvps");
   filterRows();
 }
 function filterRows() {
   const q=$("search").value.trim().toLocaleLowerCase("es");
   render(allRows.filter(r=>r.guest.toLocaleLowerCase("es").includes(q)));
 }
 async function init() {
   try {
     const session=await api("/api/admin/me");
     if(!session.authenticated){location.replace("/admin/login");return;}
     await Promise.all([loadStats(),loadRows()]);
   } catch(e) { $("notice").textContent=e.message; }
 }
 $("search").addEventListener("input",filterRows);
 $("rows").addEventListener("click",async e=>{
   const button=e.target.closest("[data-id]"); if(!button)return;
   if(!confirm("¿Eliminar esta confirmación? Esta acción no se puede deshacer."))return;
   try { await api(`/api/admin/rsvps/${button.dataset.id}`,{method:"DELETE"}); await Promise.all([loadStats(),loadRows()]); }
   catch(err){$("notice").textContent=err.message;}
 });
 $("logout").addEventListener("click",async()=>{
   try{await api("/api/admin/logout",{method:"POST"});}finally{location.replace("/admin/login");}
 });
 init();
})();
