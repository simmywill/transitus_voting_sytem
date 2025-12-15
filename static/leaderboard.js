document.addEventListener("DOMContentLoaded", () => {
    const leaderboards = document.querySelectorAll(".leaderboard");
  
    leaderboards.forEach(lb => {
      let rows = Array.from(lb.querySelectorAll(".candidate-row"));
      
      // Sort by vote count descending
      rows.sort((a, b) => {
        return parseInt(b.dataset.votes) - parseInt(a.dataset.votes);
      });
  
      // Clear existing and reappend sorted
      rows.forEach((row, index) => {
        row.querySelector(".rank").textContent = index + 1;
        lb.appendChild(row);
  
        // Animate vote counter
        const votes = parseInt(row.dataset.votes, 10) || 0;
        const voteEl = row.querySelector(".votes");

        if (votes <= 0) {
          voteEl.textContent = "0";
          return;
        }

        let count = 0;
        const duration = 1000;
        const stepTime = Math.max(Math.floor(duration / votes), 20);

        const counter = setInterval(() => {
          count += 1;

          if (count >= votes) {
            voteEl.textContent = String(votes);
            clearInterval(counter);
            return;
          }

          voteEl.textContent = String(count);
        }, stepTime);
      });
    });
  });
  
