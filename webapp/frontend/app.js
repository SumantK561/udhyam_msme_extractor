const API_BASE = "/api";

const state = {
  page: 1,
  pageSize: 20,
  hasNext: false,
  hasPrev: false,
  totalPages: 1,
  hasSearched: false,
};

const els = {
  form: document.getElementById("search-form"),
  name: document.getElementById("name"),
  stateSelect: document.getElementById("state"),
  districtSelect: document.getElementById("district"),
  nicSelect: document.getElementById("nic_code"),
  status: document.getElementById("status"),
  resultsBar: document.getElementById("results-bar"),
  resultsCount: document.getElementById("results-count"),
  pageSizeSelect: document.getElementById("page-size"),
  table: document.getElementById("results-table"),
  tbody: document.getElementById("results-body"),
  pagination: document.getElementById("pagination"),
  prevBtn: document.getElementById("prev-page"),
  nextBtn: document.getElementById("next-page"),
  pageNumbers: document.getElementById("page-numbers"),
  modal: document.getElementById("detail-modal"),
  closeModal: document.getElementById("close-modal"),
  detailName: document.getElementById("detail-name"),
  detailMsmeBadge: document.getElementById("detail-msme-badge"),
  detailAddress: document.getElementById("detail-address"),
  detailState: document.getElementById("detail-state"),
  detailDistrict: document.getElementById("detail-district"),
  detailCountry: document.getElementById("detail-country"),
  detailRegistration: document.getElementById("detail-registration"),
  detailActivities: document.getElementById("detail-activities"),
};

async function loadStates() {
  const res = await fetch(`${API_BASE}/meta/states`);
  const states = await res.json();
  for (const s of states) {
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = s;
    els.stateSelect.appendChild(opt);
  }
}

async function loadNicCodes() {
  const res = await fetch(`${API_BASE}/meta/nic-codes`);
  const codes = await res.json();
  for (const c of codes) {
    const opt = document.createElement("option");
    opt.value = c.nic_code;
    opt.textContent = c.nic_description ? `${c.nic_code} — ${c.nic_description}` : c.nic_code;
    els.nicSelect.appendChild(opt);
  }
}

async function loadDistricts(stateName) {
  els.districtSelect.innerHTML = '<option value="">All districts</option>';
  if (!stateName) {
    els.districtSelect.disabled = true;
    return;
  }
  els.districtSelect.disabled = false;
  const res = await fetch(`${API_BASE}/meta/districts?state=${encodeURIComponent(stateName)}`);
  const districts = await res.json();
  for (const d of districts) {
    const opt = document.createElement("option");
    opt.value = d;
    opt.textContent = d;
    els.districtSelect.appendChild(opt);
  }
}

function buildSearchParams() {
  const params = new URLSearchParams();
  const name = els.name.value.trim();
  if (name) params.set("name", name);
  if (els.stateSelect.value) params.set("state", els.stateSelect.value);
  if (els.districtSelect.value) params.set("district", els.districtSelect.value);
  if (els.nicSelect.value) params.set("nic_code", els.nicSelect.value);
  params.set("page", state.page);
  params.set("page_size", state.pageSize);
  return params;
}

