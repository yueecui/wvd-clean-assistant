/* WVD 装备梳理 — 扫描控制台 */
const $ = (s) => document.querySelector(s);
let polling = null;

async function api(path, body) {
  const opt = body === undefined ? {} :
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const j = await r.json();
  if (j.error) throw new Error(j.error);
  return j;
}

/* ---------- 设备 ---------- */
async function refreshDevices() {
  const s = await api("/api/settings");
  $("#adbPath").value = s.adb || "";
  const sel = $("#serial");
  const cur = sel.value;
  sel.innerHTML = "";
  for (const d of s.devices) {
    const o = document.createElement("option");
    o.value = o.textContent = d;
    sel.appendChild(o);
  }
  if (s.serial && ![...sel.options].some((o) => o.value === s.serial)) {
    const o = document.createElement("option");
    o.value = o.textContent = s.serial;
    sel.appendChild(o);
  }
  sel.value = cur || s.serial || (sel.options[0] && sel.options[0].value) || "";
  $("#connState").textContent = s.devices.length ? "已连接" : "未发现设备";
  $("#connState").className = s.devices.length ? "ok" : "bad";
}

async function saveSettings() {
  await api("/api/settings", { adb: $("#adbPath").value, serial: $("#serial").value });
}

/* ---------- 扫描 ---------- */
async function start() {
  const btn = $("#btnStart");
  btn.disabled = true;
  try {
    await saveSettings();
    await api("/api/scan/start", { clear: true });
    $("#btnStop").disabled = false;
    poll();
  } catch (e) {
    $("#stat").textContent = "启动失败: " + e.message;
    btn.disabled = false;
  }
}

async function stop() {
  $("#btnStop").disabled = true;
  await api("/api/scan/stop", {});
}

function poll() {
  clearInterval(polling);
  polling = setInterval(tick, 800);
  tick();
}

async function tick() {
  try {
    const s = await api("/api/scan/status");
    render(s);
    if (!s.status.running) {
      clearInterval(polling);
      polling = null;
      $("#btnStart").disabled = false;
      $("#btnStop").disabled = true;
      if (s.status.phase === "done") await api("/api/scan/save", {});
    }
  } catch (e) {
    $("#stat").textContent = "状态获取失败: " + e.message;
  }
}

function render(s) {
  const st = s.status;
  const items = s.results || s.items || [];
  $("#barFill").style.width = st.running ? "100%" : (st.phase === "done" ? "100%" : "0%");
  $("#barFill").className = st.running ? "run" : "";
  $("#stat").textContent = st.running
    ? `扫描中 ${st.scanned} 件 · 当前: ${st.current || "…"}`
    : (st.error ? `错误: ${st.error}`
       : (st.phase === "done" ? `完成，共 ${items.length} 件` : "待开始"));
  $("#cnt").textContent = `(${items.length} 件)`;

  const tb = $("#rows");
  const near = tb.scrollHeight - tb.parentElement.scrollTop - tb.parentElement.clientHeight < 80;
  tb.innerHTML = items.map((it) => `<tr>
      <td>${it.idx ?? ""}</td>
      <td>${esc(it.name)}</td>
      <td class="st">${"★".repeat(it.stars || 0)}</td>
      <td>${esc((it.blessings || []).join(" / "))}</td>
      <td>${it.locked ? "🔒" : ""}</td>
    </tr>`).join("");
  if (near) tb.parentElement.scrollTop = tb.parentElement.scrollHeight;

  const log = (s.logs || []).join("\n");
  const pre = $("#log");
  const atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 40;
  pre.textContent = log;
  if (atBottom) pre.scrollTop = pre.scrollHeight;
}

const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---------- 事件 ---------- */
$("#btnStart").onclick = start;
$("#btnStop").onclick = stop;
$("#btnRefresh").onclick = refreshDevices;
$("#btnClear").onclick = async () => {
  if (confirm("清空已保存的扫描结果？")) { await api("/api/clear", {}); tick(); }
};

refreshDevices();
tick();
