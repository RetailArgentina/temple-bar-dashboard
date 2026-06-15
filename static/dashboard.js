/* dashboard.js — Temple Bar Executive Dashboard
 *
 * Adapted from super_dashboard_temple.html:
 *   - Removed embedded const RAW = {...} (data loaded from /api/data)
 *   - Added initData() async fetch replacing static data
 *   - Added deriveCanal() / deriveTurno() from ventas (API no longer returns these)
 *   - Added estabSelect populated dynamically from API
 *   - Added estabSelect onChange handler (was missing in original)
 *   - Fixed initDatePicker() called inside initData() after data is available
 *   - Fixed flatpickr onChange to use proper callback API
 *   - Added last_updated display in ART timezone
 */

let RAW = null;

let state = {d1:null, d2:null, estab:'ALL', darkMode:false};
let charts = {};

const C = {
    azul:'#2E5FA3', azulDark:'#1B3A6B', azulLight:'#D6E4F7',
    rojo:'#C0392B', verde:'#1E8449', amarillo:'#D4A017',
    charts:['#2E5FA3','#27AE60','#E67E22','#8E44AD','#16A085','#C0392B','#F39C12','#2980B9']
};

const fmtARS = v => '$' + Math.round(v).toLocaleString('es-AR');
const fmtM = v => '$' + (v/1e6).toFixed(1) + 'M';
const fmtK = v => v >= 1000 ? (v/1000).toFixed(1)+'K' : Math.round(v).toString();
const pctDelta = (a, b) => b > 0 ? ((a-b)/b*100).toFixed(1) : 0;

function addDays(dateStr, days) {
    const d = new Date(dateStr + 'T12:00:00Z');
    d.setUTCDate(d.getUTCDate() + days);
    return d.toISOString().split('T')[0];
}
function subtractDays(dateStr, days) { return addDays(dateStr, -days); }

function getFiltered() {
    const {d1, d2, estab} = state;
    const ok = r => r.d >= d1 && r.d <= d2 && (estab === 'ALL' || r.e === estab);
    return {
        ventas:RAW.ventas.filter(ok),
        canal:RAW.canal.filter(r => r.d >= d1 && r.d <= d2),
        turno:RAW.turno.filter(r => r.d >= d1 && r.d <= d2),
        mix:RAW.mix.filter(ok),
        cerv:RAW.cerv.filter(ok),
        gin:RAW.gin.filter(ok),
        ferid:RAW.ferid.filter(ok)
    };
}

function getPrevFiltered() {
    const {d1, d2, estab} = state;
    const d1Date = new Date(d1 + 'T12:00:00Z');
    const d2Date = new Date(d2 + 'T12:00:00Z');
    const days = Math.round((d2Date - d1Date) / 86400000) + 1;
    const pd2 = subtractDays(d1, 1);
    const pd1 = subtractDays(pd2, days - 1);
    const ok = r => r.d >= pd1 && r.d <= pd2 && (estab === 'ALL' || r.e === estab);
    return RAW.ventas.filter(ok);
}

function makeChart(id, config) {
    if (charts[id]) {
        charts[id].destroy();
        delete charts[id];
    }
    try {
        const ctx = document.getElementById(id);
        if (!ctx) return;
        config.options = config.options || {};
        config.options.maintainAspectRatio = false;
        charts[id] = new Chart(ctx, config);
    } catch (e) {
        console.error('Chart error', id, e);
    }
}

function updateKPIs(f, pv) {
    const vt = f.ventas.reduce((s,r) => s + r.v, 0);
    const ot = f.ventas.reduce((s,r) => s + r.o, 0);
    const pvt = pv.reduce((s,r) => s + r.v, 0);
    const pot = pv.reduce((s,r) => s + r.o, 0);
    const tk = ot > 0 ? vt / ot : 0;
    const ptk = pot > 0 ? pvt / pot : 0;
    const activos = new Set(f.ventas.map(r => r.e)).size;

    const delta_vt = pctDelta(vt, pvt);
    const delta_ot = pctDelta(ot, pot);
    const delta_tk = pctDelta(tk, ptk);

    const html = `
        <div class="kpi-card">
            <div class="kpi-label">Ventas Totales</div>
            <div class="kpi-value">${fmtM(vt)}</div>
            <div class="kpi-change ${delta_vt >= 0 ? 'positive' : 'negative'}">
                ${delta_vt >= 0 ? '▲' : '▼'} ${Math.abs(delta_vt)}% vs período anterior
            </div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Órdenes</div>
            <div class="kpi-value">${fmtK(ot)}</div>
            <div class="kpi-change ${delta_ot >= 0 ? 'positive' : 'negative'}">
                ${delta_ot >= 0 ? '▲' : '▼'} ${Math.abs(delta_ot)}% vs período anterior
            </div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Ticket Promedio</div>
            <div class="kpi-value">${fmtARS(tk)}</div>
            <div class="kpi-change ${delta_tk >= 0 ? 'positive' : 'negative'}">
                ${delta_tk >= 0 ? '▲' : '▼'} ${Math.abs(delta_tk)}% vs período anterior
            </div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Establecimientos Activos</div>
            <div class="kpi-value">${activos}</div>
            <div class="kpi-change">en el período seleccionado</div>
        </div>
    `;
    document.getElementById('kpiResumen').innerHTML = html;
}

