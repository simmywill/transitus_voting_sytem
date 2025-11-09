(() => {
  const state = {};

  const createModal = () => {
    if (state.modal) {
      return state;
    }

    const wrapper = document.createElement('div');
    wrapper.className = 'qr-modal';
    wrapper.setAttribute('aria-hidden', 'true');
    wrapper.innerHTML = `
      <div class="qr-modal__dialog" role="dialog" aria-modal="true" aria-labelledby="qrModalTitle">
        <button type="button" class="qr-modal__close" data-qr-dismiss aria-label="Close QR code viewer">
          &times;
        </button>
        <h2 class="qr-modal__title" id="qrModalTitle">QR Code</h2>
        <img class="qr-modal__image" alt="Voting session QR code" loading="lazy" />
        <a class="qr-modal__download" target="_blank" rel="noopener">Download</a>
      </div>
    `;

    document.body.appendChild(wrapper);

    state.modal = wrapper;
    state.dialog = wrapper.querySelector('.qr-modal__dialog');
    state.title = wrapper.querySelector('.qr-modal__title');
    state.image = wrapper.querySelector('.qr-modal__image');
    state.download = wrapper.querySelector('.qr-modal__download');

    wrapper.addEventListener('click', (event) => {
      if (event.target === wrapper) {
        closeModal();
      }
    });

    return state;
  };

  const formatFilename = (label = 'qr-code') =>
    (label || 'qr-code')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '');

  const openModal = (url, label) => {
    if (!url) {
      return;
    }
    const { modal, title, image, download } = createModal();
    const safeLabel = label && label.trim() ? label.trim() : 'QR Code';

    title.textContent = safeLabel;
    image.src = url;
    image.alt = `${safeLabel} image`;
    download.href = url;
    download.setAttribute('download', `${formatFilename(safeLabel)}.png`);
    download.textContent = 'Download QR Code';

    modal.classList.add('is-visible');
    document.body.classList.add('qr-modal-open');
  };

  const closeModal = () => {
    if (!state.modal) {
      return;
    }
    state.modal.classList.remove('is-visible');
    document.body.classList.remove('qr-modal-open');
    if (state.image) {
      state.image.removeAttribute('src');
    }
  };

  document.addEventListener('DOMContentLoaded', () => {
    createModal();

    document.body.addEventListener('click', (event) => {
      const closeTrigger = event.target.closest('[data-qr-dismiss]');
      if (closeTrigger) {
        event.preventDefault();
        closeModal();
        return;
      }

      const trigger = event.target.closest('[data-qr-modal]');
      if (!trigger) {
        return;
      }

      const url = trigger.getAttribute('data-qr-modal') || trigger.getAttribute('href');
      const label = trigger.getAttribute('data-qr-label') || trigger.textContent || 'QR Code';
      if (!url) {
        return;
      }

      event.preventDefault();
      openModal(url, label);
    });
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeModal();
    }
  });
})();
