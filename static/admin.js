(() => {
  const config = window.SIGNIN_CONFIG;
  let currentFilter = "all";
  let searchTimer;
  let participantCache = new Map();
  let participantList = [];
  let sortKey = null;
  let sortDirection = "asc";

  const rows = document.getElementById("participantRows");
  const search = document.getElementById("searchInput");
  const exportLink = document.getElementById("exportLink");
  const participantDialog = document.getElementById("participantDialog");
  const participantEditForm = document.getElementById("participantEditForm");

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, char => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
    }[char]));
  }

  function formatTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return escapeHtml(value);
    return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
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
    participantCache = new Map(participants.map(person => [String(person.id), person]));
    if (!participants.length) {
      rows.innerHTML = '<tr><td colspan="9" class="loading-cell">当前筛选条件下没有人员</td></tr>';
      return;
    }
    rows.innerHTML = sortEntries(participants).map(({ person, sourceIndex }, index) => {
      const signed = Boolean(person.signed_in);
      const rowNumber = sortKey === "index" ? sourceIndex + 1 : index + 1;
      const state = signed
        ? '<span class="check-state signed"><i><span>✓</span></i>已签到</span>'
        : '<span class="check-state unsigned"><i><span>!</span></i>未签到</span>';
      const signAction = signed
        ? `<button class="btn btn-sm btn-outline-danger action-toggle" data-id="${person.id}" data-signed="false">取消</button>`
        : `<button class="btn btn-sm btn-outline-success action-toggle" data-id="${person.id}" data-signed="true">补签</button>`;
      const action = `<div class="record-actions">
        ${signAction}
        <button class="btn btn-sm btn-outline-secondary action-edit" data-id="${person.id}">修改</button>
        <button class="btn btn-sm btn-outline-danger action-delete" data-id="${person.id}">删除</button>
      </div>`;
      const source = [person.source, person.note].filter(Boolean).map(escapeHtml).join(" · ") || "—";
      return `<tr class="${signed ? "signed-row" : "unsigned-row"}">
        <td>${rowNumber}</td>
        <td class="person-name">${escapeHtml(person.name)}</td>
        <td class="person-id">${escapeHtml(person.identifier)}</td>
        <td class="d-none d-md-table-cell">${escapeHtml(person.phone || "—")}</td>
        <td>${escapeHtml(person.position || "—")}</td>
        <td>${state}</td>
        <td class="d-none d-sm-table-cell">${formatTime(person.sign_time)}</td>
        <td class="d-none d-lg-table-cell"><div class="source-note">${source}</div></td>
        <td>${action}</td>
      </tr>`;
    }).join("");
  }

  async function loadParticipants(showError = false) {
    const params = new URLSearchParams({ status: currentFilter, q: search.value.trim() });
    try {
      const response = await fetch(`${config.participantsUrl}?${params}`, { headers: { "Accept": "application/json" } });
      if (!response.ok) throw new Error("载入失败");
      const data = await response.json();
      updateSummary(data.summary);
      participantList = data.participants;
      renderParticipants(participantList);
    } catch (error) {
      if (showError) rows.innerHTML = '<tr><td colspan="9" class="loading-cell text-danger">名单载入失败，请刷新页面重试</td></tr>';
    }
  }

  function applyFilter(filter) {
    currentFilter = filter;
    document.querySelectorAll("[data-filter]").forEach(item => {
      const selected = item.dataset.filter === currentFilter;
      item.classList.toggle("active", selected);
      item.setAttribute("aria-pressed", String(selected));
    });
    exportLink.href = currentFilter === "unsigned" ? `${config.exportUrl}?status=unsigned` : config.exportUrl;
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
    searchTimer = setTimeout(() => loadParticipants(true), 260);
  });

  rows.addEventListener("click", async event => {
    const button = event.target.closest("button[data-id]");
    if (!button) return;
    const person = participantCache.get(button.dataset.id);
    if (!person) return;

    if (button.classList.contains("action-edit")) {
      document.getElementById("editParticipantId").value = person.id;
      document.getElementById("editParticipantName").value = person.name || "";
      document.getElementById("editParticipantIdentifier").value = person.identifier || "";
      document.getElementById("editParticipantPhone").value = person.phone || "";
      document.getElementById("editParticipantPosition").value = person.position || "";
      document.getElementById("editParticipantNote").value = person.note || "";
      document.getElementById("participantEditError").hidden = true;
      participantDialog.showModal();
      return;
    }

    if (button.classList.contains("action-delete")) {
      if (!window.confirm(`确定从本活动名单中删除“${person.name}”吗？\n此操作会同时删除其签到记录，且无法撤销。`)) return;
      button.disabled = true;
      try {
        const url = config.participantUrlPattern.replace(/\/0$/, `/${person.id}`);
        const response = await fetch(url, { method: "DELETE", headers: { "Accept": "application/json" } });
        if (!response.ok) throw new Error("删除失败");
        await loadParticipants(true);
      } catch (error) {
        window.alert("删除失败，请稍后重试。");
        button.disabled = false;
      }
      return;
    }

    if (button.classList.contains("action-toggle")) {
      const signing = button.dataset.signed === "true";
      const note = window.prompt(signing ? "补签备注（可留空）" : "取消签到原因（可留空）", "");
      if (note === null) return;
      button.disabled = true;
      try {
        const url = config.toggleUrlPattern.replace(/\/0\/toggle$/, `/${person.id}/toggle`);
        const response = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Accept": "application/json" },
          body: JSON.stringify({ signed: signing, note })
        });
        if (!response.ok) throw new Error("操作失败");
        await loadParticipants(true);
      } catch (error) {
        window.alert("操作失败，请稍后重试。");
        button.disabled = false;
      }
    }
  });

  participantEditForm.addEventListener("submit", async event => {
    event.preventDefault();
    const errorBox = document.getElementById("participantEditError");
    const submitButton = participantEditForm.querySelector('button[type="submit"]');
    const id = document.getElementById("editParticipantId").value;
    const payload = {
      name: document.getElementById("editParticipantName").value.trim(),
      identifier: document.getElementById("editParticipantIdentifier").value.trim(),
      phone: document.getElementById("editParticipantPhone").value.trim(),
      position: document.getElementById("editParticipantPosition").value.trim(),
      note: document.getElementById("editParticipantNote").value.trim()
    };
    errorBox.hidden = true;
    submitButton.disabled = true;
    try {
      const url = config.participantUrlPattern.replace(/\/0$/, `/${id}`);
      const response = await fetch(url, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(payload)
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || "修改失败");
      participantDialog.close();
      await loadParticipants(true);
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.hidden = false;
    } finally {
      submitButton.disabled = false;
    }
  });

  function closeParticipantDialog() {
    participantDialog.close();
  }
  document.getElementById("closeParticipantDialog").addEventListener("click", closeParticipantDialog);
  document.getElementById("cancelParticipantEdit").addEventListener("click", closeParticipantDialog);
  participantDialog.addEventListener("click", event => {
    if (event.target === participantDialog) closeParticipantDialog();
  });

  const qrButton = document.getElementById("toggleQr");
  qrButton.addEventListener("click", () => {
    const drawer = document.getElementById("qrDrawer");
    drawer.hidden = !drawer.hidden;
    qrButton.textContent = drawer.hidden ? "▦ 显示签到二维码" : "▦ 收起签到二维码";
  });

  const activityEditButton = document.getElementById("toggleActivityEdit");
  const activityEditDrawer = document.getElementById("activityEditDrawer");
  activityEditButton.addEventListener("click", () => {
    activityEditDrawer.hidden = !activityEditDrawer.hidden;
    activityEditButton.textContent = activityEditDrawer.hidden ? "✎ 修改活动信息" : "✎ 收起修改表单";
  });
  document.getElementById("cancelActivityEdit").addEventListener("click", () => {
    activityEditDrawer.hidden = true;
    activityEditButton.textContent = "✎ 修改活动信息";
  });

  const copyObserverButton = document.getElementById("copyObserverLink");
  copyObserverButton.addEventListener("click", async () => {
    const observerUrl = new URL(copyObserverButton.dataset.url, window.location.origin).href;
    try {
      await navigator.clipboard.writeText(observerUrl);
      const originalText = copyObserverButton.textContent;
      copyObserverButton.textContent = "已复制观察员链接";
      window.setTimeout(() => { copyObserverButton.textContent = originalText; }, 1800);
    } catch (error) {
      window.prompt("请复制观察员链接", observerUrl);
    }
  });

  loadParticipants(true);
  window.setInterval(() => loadParticipants(false), 5000);
})();