function updateResumenCharts(f) {
    const dailyData = {};
    f.ventas.forEach(r => {
        dailyData[r.d] = (dailyData[r.d] || 0) + r.v;
    });
    const dates = Object.keys(dailyData).sort();
    makeChart('chartVentasDiarias', {
        type:'line',
        data:{
            labels:dates,
            datasets:[{
                label:'Ventas',
                data:dates.map(d => dailyData[d]),
                borderColor:C.azul,
                backgroundColor:C.azulLight,
                borderWidth:2,
                fill:true,
                tension:0.4
            }]
        },
        options:{
            responsive:true,
            plugins:{legend:{display:false}},
            scales:{y:{ticks:{callback:v => fmtM(v)}}}
        }
    });

    const canalByDate = {};
    f.canal.forEach(r => {
        if (!canalByDate[r.d]) canalByDate[r.d] = {};
        canalByDate[r.d][r.c] = (canalByDate[r.d][r.c] || 0) + r.o;
    });
    const canalDates = Object.keys(canalByDate).sort();
    const canalNames = Array.from(new Set(f.canal.map(r => r.c)));
    makeChart('chartCanal', {
        type:'bar',
        data:{
            labels:canalDates,
            datasets:canalNames.map((c,i) => ({
                label:c,
                data:canalDates.map(d => canalByDate[d][c] || 0),
                backgroundColor:C.charts[i % C.charts.length]
            }))
        },
        options:{
            responsive:true,
            scales:{x:{stacked:true},y:{stacked:true}},
            plugins:{legend:{position:'bottom'}}
        }
    });

    const turnoTotals = {};
    f.turno.forEach(r => {
        turnoTotals[r.t] = (turnoTotals[r.t] || 0) + r.v;
    });
    makeChart('chartTurno', {
        type:'bar',
        data:{
            labels:Object.keys(turnoTotals).sort(),
            datasets:[{
                label:'Ventas por Turno',
                data:Object.keys(turnoTotals).sort().map(t => turnoTotals[t]),
                backgroundColor:C.charts.slice(0, Object.keys(turnoTotals).length)
            }]
        },
        options:{
            responsive:true,
            plugins:{legend:{display:false}},
            scales:{y:{ticks:{callback:v => fmtM(v)}}}
        }
    });

    const mixTotals = {};
    f.mix.forEach(r => {
        mixTotals[r.m] = (mixTotals[r.m] || 0) + r.$;
    });
    const mixTop = Object.entries(mixTotals)
        .sort((a,b) => b[1] - a[1])
        .slice(0,8);
    makeChart('chartMix', {
        type:'doughnut',
        data:{
            labels:mixTop.map(x => x[0]),
            datasets:[{
                data:mixTop.map(x => x[1]),
                backgroundColor:C.charts
            }]
        },
        options:{
            responsive:true,
            plugins:{
                legend:{position:'right'},
                tooltip:{callbacks:{label:ctx => fmtM(ctx.parsed)}}
            }
        }
    });
}

