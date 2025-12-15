(function () {
  const configEl = document.getElementById("presenter-config");
  if (!configEl) return;

  const sessionUuid = configEl.dataset.session;
  const wsPath = configEl.dataset.ws;
  const tallyUrl = configEl.dataset.tallyUrl;
  const closeBase = configEl.dataset.closeBase;
  const revealBase = configEl.dataset.revealBase;
  const hideBase = configEl.dataset.hideBase;
  const timerBase = configEl.dataset.timerBase;
  const previewBase = configEl.dataset.previewBase;

  const presenceEl = document.getElementById("presence");
  const votesEl = document.getElementById("votes-count");
  const tallyYes = document.getElementById("tally-yes");
  const tallyNo = document.getElementById("tally-no");
  const tallyAbstain = document.getElementById("tally-abstain");
  const openTitle = document.getElementById("open-title");
  const openBody = document.getElementById("open-body");
  const openStatus = document.getElementById("open-status");
  const openMeta = document.getElementById("open-meta");
  const timerEl = document.getElementById("open-timer");
  const closeForm = document.getElementById("close-form");
  const revealForm = document.getElementById("reveal-form");
  const hideForm = document.getElementById("hide-form");
  const timerInput = document.getElementById("timer-seconds");
  const timerSetBtn = document.getElementById("timer-set-btn");
  const timerExtendBtn = document.getElementById("timer-extend-btn");
  const resetButtons = document.querySelectorAll(".reset-votes-btn");
  const motionRows = Array.from(document.querySelectorAll(".motion-row"));
  const initialMotionScript = document.getElementById("presenter-initial-motion");
  const initialCountsScript = document.getElementById("presenter-initial-counts");

  let socket = null;
  let reconnectAttempts = 0;
  let heartbeatTimer = null;
  let tallyTimer = null;
  let autoCloseAt = null;
  let selectedMotionId = null;
  let openMotionId = null;
  let lastPreviewBroadcastId = null;

  const motionMap = new Map();
  const motionCounts = new Map();
  const selectionStorageKey = `presenter_selected_motion_${sessionUuid}`;

  function loadStoredSelection() {
    try {
      const raw = localStorage.getItem(selectionStorageKey);
      return raw ? parseInt(raw, 10) : null;
    } catch (err) {
      return null;
    }
  }

  function persistSelection(id) {
    try {
      if (id) {
        localStorage.setItem(selectionStorageKey, String(id));
      } else {
        localStorage.removeItem(selectionStorageKey);
      }
    } catch (err) {
      // storage failures are non-blocking
    }
  }

  function setOpenBody(text, visible = true) {
    if (!openBody) return;
    openBody.textContent = text || "";
    openBody.style.display = visible ? "" : "none";
  }

  function getCsrfToken() {
    const name = "csrftoken=";
    const cookies = document.cookie ? document.cookie.split(";") : [];
    for (const c of cookies) {
      const trimmed = c.trim();
      if (trimmed.startsWith(name)) {
        return decodeURIComponent(trimmed.slice(name.length));
      }
    }
    return "";
  }

  function normalizeCounts(counts) {
    return {
      yes: counts?.yes || 0,
      no: counts?.no || 0,
      abstain: counts?.abstain || 0,
    };
  }

  function motionRowById(id) {
    return motionRows.find((row) => parseInt(row.dataset.id, 10) === id);
  }

  function updateRowVotes(motionId, total) {
    const row = motionRowById(motionId);
    if (!row) return;
    row.dataset.votes = String(total);
  }

  function getVoteTotal(motionId) {
    const counts = motionCounts.get(motionId);
    if (counts) {
      const normalized = normalizeCounts(counts);
      return normalized.yes + normalized.no + normalized.abstain;
    }
    const row = motionRowById(motionId);
    if (!row) return 0;
    const dataTotal = parseInt(row.dataset.votes || "0", 10);
    return Number.isNaN(dataTotal) ? 0 : dataTotal;
  }

  function setCompletedBadge(motionId, completed) {
    const row = motionRowById(motionId);
    if (!row) return;
    row.dataset.completed = completed ? "true" : "false";
    const container = row.querySelector(".status-stack");
    if (!container) return;
    let badge = container.querySelector(".completed-tag");
    if (completed) {
      if (!badge) {
        badge = document.createElement("span");
        badge.className = "tag completed-tag";
        badge.textContent = "Completed";
        container.appendChild(badge);
      } else {
        badge.style.display = "inline-block";
      }
    } else if (badge) {
      badge.remove();
    }
  }

  function refreshCompletion(motionId) {
    const motion = motionMap.get(motionId);
    if (!motion) return;
    const total = getVoteTotal(motionId);
    const completed =
      motion.status === "closed" && !!motion.opened_at && !!motion.closed_at && total > 0;
    setCompletedBadge(motionId, completed);
  }

  function syncRowMeta(motion) {
    if (!motion || !motion.id) return;
    const row = motionRowById(motion.id);
    if (!row) return;
    if (motion.status) row.dataset.status = motion.status;
    if ("opened_at" in motion) row.dataset.openedAt = motion.opened_at || "";
    if ("closed_at" in motion) row.dataset.closedAt = motion.closed_at || "";
  }

  function setCountsForMotion(motionId, counts) {
    if (!motionId) return;
    const normalized = normalizeCounts(counts || {});
    motionCounts.set(motionId, normalized);
    const total = normalized.yes + normalized.no + normalized.abstain;
    updateRowVotes(motionId, total);
    const motion = motionMap.get(motionId);
    if (motion) motion.votes_count = total;
    if (selectedMotionId === motionId) {
      tallyYes.textContent = normalized.yes;
      tallyNo.textContent = normalized.no;
      tallyAbstain.textContent = normalized.abstain;
      votesEl.textContent = total;
    }
    refreshCompletion(motionId);
  }

  function updateForms(motion) {
    const hasMotion = !!motion;
    const isOpen = hasMotion && motion.status === "open";
    if (closeForm) {
      closeForm.action = hasMotion ? `${closeBase}${motion.id}/close/` : "#";
      closeForm.style.display = isOpen ? "inline-block" : "none";
      const btn = closeForm.querySelector("button");
      if (btn) btn.disabled = !isOpen;
    }
    if (revealForm) {
      revealForm.action = hasMotion ? `${revealBase}${motion.id}/reveal/` : "#";
      const btn = revealForm.querySelector("button");
      if (btn) btn.disabled = !hasMotion;
    }
    if (hideForm) {
      hideForm.action = hasMotion ? `${hideBase}${motion.id}/hide/` : "#";
      const btn = hideForm.querySelector("button");
      if (btn) btn.disabled = !hasMotion;
    }
    if (timerSetBtn) timerSetBtn.disabled = !isOpen;
    if (timerExtendBtn) timerExtendBtn.disabled = !isOpen;
    if (timerInput) timerInput.disabled = !isOpen;
  }

  function renderSelectedMotion(motion) {
    if (!motion) {
      openTitle.textContent = "Select a motion to preview";
      setOpenBody("Choose a motion from the list to view details and tallies.", true);
      openStatus.textContent = "";
      openMeta.textContent = "";
      timerEl.textContent = "";
      votesEl.textContent = "0";
      tallyYes.textContent = "0";
      tallyNo.textContent = "0";
      tallyAbstain.textContent = "0";
      updateForms(null);
      return;
    }
    openTitle.textContent = motion.title;
    const hasBody = !!(motion.body && String(motion.body).trim());
    setOpenBody(hasBody ? motion.body : "", hasBody);
    const status = (motion.status || "unknown").toLowerCase();
    const isOpen = status === "open";
    const isClosed = status === "closed";
    const lockNote =
      openMotionId && motion.id === openMotionId && isOpen
        ? "Selection locked while this motion is open."
        : "";
    openStatus.textContent = `Status: ${motion.status ? motion.status.toUpperCase() : "UNKNOWN"}`;
    if (isClosed) {
      openMeta.textContent = "Voting closed. Please wait for the moderator to open voting for the next motion.";
      timerEl.textContent = "Closed";
    } else {
      const metaText = motion.allow_vote_change
        ? "Vote changes allowed while open"
        : "Vote changes locked after first response";
      openMeta.textContent = lockNote ? `${metaText} — ${lockNote}` : metaText;
    }
    updateForms(motion);
    updateTimerState(motion);
    const counts = motionCounts.get(motion.id) || { yes: 0, no: 0, abstain: 0 };
    tallyYes.textContent = counts.yes || 0;
    tallyNo.textContent = counts.no || 0;
    tallyAbstain.textContent = counts.abstain || 0;
    votesEl.textContent = (counts.yes || 0) + (counts.no || 0) + (counts.abstain || 0);
  }

  function startHeartbeat() {
    if (heartbeatTimer) return;
    heartbeatTimer = setInterval(() => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "heartbeat" }));
      }
    }, 15000);
  }

  function stopHeartbeat() {
    if (heartbeatTimer) clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }

  function scheduleReconnect() {
    reconnectAttempts += 1;
    const delay = Math.min(15000, 3000 + reconnectAttempts * 1000);
    setTimeout(connectSocket, delay);
  }

  function connectSocket() {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${scheme}://${location.host}${wsPath}`);
    socket.onopen = () => {
      reconnectAttempts = 0;
      startHeartbeat();
      stopPollingTallies();
      if (selectedMotionId) {
        fetchTallies(selectedMotionId);
      }
    };
    socket.onclose = () => {
      stopHeartbeat();
      startPollingTallies();
      scheduleReconnect();
    };
    socket.onerror = () => socket.close();
    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleEvent(data.event, data.payload || {});
      } catch (err) {
        console.error("Bad WS payload", err);
      }
    };
  }

  function handleEvent(event, payload) {
    switch (event) {
      case "motion_opened":
        if (payload && payload.id) {
          const merged = { ...(motionMap.get(payload.id) || {}), ...payload, status: "open", closed_at: null };
          motionMap.set(payload.id, merged);
          syncRowMeta(merged);
          openMotionId = payload.id;
          lastPreviewBroadcastId = null;
          setCountsForMotion(payload.id, { yes: 0, no: 0, abstain: 0 });
          fetchTallies(payload.id);
          selectedMotionId = payload.id;
          persistSelection(selectedMotionId);
          highlightSelection();
          renderSelectedMotion(merged);
        }
        break;
      case "motion_closed":
        if (payload && payload.id) {
          const merged = { ...(motionMap.get(payload.id) || {}), ...payload, status: "closed" };
          motionMap.set(payload.id, merged);
          syncRowMeta(merged);
          if (openMotionId === payload.id) openMotionId = null;
          lastPreviewBroadcastId = null;
          setCountsForMotion(payload.id, payload.counts || motionCounts.get(payload.id) || {});
          if (selectedMotionId === payload.id) {
            renderSelectedMotion(merged);
          }
        }
        break;
      case "admin_vote_update":
        if (payload.motion_id) {
          setCountsForMotion(payload.motion_id, payload.counts || {});
        }
        break;
      case "presence_update":
        if (typeof payload.count === "number") {
          presenceEl.textContent = payload.count;
        }
        break;
      case "results_revealed":
        if (payload.counts) {
          setCountsForMotion(payload.motion_id || selectedMotionId, payload.counts);
        }
        break;
      case "timer_updated":
        if (payload.id) {
          const existingTimer = motionMap.get(payload.id) || {};
          const mergedTimer = { ...existingTimer, ...payload };
          motionMap.set(payload.id, mergedTimer);
          syncRowMeta(mergedTimer);
          if (selectedMotionId === payload.id) {
            renderSelectedMotion(motionMap.get(payload.id));
          }
        }
        break;
      case "heartbeat_ack":
        if (typeof payload.active_count === "number") {
          presenceEl.textContent = payload.active_count;
        }
        break;
      default:
        break;
    }
  }

  function startTimer() {
    if (!autoCloseAt) return;
    const tick = () => {
      const selected = selectedMotionId ? motionMap.get(selectedMotionId) : null;
      if (selected && selected.status === "closed") {
        timerEl.textContent = "Closed";
        return;
      }
      if (!autoCloseAt || !selected) {
        timerEl.textContent = "";
        return;
      }
      if (selected.status !== "open") {
        timerEl.textContent = selected.status === "closed" ? "Closed" : "";
        return;
      }
      const remaining = Math.max(0, autoCloseAt - Date.now());
      if (remaining <= 0) {
        timerEl.textContent = "Auto-closing.";
        if (closeForm) closeForm.submit();
        return;
      }
      const seconds = Math.ceil(remaining / 1000);
      timerEl.textContent = `Auto-close in ${seconds}s`;
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  function updateTimerState(motion) {
    autoCloseAt = null;
    if (motion && motion.status === "open" && motion.auto_close_seconds && motion.opened_at) {
      autoCloseAt = new Date(motion.opened_at).getTime() + motion.auto_close_seconds * 1000;
      startTimer();
    } else if (!motion || motion.status !== "closed") {
      timerEl.textContent = "";
    }
  }

  function highlightSelection() {
    motionRows.forEach((row) => {
      const rowId = parseInt(row.dataset.id, 10);
      if (selectedMotionId && rowId === selectedMotionId) {
        row.classList.add("selected");
      } else {
        row.classList.remove("selected");
      }
    });
  }

  function selectionLockedToOpen(id) {
    if (!openMotionId) return false;
    const openMotion = motionMap.get(openMotionId);
    return openMotion && openMotion.status === "open" && id !== openMotionId;
  }

  function selectMotion(id) {
    if (!id) return;
    if (selectionLockedToOpen(id)) {
      highlightSelection();
      return;
    }
    const motion = motionMap.get(id);
    if (!motion) return;
    selectedMotionId = id;
    persistSelection(selectedMotionId);
    highlightSelection();
    renderSelectedMotion(motion);
    broadcastPreviewSelection(motion);
    if (!motionCounts.get(id)) {
      fetchTallies(id);
    }
  }

  function shouldPreviewMotion(motion) {
    if (!motion) return false;
    if (openMotionId && motion.id !== openMotionId) return false;
    return true;
  }

  async function broadcastPreviewSelection(motion) {
    if (!previewBase || !shouldPreviewMotion(motion)) return;
    if (lastPreviewBroadcastId === motion.id) return;
    try {
      const res = await fetch(`${previewBase}${motion.id}/preview/`, {
        method: "POST",
        headers: {
          "X-CSRFToken": getCsrfToken(),
          "X-Requested-With": "XMLHttpRequest",
        },
      });
      if (!res.ok) {
        lastPreviewBroadcastId = null;
        return;
      }
      lastPreviewBroadcastId = motion.id;
    } catch (err) {
      // preview sync failures are non-blocking for moderator controls
      lastPreviewBroadcastId = null;
    }
  }

  function fetchTallies(motionId) {
    if (!motionId) return;
    fetch(`${tallyUrl}?motion_id=${motionId}`, { headers: { "Cache-Control": "no-cache" } })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!data || !data.motion_id) return;
        setCountsForMotion(data.motion_id, data.counts || {});
      })
      .catch(() => {});
  }

  function startPollingTallies() {
    if (tallyTimer) return;
    tallyTimer = setInterval(() => {
      if (selectedMotionId) {
        fetchTallies(selectedMotionId);
      }
    }, 5000);
  }

  function stopPollingTallies() {
    if (tallyTimer) clearInterval(tallyTimer);
    tallyTimer = null;
  }

  async function setTimer(seconds, extend) {
    if (!selectedMotionId) return;
    const url = `${timerBase}${selectedMotionId}/timer/`;
    const body = [];
    if (typeof seconds === "number") body.push(`seconds=${encodeURIComponent(seconds)}`);
    if (typeof extend === "number") body.push(`extend=${encodeURIComponent(extend)}`);
    if (!body.length) return;
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": getCsrfToken(),
        },
        body: body.join("&"),
      });
      if (!res.ok) return;
      const data = await res.json();
      if (data.motion) {
        motionMap.set(data.motion.id, data.motion);
        syncRowMeta(data.motion);
        if (selectedMotionId === data.motion.id) {
          renderSelectedMotion(data.motion);
        }
      }
    } catch (err) {
      console.warn("Timer update failed", err);
    }
  }

  async function resetVotes(button) {
    const url = button.dataset.resetUrl;
    const motionId = parseInt(button.dataset.motionId, 10);
    const motionTitle =
      button.dataset.motionTitle || (motionId && motionMap.get(motionId)?.title) || "this motion";
    if (!url) return;
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": getCsrfToken(),
        },
      });
      if (!res.ok) {
        alert("Unable to refresh votes right now. Please try again.");
        return;
      }
      const data = await res.json().catch(() => null);
      if (data && data.motion_id) {
        setCountsForMotion(data.motion_id, data.counts || {});
        const motion = motionMap.get(data.motion_id);
        if (motion) motion.votes_count = 0;
      }
    } catch (err) {
      console.warn("Reset failed", err);
      alert("Unable to refresh votes right now. Please try again.");
    }
  }

  function bootstrapMotionMap() {
    motionRows.forEach((row) => {
      const id = parseInt(row.dataset.id, 10);
      if (!id) return;
      const votesCountRaw = row.dataset.votes ? parseInt(row.dataset.votes, 10) : 0;
      const votesCount = Number.isNaN(votesCountRaw) ? 0 : votesCountRaw;
      motionMap.set(id, {
        id,
        title: row.dataset.title || "",
        body: row.dataset.body || "",
        status: row.dataset.status || "draft",
        allow_vote_change: row.dataset.allow === "true",
        reveal_results: row.dataset.reveal === "true",
        auto_close_seconds: row.dataset.autoClose ? parseInt(row.dataset.autoClose, 10) : null,
        opened_at: row.dataset.openedAt || null,
        closed_at: row.dataset.closedAt || null,
        votes_count: votesCount,
      });
      if (row.dataset.status === "open") {
        openMotionId = id;
      }
    });

    if (initialMotionScript) {
      try {
        const payload = JSON.parse(initialMotionScript.textContent);
        if (payload && payload.id) {
          const merged = { ...(motionMap.get(payload.id) || {}), ...payload };
          motionMap.set(payload.id, merged);
          openMotionId = payload.id;
        }
      } catch (err) {
        console.warn("Failed to parse initial motion", err);
      }
    }
    if (initialCountsScript) {
      try {
        const payload = JSON.parse(initialCountsScript.textContent);
        if (openMotionId) {
          setCountsForMotion(openMotionId, payload || {});
        }
      } catch (err) {
        // ignore
      }
    }
  }

  bootstrapMotionMap();
  const storedSelectionId = loadStoredSelection();
  if (openMotionId && motionMap.get(openMotionId)?.status === "open") {
    selectedMotionId = openMotionId;
  } else if (storedSelectionId && motionMap.has(storedSelectionId)) {
    selectedMotionId = storedSelectionId;
  } else if (!selectedMotionId) {
    selectedMotionId = openMotionId || (motionRows[0] ? parseInt(motionRows[0].dataset.id, 10) : null);
  }
  highlightSelection();
  if (selectedMotionId) {
    renderSelectedMotion(motionMap.get(selectedMotionId));
    fetchTallies(selectedMotionId);
    persistSelection(selectedMotionId);
    broadcastPreviewSelection(motionMap.get(selectedMotionId));
  } else {
    renderSelectedMotion(null);
    persistSelection(null);
  }

  motionRows.forEach((row) => {
    const id = parseInt(row.dataset.id, 10);
    if (id) refreshCompletion(id);
  });

  motionRows.forEach((row) => {
    row.addEventListener("click", () => {
      const id = parseInt(row.dataset.id, 10);
      selectMotion(id);
    });
  });

  if (timerSetBtn && timerInput) {
    timerSetBtn.addEventListener("click", () => {
      const value = parseInt(timerInput.value, 10);
      if (isNaN(value)) return;
      setTimer(value, null);
    });
  }

  if (timerExtendBtn) {
    timerExtendBtn.addEventListener("click", () => setTimer(null, 3));
  }

  resetButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const motionId = parseInt(btn.dataset.motionId, 10);
      const title = btn.dataset.motionTitle || (motionId && motionMap.get(motionId)?.title) || "this motion";
      const confirmed = confirm(`Refreshing "${title}" will clear all current votes. Continue?`);
      if (!confirmed) return;
      resetVotes(btn);
    });
  });

  connectSocket();
  startPollingTallies();
})();
