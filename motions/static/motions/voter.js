(function () {
  const configEl = document.getElementById("motion-config");
  if (!configEl) return;

  const sessionUuid = configEl.dataset.session;
  const wsPath = configEl.dataset.ws;
  const currentUrl = configEl.dataset.currentUrl;
  const presenceUrl = configEl.dataset.presenceUrl;
  const voteBase = configEl.dataset.voteBase;
  let initialMotion = null;
  if (configEl.dataset.motion) {
    initialMotion = JSON.parse(configEl.dataset.motion);
  } else {
    const script = document.getElementById("initial-motion");
    if (script) {
      try {
        initialMotion = JSON.parse(script.textContent);
      } catch (err) {
        initialMotion = null;
      }
    }
  }
  let previewMotion = null;
  const previewScript = document.getElementById("preview-motion");
  if (previewScript) {
    try {
      previewMotion = JSON.parse(previewScript.textContent);
    } catch (err) {
      previewMotion = null;
    }
  }
  const initialSelection = configEl.dataset.selection || null;
  let latestClosed = null;
  const latestClosedScript = document.getElementById("latest-closed");
  if (latestClosedScript) {
    try {
      latestClosed = JSON.parse(latestClosedScript.textContent);
    } catch (err) {
      latestClosed = null;
    }
  }

  const statusEl = document.getElementById("connection-status");
  const feedbackEl = document.getElementById("feedback");
  const motionTitleEl = document.getElementById("motion-title");
  const motionBodyEl = document.getElementById("motion-body");
  const motionContainer = document.getElementById("motion-container");
  const waitingEl = document.getElementById("waiting");
  const voteButtons = document.querySelectorAll("[data-choice]");
  const choiceGrid = document.getElementById("choice-grid");
  const resultsEl = document.getElementById("inline-results");
  const resultsList = document.getElementById("results-list");
  const userVoteEl = document.getElementById("your-vote");
  const timerEl = document.getElementById("timer");
  const timerBanner = document.getElementById("timer-banner");
  const closedAlert = document.getElementById("closed-alert");
  const presenceEl = document.getElementById("presence-count");
  const helpButton = document.getElementById("help-button");
  const helpDialog = document.getElementById("help-dialog");
  const helpBackdrop = document.getElementById("help-backdrop");
  const helpClose = document.getElementById("help-close");

  let socket = null;
  let heartbeatTimer = null;
  let reconnectAttempts = 0;
  let pollTimer = null;
  let currentMotion = initialMotion || previewMotion || latestClosed;
  let selection = null;
  if (initialMotion) {
    selection = initialSelection;
  } else if (!selection && latestClosed && !previewMotion && !initialMotion) {
    selection = latestClosed.selection || null;
  }
  let autoCloseAt = null;
  let timerFrame = null;
  let lastClosedMotionId =
    latestClosed && !initialMotion && !previewMotion ? latestClosed.id || null : null;

  const helpKey = `motion_help_seen_${sessionUuid}`;

  function setStatus(state, message) {
    statusEl.dataset.state = state;
    statusEl.textContent = message;
    statusEl.className = `status-pill ${state}`;
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

  function toggleResultsVisibility(show) {
    if (resultsEl) {
      resultsEl.hidden = !show;
    }
    if (choiceGrid) {
      choiceGrid.hidden = !!show;
    }
  }

  function resetUserVote() {
    if (!userVoteEl) return;
    userVoteEl.textContent = "";
    userVoteEl.className = "vote-chip";
    userVoteEl.hidden = true;
  }

  function setUserVote(choice) {
    if (!userVoteEl) return;
    const normalized = (choice || "").toLowerCase();
    userVoteEl.className = "vote-chip";
    if (normalized) {
      userVoteEl.textContent = normalized.toUpperCase();
      userVoteEl.classList.add(`vote-chip--${normalized}`);
    } else {
      userVoteEl.textContent = "No vote recorded";
      userVoteEl.classList.add("vote-chip--none");
    }
    userVoteEl.hidden = false;
  }

  function renderWaiting(message) {
    previewMotion = null;
    currentMotion = null;
    selection = null;
    lastClosedMotionId = null;
    motionContainer.hidden = true;
    waitingEl.hidden = false;
    waitingEl.textContent = message || "Please wait, the next motion will appear shortly.";
    disableVoting(true);
    toggleResultsVisibility(false);
    resetUserVote();
    setClosedAlert(false);
    feedbackEl.textContent = "";
    feedbackEl.className = "feedback";
    autoCloseAt = null;
    if (timerFrame) {
      cancelAnimationFrame(timerFrame);
      timerFrame = null;
    }
    updateTimerDisplay("Waiting");
  }

  function renderMotion(motion, userSelection, options = {}) {
    if (!motion) {
      renderWaiting();
      return;
    }
    previewMotion = options.preview ? motion : null;
    const isPreview = options.preview || (motion && motion.preview);
    motionContainer.hidden = false;
    waitingEl.hidden = true;
    toggleResultsVisibility(false);
    resetUserVote();
    motionTitleEl.textContent = motion.title;
    motionBodyEl.textContent = motion.body || "No description provided.";
    selection = userSelection || null;
    updateSelectionUI();
    disableVoting(isPreview || motion.status !== "open");
    autoCloseAt = null;
    if (timerFrame) {
      cancelAnimationFrame(timerFrame);
      timerFrame = null;
    }
    const hasTimer = motion.auto_close_seconds && motion.opened_at;
    if (isPreview) {
      setClosedAlert(true, "Waiting for the moderator to open voting for this motion.");
      updateTimerDisplay("Waiting");
      return;
    }
    if (motion.status === "closed") {
      setClosedAlert(true, "Voting closed");
      updateTimerDisplay("Closed");
    } else {
      setClosedAlert(false);
      updateTimerDisplay(hasTimer ? "Syncing" : "Not set");
    }
    if (motion.auto_close_seconds && motion.opened_at) {
      autoCloseAt = new Date(motion.opened_at).getTime() + motion.auto_close_seconds * 1000;
      startTimer();
    }
  }

  function renderPreview(motion) {
    if (!motion) {
      renderWaiting();
      return;
    }
    previewMotion = motion;
    currentMotion = motion;
    selection = null;
    clearResults();
    renderMotion(motion, null, { preview: true });
  }

  function updateSelectionUI() {
    voteButtons.forEach((btn) => {
      const choice = btn.dataset.choice;
      const isSelected = choice === selection;
      btn.classList.toggle("selected", isSelected);
      btn.setAttribute("aria-pressed", String(isSelected));
    });
    if (selection) {
      feedbackEl.textContent = "Vote recorded";
      feedbackEl.className = "feedback success";
    } else {
      feedbackEl.textContent = "";
      feedbackEl.className = "feedback";
    }
  }

  function setClosedAlert(visible, message) {
    if (!closedAlert) return;
    closedAlert.hidden = !visible;
    const body = closedAlert.querySelector(".alert-body");
    if (body && message) {
      body.textContent = message;
    }
  }

  function disableVoting(disabled) {
    voteButtons.forEach((btn) => {
      btn.disabled = disabled;
      btn.setAttribute("aria-disabled", String(disabled));
    });
    if (disabled) {
      voteButtons.forEach((btn) => btn.classList.remove("selected"));
    }
  }

  function updateTimerDisplay(value, state = "idle") {
    if (timerEl) {
      timerEl.textContent = value;
    }
    if (timerBanner) {
      timerBanner.classList.toggle("timer-active", state === "active" || state === "urgent");
      timerBanner.classList.toggle("timer-urgent", state === "urgent");
    }
  }

  function connectSocket() {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${scheme}://${location.host}${wsPath}`);
    socket.onopen = () => {
      setStatus("connected", "Connected");
      reconnectAttempts = 0;
      startHeartbeat();
      stopPolling();
    };
    socket.onclose = () => {
      setStatus("reconnecting", "Reconnecting…");
      stopHeartbeat();
      scheduleReconnect();
    };
    socket.onerror = () => {
      setStatus("reconnecting", "Reconnecting…");
      socket.close();
    };
    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleEvent(data.event, data.payload || {});
      } catch (err) {
        console.error("Bad WS payload", err);
      }
    };
  }

  function scheduleReconnect() {
    reconnectAttempts += 1;
    const delay = Math.min(15000, 3000 + reconnectAttempts * 1000);
    if (reconnectAttempts >= 3) {
      startPolling();
    }
    setTimeout(() => connectSocket(), delay);
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

  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(fetchState, 5000);
    fetchState();
  }

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  async function fetchState() {
    try {
      const res = await fetch(currentUrl, { headers: { "Cache-Control": "no-cache" } });
      if (!res.ok) throw new Error("Bad response");
      const data = await res.json();
      if (data.open) {
        previewMotion = null;
        currentMotion = data.open;
        selection = data.open.selection || null;
        renderMotion(currentMotion, selection);
        clearResults();
      } else if (data.preview) {
        if (data.preview.preview) {
          renderPreview(data.preview);
        } else {
          previewMotion = null;
          currentMotion = data.preview;
          renderMotion(currentMotion, data.preview.selection || null);
          if (
            data.preview.status === "closed" &&
            data.preview.reveal_results &&
            data.preview.counts
          ) {
            renderResults(data.preview.counts, data.preview.id, {
              userChoice: data.preview.selection || selection,
            });
          }
        }
      } else if (data.latest_closed && data.latest_closed.counts) {
        previewMotion = null;
        currentMotion = data.latest_closed;
        selection = data.latest_closed.selection || null;
        renderMotion(currentMotion, selection);
        renderResults(data.latest_closed.counts, data.latest_closed.id, { userChoice: selection });
      } else {
        currentMotion = null;
        selection = null;
        renderWaiting();
        clearResults();
      }
      setStatus("connected", "Connected");
    } catch (err) {
      console.warn("Polling failed", err);
      setStatus("offline", "Offline");
    }
    try {
      const res = await fetch(presenceUrl);
      const data = await res.json();
      if (data && typeof data.count === "number") {
        presenceEl.textContent = data.count;
      }
    } catch (err) {
      // ignore
    }
  }

  function renderResults(counts, motionId, options = {}) {
    if (!resultsList || !counts) return;
    if (motionContainer) {
      motionContainer.hidden = false;
    }
    if (waitingEl) {
      waitingEl.hidden = true;
    }
    previewMotion = null;
    if (motionId) {
      lastClosedMotionId = motionId;
    }
    resultsList.innerHTML = "";
    const total = (counts.yes || 0) + (counts.no || 0) + (counts.abstain || 0);
    ["yes", "no", "abstain"].forEach((key) => {
      const value = counts[key] || 0;
      const pct = total ? Math.round((value / total) * 100) : 0;
      const li = document.createElement("li");
      li.className = "result-row";
      const label = document.createElement("span");
      label.className = "result-label";
      label.textContent = key.toUpperCase();
      const bar = document.createElement("div");
      bar.className = `result-bar result-bar--${key}`;
      const fill = document.createElement("span");
      fill.style.width = `${pct}%`;
      bar.appendChild(fill);
      const countEl = document.createElement("span");
      countEl.className = "result-count";
      countEl.textContent = `${value} (${pct}%)`;
      li.append(label, bar, countEl);
      resultsList.appendChild(li);
    });
    const userChoice =
      options.userChoice ||
      selection ||
      (currentMotion && currentMotion.selection) ||
      null;
    setUserVote(userChoice);
    toggleResultsVisibility(true);
    disableVoting(true);
    updateTimerDisplay("Closed");
    setClosedAlert(true, "Please wait for the moderator to open voting for the next motion.");
  }

  function clearResults() {
    toggleResultsVisibility(false);
    if (resultsList) {
      resultsList.innerHTML = "";
    }
    resetUserVote();
    lastClosedMotionId = null;
  }

  async function submitVote(choice) {
    if (!currentMotion || currentMotion.status !== "open") return;
    const voteUrl = `${voteBase}${currentMotion.id}/vote/`;
    disableVoting(true);
    feedbackEl.textContent = "Submitting…";
    feedbackEl.className = "feedback";
    try {
      const res = await fetch(voteUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRFToken": getCsrfToken(),
        },
        body: `choice=${encodeURIComponent(choice)}`,
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        const message =
          data.error === "vote_locked"
            ? "Vote already recorded."
            : "Vote could not be recorded. Please try again.";
        feedbackEl.textContent = message;
        feedbackEl.className = "feedback error";
      } else {
        selection = choice;
        updateSelectionUI();
      }
    } catch (err) {
      feedbackEl.textContent = "Connection issue. Please try again.";
      feedbackEl.className = "feedback error";
    } finally {
      disableVoting(!currentMotion || currentMotion.status !== "open");
    }
  }

  function handleEvent(event, payload) {
    switch (event) {
      case "motion_opened":
        previewMotion = null;
        currentMotion = payload;
        selection = null;
        clearResults();
        renderMotion(payload, null);
        break;
      case "motion_previewed":
        if (!payload || !payload.id) break;
        if (currentMotion && currentMotion.status === "open" && payload.id !== currentMotion.id) {
          break;
        }
        if (payload.preview) {
          previewMotion = payload;
          renderPreview(payload);
        } else {
          previewMotion = null;
          currentMotion = payload;
          renderMotion(payload, payload.selection || null);
          if (payload.status === "closed" && payload.reveal_results && payload.counts) {
            renderResults(payload.counts, payload.id, { userChoice: selection });
          }
        }
        break;
      case "motion_closed":
        previewMotion = null;
        currentMotion = payload;
        if (selection && !currentMotion.selection) {
          currentMotion.selection = selection;
        }
        renderMotion(currentMotion, selection);
        lastClosedMotionId = payload.id || null;
        disableVoting(true);
        feedbackEl.textContent = "Voting closed.";
        feedbackEl.className = "feedback";
        updateTimerDisplay("Closed");
        setClosedAlert(true, "Please wait for the moderator to open voting for the next motion.");
        if (payload.reveal_results && payload.counts) {
          renderResults(payload.counts, payload.id, { userChoice: selection });
        }
        break;
      case "results_revealed":
        if (previewMotion || (currentMotion && currentMotion.preview)) {
          break;
        }
        if (payload.counts) {
          const hasOpen = currentMotion && currentMotion.status === "open";
          const matchesClosed =
            !lastClosedMotionId || (payload.motion_id && payload.motion_id === lastClosedMotionId);
          if (!hasOpen && matchesClosed) {
            renderResults(payload.counts, payload.motion_id, { userChoice: selection });
          }
        }
        break;
      case "timer_updated":
        if (currentMotion && payload.id === currentMotion.id) {
          currentMotion.auto_close_seconds = payload.auto_close_seconds;
          currentMotion.opened_at = payload.opened_at;
          autoCloseAt = null;
          if (currentMotion.auto_close_seconds && currentMotion.opened_at) {
            autoCloseAt =
              new Date(currentMotion.opened_at).getTime() + currentMotion.auto_close_seconds * 1000;
            startTimer();
          }
        }
        break;
      case "results_hidden":
        if (previewMotion) {
          renderPreview(previewMotion);
          break;
        }
        clearResults();
        disableVoting(true);
        setClosedAlert(true, "Please wait for the moderator to open voting for the next motion.");
        break;
      case "vote_ack":
        if (payload.choice) {
          selection = payload.choice;
          updateSelectionUI();
          if (resultsEl && !resultsEl.hidden) {
            setUserVote(selection);
          }
        }
        break;
      case "presence_update":
        if (presenceEl && typeof payload.count === "number") {
          presenceEl.textContent = payload.count;
        }
        break;
      case "heartbeat_ack":
        if (typeof payload.active_count === "number") {
          presenceEl.textContent = payload.active_count;
        }
        setStatus("connected", "Connected");
        break;
      default:
        break;
    }
  }

  function startTimer() {
    if (timerFrame) {
      cancelAnimationFrame(timerFrame);
      timerFrame = null;
    }
    if (!autoCloseAt) {
      updateTimerDisplay("Waiting");
      return;
    }
    const tick = () => {
      if (!autoCloseAt || (currentMotion && currentMotion.status !== "open")) {
        updateTimerDisplay("Closed");
        timerFrame = null;
        return;
      }
      const remaining = Math.max(0, autoCloseAt - Date.now());
      if (remaining <= 0) {
        updateTimerDisplay("Closing", "urgent");
        disableVoting(true);
        setClosedAlert(true, "Please wait for the moderator to open voting for the next motion.");
        timerFrame = null;
        return;
      }
      const seconds = Math.ceil(remaining / 1000);
      const state = seconds <= 10 ? "urgent" : "active";
      updateTimerDisplay(`${seconds}s`, state);
      timerFrame = requestAnimationFrame(tick);
    };
    timerFrame = requestAnimationFrame(tick);
  }

  function showHelp() {
    helpBackdrop.classList.add("active");
    helpDialog.setAttribute("aria-hidden", "false");
    helpClose.focus();
  }

  function hideHelp() {
    helpBackdrop.classList.remove("active");
    helpDialog.setAttribute("aria-hidden", "true");
  }

  function initHelp() {
    if (!localStorage.getItem(helpKey)) {
      showHelp();
      localStorage.setItem(helpKey, "1");
    }
    helpButton?.addEventListener("click", showHelp);
    helpClose?.addEventListener("click", hideHelp);
    helpBackdrop?.addEventListener("click", (e) => {
      if (e.target === helpBackdrop) hideHelp();
    });
    document.addEventListener("keyup", (e) => {
      if (e.key === "Escape") hideHelp();
    });
  }

  voteButtons.forEach((btn) => {
    btn.addEventListener("click", () => submitVote(btn.dataset.choice));
    btn.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        submitVote(btn.dataset.choice);
      }
    });
  });

  window.addEventListener("online", () => setStatus("connected", "Connected"));
  window.addEventListener("offline", () => setStatus("offline", "Offline"));

  if (previewMotion && !initialMotion) {
    if (previewMotion.preview) {
      renderPreview(previewMotion);
    } else {
      renderMotion(previewMotion, previewMotion.selection || null);
      if (
        previewMotion.status === "closed" &&
        previewMotion.reveal_results &&
        previewMotion.counts
      ) {
        renderResults(previewMotion.counts, previewMotion.id, {
          userChoice: previewMotion.selection || selection,
        });
      }
    }
  } else {
    renderMotion(currentMotion, selection);
  }
  if (!initialMotion && !previewMotion && latestClosed && latestClosed.counts) {
    renderResults(latestClosed.counts, latestClosed.id, {
      userChoice: latestClosed.selection || selection,
    });
  }
  connectSocket();
  initHelp();
})();