function updateEstabTable(ventas, prevVentas) {
    const estabTotals = {};
    ventas.forEach(r => {
        if (!estabTotals[r.e]) estabTotals[r.e] = {v:0, o:0};
        estabTotals[r.e].v += r.v;
        estabTotals[r.e].o += r.o;
    });

    const prevEstabTotals = {};
    prevVentas.forEach(r => {
        if (!prevEstabTotals[r.e]) prevEstabTotals[r.e] = {v:0, o:0};
        prevEstabTotals[r.e].v += r.v;
        prevEstabTotals[r.e].o += r.o;
    });

    const rows = Object.entries(estabTotals)
        .map(([e,d]) => ({
            e,
            v:d.v,
            o:d.o,
            tk:d.o > 0 ? d.v / d.o : 0,
            var:pctDelta(d.v, prevEstabTotals[e]?.v || 0)
        }))
        .sort((a,b) => b.v - a.v)
        .slice(0,10);

    const html = `
        <thead><tr>
            <th>Rank</th><th>Establecimiento</th><th>Ventas</th><th>Órdenes</th><th>Ticket</th><th>Var%</th>
        </tr></thead>
        <tbody>
        ${rows.map((r,i) => `
            <tr class="${Math.abs(r.var) >= 5 ? (r.var >= 0 ? 'row-positive' : 'row-negative') : ''}">
                <td>${i+1}</td>
                <td><strong>${r.e}</strong></td>
                <td>${fmtM(r.v)}</td>
                <td>${fmtK(r.o)}</td>
                <td>${fmtARS(r.tk)}</td>
                <td class="${r.var >= 0 ? 'positive' : 'negative'}">${r.var >= 0 ? '▲' : '▼'} ${r.var}%</td>
            </tr>
        `).join('')}
        </tbody>
    `;
    document.getElementById('tableEstab').innerHTML = html;
}

function updateAlerts(f, pv) {
    const vt = f.ventas.reduce((s,r) => s + r.v, 0);
    const pvt = pv.reduce((s,r) => s + r.v, 0);
    const delta = pctDelta(vt, pvt);

    const alerts = [];
    if (delta < -10) alerts.push({type:'danger', title:'⚠️ Caída Importante', text:`Ventas ${delta}% vs período anterior`});
    else if (delta > 15) alerts.push({type:'success', title:'✅ Crecimiento Fuerte', text:`Ventas ${delta}% vs período anterior`});

    const estabs = Array.from(new Set(f.ventas.map(r => r.e)));
    const totalEstabs = new Set(RAW.ventas.map(r => r.e)).size;
    if (estabs.length < totalEstabs * 0.7) alerts.push({type:'warning', title:'⏱️ Establecimientos Activos', text:`Sólo ${estabs.length}/${totalEstabs} registrando ventas`});

    const html = alerts.map(a => `
        <div class="alert-box ${a.type}">
            <div class="alert-title">${a.title}</div>
            <div class="alert-text">${a.text}</div>
        </div>
    `).join('');
    document.getElementById('alertsContainer').innerHTML = html || '<p style="grid-column:1/-1;color:#999;">Sin alertas</p>';
}

function updateCervCharts(f) {
    const cervTotals = {};
    f.cerv.forEach(r => {
        if (!cervTotals[r.s]) cervTotals[r.s] = {v:0, q:0, cat:r.cat};
        cervTotals[r.s].v += r.$;
        cervTotals[r.s].q += r.q;
    });

    const top10 = Object.entries(cervTotals)
        .sort((a,b) => b[1].v - a[1].v)
        .slice(0,10);

    const vt = f.cerv.reduce((s,r) => s + r.$, 0);
    const qt = f.cerv.reduce((s,r) => s + r.q, 0);
    const top = top10[0] || ['—',{}];
    document.getElementById('kpiCerv').innerHTML = `
        <div class="kpi-card"><div class="kpi-label">Revenue Total</div><div class="kpi-value">${fmtM(vt)}</div></div>
        <div class="kpi-card"><div class="kpi-label">Unidades</div><div class="kpi-value">${fmtK(qt)}</div></div>
        <div class="kpi-card"><div class="kpi-label">Top Estilo</div><div class="kpi-value">${top[0]}</div><div style="font-size:12px;color:#999;">Rev: ${fmtM(top[1].v || 0)}</div></div>
    `;

    makeChart('chartCervTop', {
        type:'bar',
        data:{
            labels:top10.map(x => x[0]),
            datasets:[{
                label:'Revenue',
                data:top10.map(x => x[1].v),
                backgroundColor:C.azul
            }]
        },
        options:{
            indexAxis:'y',
            responsive:true,
            plugins:{legend:{display:false}},
            scales:{x:{ticks:{callback:v => fmtM(v)}}}
        }
    });

    const catTotals = {};
    f.cerv.forEach(r => {
        catTotals[r.cat] = (catTotals[r.cat] || 0) + r.$;
    });
    const catTop = Object.entries(catTotals)
        .sort((a,b) => b[1] - a[1])
        .slice(0,8);
    makeChart('chartCervCat', {
        type:'doughnut',
        data:{
            labels:catTop.map(x => x[0]),
            datasets:[{
                data:catTop.map(x => x[1]),
                backgroundColor:C.charts
            }]
        },
        options:{
            responsive:true,
            plugins:{
                legend:{position:'right'},
                tooltip:{callbacks:{label:ctx => fmtM(ctx.parsed)}}
            }
        }
    });
}

