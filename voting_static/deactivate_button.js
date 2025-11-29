(() => {
  const holdBtn = document.getElementById('holdBtn');
  const progressBar = document.getElementById('progressBar');
  const activationMessage = document.getElementById('activationMessage');
  const resultsNav = document.getElementById('generate-results-nav');
  const resultsLink = document.getElementById('generate-results-link');

  const HOLD_DURATION = 5000;
  let holdTimer = null;

  const escapeAttr = (value = '') =>
    value
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

  const getCsrfToken = () => {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content && meta.content !== 'NOTPROVIDED') {
      return meta.content;
    }
    const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (input && input.value) {
      return input.value;
    }
    if (window.csrfToken && window.csrfToken !== 'NOTPROVIDED') {
      return window.csrfToken;
    }
    const match = document.cookie.match(/(?:^|;)\s*csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  };

  const getSessionTitle = (source = {}) =>
    source.session_title ||
    holdBtn?.dataset?.sessionTitle ||
    activationMessage?.dataset?.sessionTitle ||
    'Session QR Code';

  const buildActivationLinksMarkup = (source = {}) => {
    const shareUrl =
      source.unique_url ||
      holdBtn?.dataset?.uniqueUrl ||
      activationMessage?.dataset?.uniqueUrl ||
      '';
    const qrUrl =
      source.qr_code_url ||
      holdBtn?.dataset?.qrCodeUrl ||
      activationMessage?.dataset?.qrCodeUrl ||
      '';
    const anchors = [];
    if (shareUrl) {
      const safeShareUrl = escapeAttr(shareUrl);
      anchors.push(
        `<a class="activation-link" href="${safeShareUrl}" target="_blank" rel="noopener">Open Share Link</a>`
      );
    }
    if (qrUrl) {
      const safeQrUrl = escapeAttr(qrUrl);
      const label = escapeAttr(getSessionTitle(source));
      anchors.push(
        `<a class="activation-link" href="${safeQrUrl}" target="_blank" rel="noopener" data-qr-modal="${safeQrUrl}" data-qr-label="${label}">View QR Code</a>`
      );
    }
    return anchors.length ? `<span class="activation-links">${anchors.join('')}</span>` : '';
  };

  const revealResultsLink = (payload = {}) => {
    if (resultsNav) {
      resultsNav.hidden = false;
    }
    if (!resultsLink) {
      return;
    }
    const explicitUrl = payload.results_url;
    if (explicitUrl) {
      resultsLink.href = explicitUrl;
      resultsLink.dataset.resultsUrl = explicitUrl;
      return;
    }
    if (resultsLink.dataset.resultsUrl) {
      resultsLink.href = resultsLink.dataset.resultsUrl;
      return;
    }
    if (payload.session_uuid) {
      const derived = `/results/${payload.session_uuid}/`;
      resultsLink.href = derived;
      resultsLink.dataset.resultsUrl = derived;
    }
  };

  const resetProgress = (animate = true) => {
    if (!progressBar) {
      return;
    }
    progressBar.style.transition = animate ? 'width 0.2s ease' : 'none';
    progressBar.style.width = '0%';
    progressBar.style.opacity = '0';
    if (!animate) {
      requestAnimationFrame(() => {
        progressBar.style.transition = 'width 0.2s ease';
      });
    }
    if (holdBtn && !holdBtn.classList.contains('is-complete')) {
      holdBtn.classList.remove('is-arming');
    }
  };

  const updateUIForActivation = (payload = {}) => {
    if (!holdBtn) {
      return;
    }
    holdBtn.dataset.isActive = 'true';
    holdBtn.disabled = true;
    holdBtn.classList.remove('is-arming');
    holdBtn.classList.add('is-complete');
    const label = holdBtn.querySelector('span');
    if (label) {
      label.textContent = 'Session Active';
    }

    if (payload?.session_uuid) {
      holdBtn.dataset.sessionUuid = payload.session_uuid;
    }
    if (payload?.unique_url) {
      holdBtn.dataset.uniqueUrl = payload.unique_url;
    }
    if (payload?.qr_code_url) {
      holdBtn.dataset.qrCodeUrl = payload.qr_code_url;
    }
    if (payload?.session_title) {
      holdBtn.dataset.sessionTitle = payload.session_title;
    }

    if (activationMessage) {
      activationMessage.dataset.active = 'true';
      activationMessage.classList.remove('is-idle');
      activationMessage.classList.remove('has-error');
      if (payload?.unique_url) {
        activationMessage.dataset.uniqueUrl = payload.unique_url;
      }
      if (payload?.qr_code_url) {
        activationMessage.dataset.qrCodeUrl = payload.qr_code_url;
      }
      if (payload?.session_title) {
        activationMessage.dataset.sessionTitle = payload.session_title;
      }
      const activeText =
        activationMessage.dataset.activeText || 'Voting session is active.';
      const linksMarkup = buildActivationLinksMarkup(payload);
      activationMessage.innerHTML = `<span class="status-dot"></span>${activeText}${linksMarkup}`;
    }

    revealResultsLink(payload);

  };

  const showActivationError = () => {
    if (activationMessage) {
      activationMessage.classList.add('has-error');
      activationMessage.textContent = 'Unable to activate the session. Please try again.';
      setTimeout(() => {
        activationMessage.classList.remove('has-error');
        const activeText =
          activationMessage.dataset.activeText || 'Voting session is active.';
        const idleText =
          activationMessage.dataset.idleText ||
          'Activate the session to generate a shareable link and QR code.';
        if (activationMessage.dataset.active === 'true') {
          activationMessage.classList.remove('is-idle');
          const linksMarkup = buildActivationLinksMarkup();
          activationMessage.innerHTML = `<span class="status-dot"></span>${activeText}${linksMarkup}`;
        } else {
          activationMessage.classList.add('is-idle');
          activationMessage.innerHTML = `<span class="status-dot is-idle"></span>${idleText}`;
        }
      }, 2200);
    } else {
      // fallback
      alert('Unable to activate the session. Please try again.');
    }
  };

  const activateSession = async () => {
    const activateUrl = holdBtn?.dataset?.activateUrl;
    if (!activateUrl) {
      return;
    }
    const csrfToken = getCsrfToken();
    holdBtn.classList.add('is-loading');
    try {
      const response = await fetch(activateUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
          'X-Requested-With': 'XMLHttpRequest',
          Accept: 'application/json'
        },
        body: JSON.stringify({})
      });
      if (!response.ok) {
        throw new Error(`Unexpected response ${response.status}`);
      }
      const data = await response.json();
      if (!data.success) {
        throw new Error(data.error || 'Activation failed');
      }
      updateUIForActivation(data);
    } catch (err) {
      console.error('Failed to activate session', err);
      showActivationError();
    } finally {
      holdBtn.classList.remove('is-loading');
      holdBtn.classList.remove('is-arming');
      resetProgress(false);
      holdTimer = null;
    }
  };

  const startHold = () => {
    if (!holdBtn || holdBtn.disabled || holdBtn.dataset.isActive === 'true') {
      return;
    }
    if (!progressBar) {
      activateSession();
      return;
    }
    holdBtn.classList.add('is-arming');
    holdBtn.classList.remove('is-complete');
    progressBar.style.transition = `width ${HOLD_DURATION}ms linear`;
    progressBar.style.opacity = '1';
    requestAnimationFrame(() => {
      progressBar.style.width = '100%';
    });
    holdTimer = setTimeout(activateSession, HOLD_DURATION);
  };

  const cancelHold = () => {
    if (holdTimer) {
      clearTimeout(holdTimer);
      holdTimer = null;
    }
    if (holdBtn) {
      holdBtn.classList.remove('is-arming');
    }
    resetProgress();
  };

  if (holdBtn) {
    ['mousedown', 'touchstart'].forEach((eventName) =>
      holdBtn.addEventListener(eventName, startHold)
    );
    ['mouseup', 'mouseleave', 'touchend', 'touchcancel'].forEach((eventName) =>
      holdBtn.addEventListener(eventName, cancelHold)
    );
    resetProgress(false);
  }

})();
