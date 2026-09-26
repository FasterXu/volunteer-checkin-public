(() => {
  const config = window.OBSERVER_CONFIG;
  let currentFilter = "all";
  let searchTimer;
  let participantList = [];
  let sortKey = null;
  let sortDirection = "asc";

  const rows = document.getElementById("participantRows");
  const search = document.getElementById("searchInput");
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

  function renderParticipants(participants) {
    if (!participants.length) {
      rows.innerHTML = '<tr><td colspan="8" class="loading-cell">当前筛选条件下没有人员</td></tr>';
      return;
    }
    rows.innerHTML = sortEntries(participants).map(({ person, sourceIndex }, index) => {
      const signed = Boolean(person.signed_in);
      const rowNumber = sortKey === "index" ? sourceIndex + 1 : index + 1;
      const state = signed
        ? '<span class="check-state signed"><i><span>✓</span></i>已签到</span>'
        : '<span class="check-state unsigned"><i><span>!</span></i>未签到</span>';
      const source = [person.source, person.note].filter(Boolean).map(escapeHtml).join(" · ") || "—";
      return `<tr class="${signed ? "signed-row" : "unsigned-row"}">
        <td>${rowNumber}</td>
        <td class="person-name">${escapeHtml(person.name)}</td>
        <td class="person-id">${escapeHtml(person.identifier)}</td>
        <td>${escapeHtml(person.phone || "—")}</td>
        <td>${escapeHtml(person.position || "—")}</td>
        <td>${state}</td>
        <td>${formatTime(person.sign_time)}</td>
        <td><div class="source-note">${source}</div></td>
      </tr>`;
    }).join("");
  }

  async function loadParticipants(showError = false) {
    const params = new URLSearchParams({ status: currentFilter, q: search.value.trim() });
    try {
      const response = await fetch(`${config.participantsUrl}?${params}`, {
        headers: { "Accept": "application/json" }
      });
      if (!response.ok) throw new Error("载入失败");
      const data = await response.json();
      updateSummary(data.summary);
      participantList = data.participants;
      renderParticipants(participantList);
    } catch (error) {
      if (showError) {
        rows.innerHTML = '<tr><td colspan="8" class="loading-cell text-danger">名单载入失败，请刷新页面重试</td></tr>';
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
    exportLink.href = currentFilter === "unsigned"
      ? `${config.exportUrl}?status=unsigned`
      : config.exportUrl;
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
    searchTimer = window.setTimeout(() => loadParticipants(true), 260);
  });

  loadParticipants(true);
  window.setInterval(() => loadParticipants(false), 5000);
})();