function updateCervTable(f) {
    const rows = f.cerv
        .map(r => ({s:r.s, cat:r.cat, q:r.q, v:r.$, pct:0}))
        .reduce((acc,r) => {
            const existing = acc.find(x => x.s === r.s && x.cat === r.cat);
            if (existing) {existing.q += r.q; existing.v += r.v;} else {acc.push(r);}
            return acc;
        }, [])
        .sort((a,b) => b.v - a.v)
        .slice(0,20);

    const total = rows.reduce((s,r) => s + r.v, 0);
    rows.forEach(r => {r.pct = ((r.v/total)*100).toFixed(1);});

    const html = `
        <thead><tr>
            <th>Estilo</th><th>Categoría</th><th>Cantidad</th><th>Revenue</th><th>% del Total</th>
        </tr></thead>
        <tbody>
        ${rows.map(r => `
            <tr>
                <td><strong>${r.s}</strong></td>
                <td>${r.cat}</td>
                <td>${r.q}</td>
                <td>${fmtM(r.v)}</td>
                <td>${r.pct}%</td>
            </tr>
        `).join('')}
        </tbody>
    `;
    document.getElementById('tableCerv').innerHTML = html;
}

function updateGinCharts(f) {
    const ginTotals = {};
    f.gin.forEach(r => {
        if (!ginTotals[r.p]) ginTotals[r.p] = {v:0, q:0, l:0};
        ginTotals[r.p].v += r.$;
        ginTotals[r.p].q += r.q;
        ginTotals[r.p].l += r.l;
    });

    const top10 = Object.entries(ginTotals)
        .sort((a,b) => b[1].v - a[1].v)
        .slice(0,10);

    const vt = f.gin.reduce((s,r) => s + r.$, 0);
    const qt = f.gin.reduce((s,r) => s + r.q, 0);
    const lt = f.gin.reduce((s,r) => s + r.l, 0);
    const top = top10[0] || ['—',{}];

    document.getElementById('kpiGin').innerHTML = `
        <div class="kpi-card"><div class="kpi-label">Revenue Total</div><div class="kpi-value">${fmtM(vt)}</div></div>
        <div class="kpi-card"><div class="kpi-label">Litros</div><div class="kpi-value">${lt.toFixed(1)}</div></div>
        <div class="kpi-card"><div class="kpi-label">Top Producto</div><div class="kpi-value">${top[0].substring(0,15)}</div><div style="font-size:12px;color:#999;">Rev: ${fmtM(top[1].v || 0)}</div></div>
    `;

    makeChart('chartGinTop', {
        type:'bar',
        data:{
            labels:top10.map(x => x[0].substring(0,25)),
            datasets:[{
                label:'Revenue',
                data:top10.map(x => x[1].v),
                backgroundColor:C.verde
            }]
        },
        options:{
            indexAxis:'y',
            responsive:true,
            plugins:{legend:{display:false}},
            scales:{x:{ticks:{callback:v => fmtM(v)}}}
        }
    });
}

function updateGinTable(f) {
    const rows = f.gin
        .map(r => ({p:r.p, q:r.q, l:r.l, v:r.$, pct:0}))
        .reduce((acc,r) => {
            const existing = acc.find(x => x.p === r.p);
            if (existing) {existing.q += r.q; existing.l += r.l; existing.v += r.v;} else {acc.push(r);}
            return acc;
        }, [])
        .sort((a,b) => b.v - a.v)
        .slice(0,20);

    const total = rows.reduce((s,r) => s + r.v, 0);
    rows.forEach(r => {r.pct = ((r.v/total)*100).toFixed(1);});

    const html = `
        <thead><tr>
            <th>Producto</th><th>Cantidad</th><th>Litros</th><th>Revenue</th><th>% del Total</th>
        </tr></thead>
        <tbody>
        ${rows.map(r => `
            <tr>
                <td><strong>${r.p}</strong></td>
                <td>${r.q}</td>
                <td>${r.l.toFixed(2)}</td>
                <td>${fmtM(r.v)}</td>
                <td>${r.pct}%</td>
            </tr>
        `).join('')}
        </tbody>
    `;
    document.getElementById('tableGin').innerHTML = html;
}

