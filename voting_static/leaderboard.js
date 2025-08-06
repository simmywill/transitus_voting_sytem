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
        const votes = parseInt(row.dataset.votes);
        const voteEl = row.querySelector(".votes");
        let count = 0;
        const duration = 1000;
        const stepTime = Math.max(Math.floor(duration / votes), 20);
        
        const counter = setInterval(() => {
          count++;
          voteEl.textContent = count;
          if (count >= votes) clearInterval(counter);
        }, stepTime);
      });
    });
  });
  