async function runSearch() {
  const name = els.name.value.trim();
  if (!name && !els.stateSelect.value && !els.districtSelect.value && !els.nicSelect.value) {
    els.status.textContent = "Enter an enterprise name or choose a filter to search.";
    els.table.classList.add("hidden");
    els.pagination.classList.add("hidden");
    els.resultsBar.classList.add("hidden");
    return;
  }
  if (name && name.length < 2) {
    els.status.textContent = "Enter at least 2 characters to search by name.";
    return;
  }

  state.hasSearched = true;
  els.status.textContent = "Searching…";
  els.table.classList.add("hidden");
  els.pagination.classList.add("hidden");
  els.resultsBar.classList.add("hidden");

  try {
    const params = buildSearchParams();
    const res = await fetch(`${API_BASE}/search?${params.toString()}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      els.status.textContent = err.detail || "Search failed. Try again.";
      return;
    }
    const data = await res.json();
    renderResults(data);
  } catch (e) {
    els.status.textContent = "Search failed. Try again.";
  }
}

function buildPageList(current, total) {
  const pages = new Set([1, total, current, current - 1, current + 1]);
  const sorted = [...pages].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b);

  const result = [];
  let prev = null;
  for (const p of sorted) {
    if (prev !== null && p - prev > 1) result.push("…");
    result.push(p);
    prev = p;
  }
  return result;
}

function renderPageNumbers(current, total) {
  els.pageNumbers.innerHTML = "";
  for (const p of buildPageList(current, total)) {
    if (p === "…") {
      const span = document.createElement("span");
      span.className = "page-ellipsis";
      span.textContent = "…";
      els.pageNumbers.appendChild(span);
      continue;
    }
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "page-num" + (p === current ? " active" : "");
    btn.textContent = p;
    btn.addEventListener("click", () => {
      if (p !== state.page) {
        state.page = p;
        runSearch();
      }
    });
    els.pageNumbers.appendChild(btn);
  }
}

function renderResults(data) {
  els.tbody.innerHTML = "";
  state.page = data.page;
  state.hasNext = data.has_next;
  state.hasPrev = data.has_prev;
  state.totalPages = data.total_pages;

  els.resultsBar.classList.remove("hidden");
  els.resultsCount.textContent =
    data.total === 0 ? "No results found." : `${data.total.toLocaleString("en-IN")} result(s) found`;

  if (data.results.length === 0) {
    els.status.textContent = "";
    els.table.classList.add("hidden");
    els.pagination.classList.add("hidden");
    return;
  }

  els.status.textContent = "";
  els.table.classList.remove("hidden");
  els.pagination.classList.remove("hidden");
  els.prevBtn.disabled = !data.has_prev;
  els.nextBtn.disabled = !data.has_next;
  renderPageNumbers(data.page, data.total_pages);

  for (const row of data.results) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(row.enterprise_name)}</td>
      <td>${escapeHtml(row.state_name || "")}</td>
      <td>${escapeHtml(row.district_name || "")}</td>
      <td>${escapeHtml(row.pincode || "")}</td>
      <td>${escapeHtml(row.registration_date || "")}</td>
    `;
    tr.addEventListener("click", () => showDetail(row.enterprise_key));
    els.tbody.appendChild(tr);
  }
}

async function showDetail(enterpriseKey) {
  const res = await fetch(`${API_BASE}/enterprise/${encodeURIComponent(enterpriseKey)}`);
  if (!res.ok) return;
  const d = await res.json();

  els.detailName.textContent = d.enterprise_name;

  if (d.msme) {
    els.detailMsmeBadge.classList.remove("hidden");
  } else {
    els.detailMsmeBadge.classList.add("hidden");
  }

  els.detailAddress.textContent = d.communication_address || "—";
  els.detailState.textContent = d.state_name || "—";
  els.detailDistrict.textContent = d.district_name
    ? d.pincode ? `${d.district_name} (${d.pincode})` : d.district_name
    : "—";
  els.detailCountry.textContent = d.country || "—";
  els.detailRegistration.textContent = d.registration_date || "—";

  els.detailActivities.innerHTML = "";
  if (d.activities.length === 0) {
    const li = document.createElement("li");
    li.className = "no-activities";
    li.textContent = "No NIC activities on record.";
    els.detailActivities.appendChild(li);
  }
  for (const a of d.activities) {
    const li = document.createElement("li");
    li.textContent = a.nic_description ? `${a.nic_code} — ${a.nic_description}` : a.nic_code;
    els.detailActivities.appendChild(li);
  }

  els.modal.classList.remove("hidden");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

els.form.addEventListener("submit", (e) => {
  e.preventDefault();
  state.page = 1;
  runSearch();
});

els.stateSelect.addEventListener("change", () => {
  loadDistricts(els.stateSelect.value);
});

els.prevBtn.addEventListener("click", () => {
  if (state.hasPrev) {
    state.page -= 1;
    runSearch();
  }
});

els.nextBtn.addEventListener("click", () => {
  if (state.hasNext) {
    state.page += 1;
    runSearch();
  }
});

els.pageSizeSelect.addEventListener("change", () => {
  state.pageSize = parseInt(els.pageSizeSelect.value, 10);
  state.page = 1;
  if (state.hasSearched) runSearch();
});

els.closeModal.addEventListener("click", () => els.modal.classList.add("hidden"));
els.modal.addEventListener("click", (e) => {
  if (e.target === els.modal) els.modal.classList.add("hidden");
});

loadStates();
loadNicCodes();

// ── Tabs ──────────────────────────────────────────────────────────────────

const tabButtons = document.querySelectorAll(".tab-btn");
const tabPanels = {
  search: document.getElementById("tab-search"),
  analytics: document.getElementById("tab-analytics"),
};

tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    tabButtons.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");

    Object.values(tabPanels).forEach((panel) => panel.classList.add("hidden"));
    tabPanels[btn.dataset.tab].classList.remove("hidden");

    if (btn.dataset.tab === "analytics" && window.loadAnalytics) {
      window.loadAnalytics();
    }
  });
});
