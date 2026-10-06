(() => {
  const config = window.OBSERVER_CONFIG;
  let currentFilter = "all";
  let searchTimer;
  let participantList = [];
  let sortKey = null;
  let sortDirection = "asc";

  const rows = document.getElementById("participantRows");
  const search = document.getElementById("searchInput");
  const shiftFilter = document.getElementById("shiftFilter");
  const positionFilter = document.getElementById("positionFilter");
  const exportLink = document.getElementById("exportLink");

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, char => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
    }[char]));
  }

  function formatTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return escapeHtml(value);
    return date.toLocaleString("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
      second: "2-digit", hour12: false
    });
  }

  function updateSummary(summary) {
    document.getElementById("statTotal").textContent = summary.total;
    document.getElementById("statSigned").textContent = summary.signed;
    document.getElementById("statUnsigned").textContent = summary.unsigned;
    document.getElementById("statRate").textContent = `${summary.rate}%`;
    document.getElementById("rateBar").style.width = `${summary.rate}%`;
  }

  function syncGroupOptions(select, groups, allLabel) {
    const selected = select.value;
    select.innerHTML = "";
    const allOption = document.createElement("option");
    allOption.value = "";
    allOption.textContent = allLabel;
    select.appendChild(allOption);
    groups.forEach(group => {
      const option = document.createElement("option");
      option.value = group.value || "__empty__";
      option.textContent = `${group.label}（${group.signed}/${group.total}）`;
      select.appendChild(option);
    });
    if ([...select.options].some(option => option.value === selected)) select.value = selected;
  }

  function renderGroupList(containerId, groups, kind) {
    const container = document.getElementById(containerId);
    if (!groups.length) {
      container.innerHTML = '<div class="group-summary-empty">暂无分组数据</div>';
      return;
    }
    const selectedValue = kind === "shift" ? shiftFilter.value : positionFilter.value;
    container.innerHTML = groups.map(group => {
      const value = group.value || "__empty__";
      return `
      <button class="group-summary-item ${selectedValue === value ? "active" : ""}" type="button" data-group-kind="${kind}" data-group-value="${escapeHtml(value)}">
        <span><strong>${escapeHtml(group.label)}</strong><small>${group.late ? `迟到 ${group.late} 人` : "无迟到"}</small></span>
        <span class="group-attendance"><b>${group.signed}/${group.total}</b><small>${group.rate}%</small></span>
        <i><em style="width:${group.rate}%"></em></i>
      </button>
    `;
    }).join("");
  }

  function updateGroups(groups) {
    syncGroupOptions(shiftFilter, groups.shifts, "全部班次");
    syncGroupOptions(positionFilter, groups.positions, "全部岗位");
    renderGroupList("shiftGroupSummary", groups.shifts, "shift");
    renderGroupList("positionGroupSummary", groups.positions, "position");
  }

  function updateExportLink() {
    const params = new URLSearchParams();
    if (currentFilter !== "all") params.set("status", currentFilter);
    if (shiftFilter.value) params.set("shift", shiftFilter.value);
    if (positionFilter.value) params.set("position", positionFilter.value);
    if (search.value.trim()) params.set("q", search.value.trim());
    const query = params.toString();
    exportLink.href = query ? `${config.exportUrl}?${query}` : config.exportUrl;
  }

  function sortEntries(participants) {
    const entries = participants.map((person, sourceIndex) => ({ person, sourceIndex }));
    if (!sortKey) return entries;

    function valueFor(entry) {
      if (sortKey === "index") return entry.sourceIndex;
      if (sortKey === "source_note") {
        return [entry.person.source, entry.person.note].filter(Boolean).join(" ");
      }
      if (sortKey === "sign_time") {
        return entry.person.sign_time ? Date.parse(entry.person.sign_time) : null;
      }
      if (sortKey === "signed_in") return Number(Boolean(entry.person.signed_in));
      return entry.person[sortKey] ?? "";
    }

    entries.sort((left, right) => {
      const leftValue = valueFor(left);
      const rightValue = valueFor(right);
      const leftEmpty = leftValue === "" || leftValue === null || Number.isNaN(leftValue);
      const rightEmpty = rightValue === "" || rightValue === null || Number.isNaN(rightValue);
      if (leftEmpty !== rightEmpty) return leftEmpty ? 1 : -1;

      let comparison = 0;
      if (!leftEmpty) {
        comparison = typeof leftValue === "number"
          ? leftValue - rightValue
          : String(leftValue).localeCompare(String(rightValue), "zh-CN", { numeric: true, sensitivity: "base" });
      }
      if (comparison === 0) comparison = left.sourceIndex - right.sourceIndex;
      return sortDirection === "asc" ? comparison : -comparison;
    });
    return entries;
  }

  function updateSortHeaders() {
    document.querySelectorAll("[data-sort-column]").forEach(header => {
      const active = header.dataset.sortColumn === sortKey;
      header.setAttribute("aria-sort", active ? (sortDirection === "asc" ? "ascending" : "descending") : "none");
      const button = header.querySelector("[data-sort]");
      button.classList.toggle("active", active);
      button.querySelector("span").textContent = active ? (sortDirection === "asc" ? "↑" : "↓") : "↕";
    });
  }

  function locationCheckMarkup(person) {
    if (!person.signed_in) return '<span class="location-check muted">—</span>';
    if (person.location_status === "verified") {
      const distance = person.location_distance == null ? "—" : `${Math.round(person.location_distance)}m`;
      const accuracy = person.location_accuracy == null ? "—" : `精度 ${Math.round(person.location_accuracy)}m`;
      return `<span class="location-check verified">✓ 范围内<small>${distance} · ${accuracy}</small></span>`;
    }
    if (person.location_status === "manual") {
      return '<span class="location-check manual">人工补签</span>';
    }
    return '<span class="location-check muted">未启用</span>';
  }

  function attendanceStatusMarkup(person) {
    if (!person.signed_in) return '<span class="attendance-state muted">—</span>';
    if (person.attendance_status === "late") {
      return '<span class="attendance-state late">! 迟到</span>';
    }
    if (person.attendance_status === "manual") {
      return '<span class="attendance-state manual">◆ 管理员补签</span>';
    }
    return '<span class="attendance-state normal">✓ 正常签到</span>';
  }

  function renderParticipants(participants) {
    if (!participants.length) {
      rows.innerHTML = '<tr><td colspan="11" class="loading-cell">当前筛选条件下没有人员</td></tr>';
      return;
    }
    rows.innerHTML = sortEntries(participants).map(({ person, sourceIndex }, index) => {
      const signed = Boolean(person.signed_in);
      const rowNumber = sortKey === "index" ? sourceIndex + 1 : index + 1;
      const state = signed
        ? '<span class="check-state signed"><i><span>✓</span></i>已签到</span>'
        : '<span class="check-state unsigned"><i><span>!</span></i>未签到</span>';
      const source = [person.source, person.note].filter(Boolean).map(escapeHtml).join(" · ") || "—";
      return `<tr class="${signed ? "signed-row" : "unsigned-row"} ${person.attendance_status === "late" ? "late-row" : ""}">
        <td>${rowNumber}</td>
        <td class="person-name">${escapeHtml(person.name)}</td>
        <td class="person-id">${escapeHtml(person.identifier)}</td>
        <td>${escapeHtml(person.phone || "—")}</td>
        <td>${escapeHtml(person.shift || "—")}</td>
        <td>${escapeHtml(person.position || "—")}</td>
        <td>${state}</td>
        <td>${attendanceStatusMarkup(person)}</td>
        <td>${formatTime(person.sign_time)}</td>
        <td>${locationCheckMarkup(person)}</td>
        <td><div class="source-note">${source}</div></td>
      </tr>`;
    }).join("");
  }

  async function loadParticipants(showError = false) {
    const params = new URLSearchParams({
      status: currentFilter,
      q: search.value.trim(),
      shift: shiftFilter.value,
      position: positionFilter.value
    });
    try {
      const response = await fetch(`${config.participantsUrl}?${params}`, {
        headers: { "Accept": "application/json" }
      });
      if (!response.ok) throw new Error("载入失败");
      const data = await response.json();
      updateSummary(data.summary);
      updateGroups(data.groups);
      updateExportLink();
      participantList = data.participants;
      renderParticipants(participantList);
    } catch (error) {
      if (showError) {
        rows.innerHTML = '<tr><td colspan="11" class="loading-cell text-danger">名单载入失败，请刷新页面重试</td></tr>';
      }
    }
  }

  function applyFilter(filter) {
    currentFilter = filter;
    document.querySelectorAll("[data-filter]").forEach(item => {
      const selected = item.dataset.filter === currentFilter;
      item.classList.toggle("active", selected);
      item.setAttribute("aria-pressed", String(selected));
    });
    updateExportLink();
    loadParticipants(true);
  }

  document.querySelectorAll("[data-filter]").forEach(control => {
    control.addEventListener("click", () => applyFilter(control.dataset.filter));
  });

  document.querySelectorAll('.stat-card[data-filter]').forEach(card => {
    card.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        applyFilter(card.dataset.filter);
      }
    });
  });

  document.querySelectorAll("[data-sort]").forEach(button => {
    button.addEventListener("click", () => {
      const nextKey = button.dataset.sort;
      if (sortKey === nextKey) {
        sortDirection = sortDirection === "asc" ? "desc" : "asc";
      } else {
        sortKey = nextKey;
        sortDirection = "asc";
      }
      updateSortHeaders();
      renderParticipants(participantList);
    });
  });

  search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    updateExportLink();
    searchTimer = window.setTimeout(() => loadParticipants(true), 260);
  });

  [shiftFilter, positionFilter].forEach(select => {
    select.addEventListener("change", () => {
      updateExportLink();
      loadParticipants(true);
    });
  });

  document.querySelector(".group-summary-panel").addEventListener("click", event => {
    const button = event.target.closest("[data-group-kind]");
    if (!button) return;
    const select = button.dataset.groupKind === "shift" ? shiftFilter : positionFilter;
    select.value = button.dataset.groupValue;
    updateExportLink();
    loadParticipants(true);
  });

  loadParticipants(true);
  window.setInterval(() => loadParticipants(false), 5000);
})();
