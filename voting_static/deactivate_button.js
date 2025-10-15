(() => {
  const holdBtn = document.getElementById('holdBtn');
  const progressBar = document.getElementById('progressBar');
  const activationMessage = document.getElementById('activationMessage');

  const HOLD_DURATION = 5000;
  let holdTimer = null;

  const getCsrfToken = () => {
    const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (input && input.value) {
      return input.value;
    }
    const match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  };

  const resetProgress = (animate = true) => {
    if (!progressBar) {
      return;
    }
    progressBar.style.transition = animate ? 'width 0.2s ease' : 'none';
    progressBar.style.width = '0%';
    if (!animate) {
      requestAnimationFrame(() => {
        progressBar.style.transition = 'width 0.2s ease';
      });
    }
  };

  const updateUIForActivation = (payload = {}) => {
    if (!holdBtn) {
      return;
    }
    holdBtn.dataset.isActive = 'true';
    holdBtn.disabled = true;
    holdBtn.classList.add('is-complete');
    const label = holdBtn.querySelector('span');
    if (label) {
      label.textContent = 'Session Active';
    }

    if (activationMessage) {
      activationMessage.dataset.active = 'true';
      activationMessage.classList.remove('is-idle');
      activationMessage.classList.remove('has-error');
      const activeText =
        activationMessage.dataset.activeText || 'Voting session is active.';
      activationMessage.innerHTML = `<span class="status-dot"></span>${activeText}`;
    }

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
          activationMessage.innerHTML = `<span class="status-dot"></span>${activeText}`;
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
    holdBtn.classList.add('is-loading');
    try {
      const response = await fetch(activateUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken(),
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
    progressBar.style.transition = `width ${HOLD_DURATION}ms linear`;
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
    resetProgress();
  };

  if (holdBtn) {
    ['mousedown', 'touchstart'].forEach((eventName) =>
      holdBtn.addEventListener(eventName, startHold)
    );
    ['mouseup', 'mouseleave', 'touchend', 'touchcancel'].forEach((eventName) =>
      holdBtn.addEventListener(eventName, cancelHold)
    );
  }

})();