function updateFeridCharts(f) {
    const feridTotals = {};
    f.ferid.forEach(r => {
        if (!feridTotals[r.p]) feridTotals[r.p] = {v:0, q:0};
        feridTotals[r.p].v += r.$;
        feridTotals[r.p].q += r.q;
    });

    const top10 = Object.entries(feridTotals)
        .sort((a,b) => b[1].v - a[1].v)
        .slice(0,10);

    const vt = f.ferid.reduce((s,r) => s + r.$, 0);
    const qt = f.ferid.reduce((s,r) => s + r.q, 0);
    const top = top10[0] || ['—',{}];

    document.getElementById('kpiFerid').innerHTML = `
        <div class="kpi-card"><div class="kpi-label">Revenue Total</div><div class="kpi-value">${fmtM(vt)}</div></div>
        <div class="kpi-card"><div class="kpi-label">Unidades</div><div class="kpi-value">${fmtK(qt)}</div></div>
        <div class="kpi-card"><div class="kpi-label">Top Producto</div><div class="kpi-value">${top[0].substring(0,15)}</div><div style="font-size:12px;color:#999;">Rev: ${fmtM(top[1].v || 0)}</div></div>
    `;

    makeChart('chartFeridTop', {
        type:'bar',
        data:{
            labels:top10.map(x => x[0].substring(0,25)),
            datasets:[{
                label:'Revenue',
                data:top10.map(x => x[1].v),
                backgroundColor:C.amarillo
            }]
        },
        options:{
            indexAxis:'y',
            responsive:true,
            plugins:{legend:{display:false}},
            scales:{x:{ticks:{callback:v => fmtM(v)}}}
        }
    });
}

function updateFeridTable(f) {
    const rows = f.ferid
        .map(r => ({p:r.p, q:r.q, v:r.$, pct:0}))
        .reduce((acc,r) => {
            const existing = acc.find(x => x.p === r.p);
            if (existing) {existing.q += r.q; existing.v += r.v;} else {acc.push(r);}
            return acc;
        }, [])
        .sort((a,b) => b.v - a.v)
        .slice(0,20);

    const total = rows.reduce((s,r) => s + r.v, 0);
    rows.forEach(r => {r.pct = ((r.v/total)*100).toFixed(1);});

    const html = `
        <thead><tr>
            <th>Producto</th><th>Cantidad</th><th>Revenue</th><th>% del Total</th>
        </tr></thead>
        <tbody>
        ${rows.map(r => `
            <tr>
                <td><strong>${r.p}</strong></td>
                <td>${r.q}</td>
                <td>${fmtM(r.v)}</td>
                <td>${r.pct}%</td>
            </tr>
        `).join('')}
        </tbody>
    `;
    document.getElementById('tableFerid').innerHTML = html;
}

