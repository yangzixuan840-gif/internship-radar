const $ = selector => document.querySelector(selector);
const api = async (url, options) => {
  const response = await fetch(url, options);
  if (!response.ok) throw Error(await response.text());
  return response.json();
};
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[char]));

function renderProfile(profile) {
  $("#profile").innerHTML = `<div><span>身份</span><strong>${esc(profile.school)} · ${esc(profile.graduation)} 毕业</strong></div><div><span>可到岗</span><strong>${esc(profile.availability_start)} — ${esc(profile.availability_end)} · ${esc(profile.days_per_week)} 天/周</strong></div><div><span>地点</span><strong>${profile.priority_cities.map(esc).join("、")} 优先</strong></div><div><span>方向</span><strong>${profile.role_priority.slice(0, 3).map(esc).join(" → ")}</strong></div>`;
}

function populateCompanies(companies) {
  const selected = $("#company").value;
  $("#company").innerHTML = `<option value="">全部 ${companies.length} 家公司</option>${companies.map(c => `<option value="${esc(c.name)}">${esc(c.name)}${c.job_count ? `（${c.job_count}）` : ""}</option>`).join("")}`;
  $("#company").value = selected;
  $("#company-options").innerHTML = companies.map(c => `<option value="${esc(c.name)}"></option>`).join("");
}

async function load() {
  const query = new URLSearchParams({q: $("#search").value, status: $("#status").value, city_group: $("#city").value, company: $("#company").value});
  const [profile, dashboard, jobs, companies, alerts] = await Promise.all([api("/api/profile"), api("/api/dashboard"), api(`/api/jobs?${query}`), api("/api/companies"), api("/api/alerts")]);
  renderProfile(profile);
  populateCompanies(companies);
  const metrics = [["已收录职位", dashboard.total], ["高匹配 ≥75", dashboard.strong], ["待提醒", dashboard.pending_alerts], ["已投递", dashboard.applied], ["面试中", dashboard.interviewing], ["可同步官网", dashboard.active_sources], ["官网来源", dashboard.companies]];
  $("#stats").innerHTML = metrics.map(([label, number]) => `<div class="stat"><b>${number}</b><span>${label}</span></div>`).join("");
  $("#empty").hidden = jobs.length > 0;
  $("#alerts").hidden = alerts.length === 0;
  $("#alerts").innerHTML = alerts.length ? `<h2>发现 ${alerts.length} 条高匹配新岗位</h2><p>${alerts.slice(0, 3).map(item => `${esc(item.company)} · ${esc(item.title)}（${item.score} 分）`).join("<br>")}<br>提醒渠道尚未配置；请先查看官网链接后决定是否投递。</p>` : "";
  $("#jobs").innerHTML = jobs.map(job => `<article class="job"><div class="score">${job.score}</div><h3>${esc(job.title)}</h3><p class="meta">${esc(job.company)} · ${esc(job.city || "地点待确认")} · ${esc(job.source)}</p><p class="reason">${job.score_reasons.map(esc).join("<br>")}</p><div class="actions"><a href="${esc(job.url)}" target="_blank" rel="noopener">查看官网 ↗</a><button onclick="createKit(${job.id})">生成投递包</button><button onclick="setJob(${job.id}, '${job.favorite ? "favorite" : "status"}', '${job.favorite ? "false" : "true"}')">${job.favorite ? "取消收藏" : "收藏"}</button><button onclick="setJob(${job.id}, 'status', '已投递')">标记已投</button><button onclick="removeJob(${job.id})">删除</button></div></article>`).join("");
  $("#companies").innerHTML = companies.map(company => {
    const state = company.status === "active" ? "已接入同步" : "待适配";
    const count = company.job_count ? ` · 已入库 ${company.job_count} 条` : "";
    return `<div class="company"><a target="_blank" rel="noopener" href="${esc(company.careers_url)}">${esc(company.name)} ↗</a><small class="${company.status}">${state}${count} · ${esc(company.connector_note)}</small></div>`;
  }).join("");
}

window.setJob = async (id, key, value) => {
  await api(`/api/jobs/${id}`, {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify(key === "favorite" ? {favorite: value === "true"} : {status: value})});
  load();
};
window.removeJob = async id => {
  if (confirm("确认删除这条职位？")) {
    await api(`/api/jobs/${id}`, {method: "DELETE"});
    load();
  }
};
window.createKit = async jobId => {
  try {
    const result = await api(`/api/jobs/${jobId}/application-kit`, {method: "POST"});
    const kit = result.kit;
    alert(`投递包已生成（${kit.resume_name}）\n命中技能：${kit.matched_skills.join("、") || "待核对"}\n可能缺口：${kit.possible_gaps.join("、") || "未识别"}\n\n请先核对内容，再在官网手动确认提交。`);
  } catch (error) {
    alert(`无法生成投递包：${error.message}`);
  }
};

$("#search").oninput = load;
$("#company").onchange = load;
$("#city").onchange = load;
$("#status").onchange = load;
$("#add").onclick = () => $("#modal").showModal();
$("#resume").onclick = () => $("#resume-modal").showModal();
$("#sync").onclick = async () => {
  const button = $("#sync");
  button.disabled = true;
  button.textContent = "正在同步…";
  try {
    const result = await api("/api/sync", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
    alert(result.results.map(item => `${item.company}：${item.message}`).join("\n"));
    await load();
  } catch (error) {
    alert(`同步失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = "同步已接入官网";
  }
};
$("#jobForm").onsubmit = async event => {
  event.preventDefault();
  const job = Object.fromEntries(new FormData(event.target));
  for (const key of ["duration_weeks", "work_days"]) job[key] = job[key] ? Number(job[key]) : null;
  await api("/api/jobs", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(job)});
  $("#modal").close();
  event.target.reset();
  load();
};
$("#resumeForm").onsubmit = async event => {
  event.preventDefault();
  const form = new FormData(event.target);
  const resume = {name: form.get("name"), summary: form.get("summary"), skills: String(form.get("skills") || "").split(/[，,]/).map(item => item.trim()).filter(Boolean), is_default: form.get("is_default") === "on"};
  const saved = await api("/api/resumes", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(resume)});
  const file = form.get("file");
  if (file && file.size) await api(`/api/resumes/${saved.id}/file`, {method: "PUT", headers: {"Content-Type": "application/octet-stream", "filename": file.name}, body: file});
  $("#resume-modal").close();
  event.target.reset();
  alert("简历版本已保存在本机；生成投递包时会使用默认版本。");
};
load();
