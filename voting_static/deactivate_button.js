    const holdBtn = document.getElementById('holdBtn');
    const progressBar = document.getElementById('progressBar');

    const holdTime = 5000; // 5 seconds
    let holdStart = 0;
    let interval;

    holdBtn.addEventListener('mousedown', () => {
      holdStart = Date.now();
      progressBar.style.transition = `width ${holdTime}ms linear`;
      progressBar.style.width = '100%';

      interval = setTimeout(() => {
        alert("Action Confirmed!");
        // Reset after completion
        progressBar.style.transition = 'width 0s';
        progressBar.style.width = '0%';
      }, holdTime);
    });

    const cancelHold = () => {
      clearTimeout(interval);
      progressBar.style.transition = 'width 0.2s ease';
      progressBar.style.width = '0%';
    };

    holdBtn.addEventListener('mouseup', cancelHold);
    holdBtn.addEventListener('mouseleave', cancelHold);
    holdBtn.addEventListener('touchend', cancelHold);
    holdBtn.addEventListener('touchcancel', cancelHold);

