// This function should be placed in a global JS file
function updateVoterCounts() {
    const sessionUuid = document.querySelector('#session-uuid').textContent;

    fetch(`/voter-counts/${sessionUuid}/`)
        .then(response => response.json())
        .then(data => {
            // Update the counts dynamically
            document.getElementById('verified-voters-count').textContent = `${data.verified_voters_count}/${data.total_voters_count}`;
            document.getElementById('finished-voters-count').textContent = `${data.finished_voters_count}/${data.total_voters_count - data.finished_voters_count}`;
        })
        .catch(error => console.error('Error fetching voter counts:', error));
}