function updateMixCharts(f) {
    const mixTotals = {};
    f.mix.forEach(r => {
        if (!mixTotals[r.m]) mixTotals[r.m] = {v:0, q:0};
        mixTotals[r.m].v += r.$;
        mixTotals[r.m].q += r.q;
    });

    const vt = f.mix.reduce((s,r) => s + r.$, 0);
    const qt = f.mix.reduce((s,r) => s + r.q, 0);
    const top = Object.entries(mixTotals).sort((a,b) => b[1].v - a[1].v)[0] || ['—',{}];

    document.getElementById('kpiMix').innerHTML = `
        <div class="kpi-card"><div class="kpi-label">Revenue Total</div><div class="kpi-value">${fmtM(vt)}</div></div>
        <div class="kpi-card"><div class="kpi-label">Unidades</div><div class="kpi-value">${fmtK(qt)}</div></div>
        <div class="kpi-card"><div class="kpi-label">Top Categoría</div><div class="kpi-value">${top[0]}</div><div style="font-size:12px;color:#999;">Rev: ${fmtM(top[1].v || 0)}</div></div>
    `;

    const catTop = Object.entries(mixTotals)
        .sort((a,b) => b[1].v - a[1].v)
        .slice(0,8);
    makeChart('chartMixCat', {
        type:'doughnut',
        data:{
            labels:catTop.map(x => x[0]),
            datasets:[{
                data:catTop.map(x => x[1].v),
                backgroundColor:C.charts
            }]
        },
        options:{
            responsive:true,
            plugins:{
                legend:{position:'right'},
                tooltip:{callbacks:{label:ctx => fmtM(ctx.parsed)}}
            }
        }
    });

    const prodTotals = {};
    f.mix.forEach(r => {
        const key = r.e + ' - ' + r.m;
        if (!prodTotals[key]) prodTotals[key] = {v:0, q:0};
        prodTotals[key].v += r.$;
        prodTotals[key].q += r.q;
    });
    const prodTop = Object.entries(prodTotals)
        .sort((a,b) => b[1].v - a[1].v)
        .slice(0,15);

    makeChart('chartMixTop', {
        type:'bar',
        data:{
            labels:prodTop.map(x => x[0].substring(0,30)),
            datasets:[{
                label:'Revenue',
                data:prodTop.map(x => x[1].v),
                backgroundColor:C.charts[0]
            }]
        },
        options:{
            indexAxis:'y',
            responsive:true,
            plugins:{legend:{display:false}},
            scales:{x:{ticks:{callback:v => fmtM(v)}}}
        }
    });
}

function updateMixTable(f) {
    const rows = f.mix
        .map(r => ({m:r.m, e:r.e, q:r.q, v:r.$, pct:0}))
        .reduce((acc,r) => {
            const existing = acc.find(x => x.m === r.m && x.e === r.e);
            if (existing) {existing.q += r.q; existing.v += r.v;} else {acc.push(r);}
            return acc;
        }, [])
        .sort((a,b) => b.v - a.v)
        .slice(0,30);

    const total = rows.reduce((s,r) => s + r.v, 0);
    rows.forEach(r => {r.pct = ((r.v/total)*100).toFixed(1);});

    const html = `
        <thead><tr>
            <th>Producto</th><th>Categoría</th><th>Establecimiento</th><th>Cantidad</th><th>Revenue</th><th>% del Total</th>
        </tr></thead>
        <tbody>
        ${rows.map(r => `
            <tr>
                <td><strong>${r.m}</strong></td>
                <td>${r.m}</td>
                <td>${r.e}</td>
                <td>${r.q}</td>
                <td>${fmtM(r.v)}</td>
                <td>${r.pct}%</td>
            </tr>
        `).join('')}
        </tbody>
    `;
    document.getElementById('tableMix').innerHTML = html;
}

function updateAll() {
    try {
        const f = getFiltered();
        const pv = getPrevFiltered();

        updateKPIs(f, pv);
        updateResumenCharts(f);
        updateEstabTable(f.ventas, pv);
        updateAlerts(f, pv);
        updateCervCharts(f);
        updateCervTable(f);
        updateGinCharts(f);
        updateGinTable(f);
        updateFeridCharts(f);
        updateFeridTable(f);
        updateMixCharts(f);
        updateMixTable(f);
    } catch (e) {
        console.error('Update error', e);
    }
}

function initDarkMode() {
    const saved = localStorage.getItem('darkMode') === 'true';
    state.darkMode = saved;
    if (saved) document.body.classList.add('dark');

    document.getElementById('btnDark').onclick = () => {
        state.darkMode = !state.darkMode;
        document.body.classList.toggle('dark');
        localStorage.setItem('darkMode', state.darkMode);
    };
}

function initDatePicker() {
    const minDate = Math.min(...RAW.ventas.map(r => new Date(r.d).getTime()));
    const maxDate = Math.max(...RAW.ventas.map(r => new Date(r.d).getTime()));

    const d2 = new Date(maxDate);
    const d1 = new Date(d2);
    d1.setDate(d1.getDate() - 29);

    const defaultStart = d1.toISOString().split('T')[0];
    const defaultEnd = d2.toISOString().split('T')[0];

    state.d1 = defaultStart;
    state.d2 = defaultEnd;

    flatpickr('#dateRange', {
        mode:'range',
        dateFormat:'Y-m-d',
        defaultDate:[defaultStart, defaultEnd],
        onChange: function(selectedDates) {
            if (selectedDates.length === 2) {
                state.d1 = selectedDates[0].toISOString().split('T')[0];
                state.d2 = selectedDates[1].toISOString().split('T')[0];
                updateAll();
            }
        }
    });
}

function initTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const tabId = btn.getAttribute('data-tab');
            document.getElementById(tabId).classList.add('active');
        });
    });
}

async function initData() {
    const overlay = document.getElementById('loadingOverlay');
    try {
        const resp = await fetch('/api/data');
        if (!resp.ok) {
            overlay.innerHTML = `<div class="loading-error">Error cargando datos (${resp.status}).<br><a href="/login">Reiniciar sesión</a></div>`;
            return;
        }
        RAW = await resp.json();

        // Derive canal and turno from ventas (not returned by API separately)
        RAW.canal = RAW.ventas.map(r => ({d:r.d, c:r.c, o:r.o}));
        RAW.turno = RAW.ventas.map(r => ({d:r.d, t:r.t, v:r.v}));

        // Build estabSelect dynamically from actual data
        const estabs = Array.from(new Set(RAW.ventas.map(r => r.e))).sort();
        const sel = document.getElementById('estabSelect');
        sel.innerHTML = '<option value="ALL">Todos los establecimientos</option>';
        estabs.forEach(e => {
            const opt = document.createElement('option');
            opt.value = e;
            opt.textContent = e;
            sel.appendChild(opt);
        });

        // Wire up estabSelect onChange (was missing in original)
        sel.addEventListener('change', e => {
            state.estab = e.target.value;
            updateAll();
        });

        // Show last_updated in ART (UTC-3)
        if (RAW.last_updated) {
            const lu = new Date(RAW.last_updated);
            const artStr = lu.toLocaleString('es-AR', {timeZone:'America/Argentina/Buenos_Aires'});
            const el = document.getElementById('lastUpdated');
            if (el) el.textContent = 'Actualizado: ' + artStr;
        }

        overlay.style.display = 'none';
        initDatePicker();
        updateAll();
    } catch (err) {
        console.error('initData error', err);
        overlay.innerHTML = '<div class="loading-error">Error de conexión.<br><a href="/login">Reiniciar sesión</a></div>';
    }
}

// ---------------------------------------------------------------------------
// CSV export
// ---------------------------------------------------------------------------

function exportCSV(filename, rows, headers) {
    const escape = v => {
        const s = String(v === null || v === undefined ? '' : v);
        return s.includes(',') || s.includes('"') || s.includes('\n')
            ? '"' + s.replace(/"/g, '""') + '"'
            : s;
    };
    const lines = [headers.join(',')].concat(rows.map(r => r.map(escape).join(',')));
    const blob = new Blob(['\uFEFF' + lines.join('\r\n')], {type:'text/csv;charset=utf-8;'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

function exportResumen() {
    const f = getFiltered();
    const rows = f.ventas.map(r => [r.d, r.e, r.c, r.t, r.o, r.v, r.tk]);
    exportCSV('resumen.csv', rows, ['Fecha','Establecimiento','Canal','Turno','Ordenes','Ventas','Ticket']);
}

function exportCerv() {
    const f = getFiltered();
    const rows = f.cerv.map(r => [r.d, r.s, r.cat, r.e, r.q, r.$]);
    exportCSV('cervezas.csv', rows, ['Fecha','Estilo','Categoria','Establecimiento','Cantidad','Revenue']);
}

function exportGin() {
    const f = getFiltered();
    const rows = f.gin.map(r => [r.d, r.p, r.e, r.q, r.l, r.$]);
    exportCSV('gin.csv', rows, ['Fecha','Producto','Establecimiento','Cantidad','Litros','Revenue']);
}

function exportFerid() {
    const f = getFiltered();
    const rows = f.ferid.map(r => [r.d, r.p, r.e, r.q, r.$]);
    exportCSV('feriado.csv', rows, ['Fecha','Producto','Establecimiento','Cantidad','Revenue']);
}

function exportMix() {
    const f = getFiltered();
    const rows = f.mix.map(r => [r.d, r.m, r.e, r.q, r.$]);
    exportCSV('productos.csv', rows, ['Fecha','Producto','Establecimiento','Cantidad','Revenue']);
}

document.getElementById('btnPrint').onclick = () => window.print();

document.addEventListener('DOMContentLoaded', () => {
    initDarkMode();
    initTabs();
    initData();
});
