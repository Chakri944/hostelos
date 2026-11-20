document.addEventListener('DOMContentLoaded', () => {
  const canvas = document.getElementById('collectionChart');
  if (!canvas || !window.Chart) return;
  new Chart(canvas, {
    type: 'bar',
    data: {
      labels: window.hostelChartLabels || [],
      datasets: [{
        label: 'Collections',
        data: window.hostelChartValues || [],
        backgroundColor: '#7667e8',
        hoverBackgroundColor: '#5d4ed0',
        borderRadius: 6,
        borderSkipped: false,
        maxBarThickness: 34
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ' ₹' + Number(c.raw).toLocaleString('en-IN') } } },
      scales: {
        x: { grid: { display: false }, border: { display: false }, ticks: { color: '#9297a5', font: { family: 'DM Sans' } } },
        y: { beginAtZero: true, grid: { color: '#f0f1f5', drawTicks: false }, border: { display: false }, ticks: { color: '#9297a5', padding: 12, callback: v => v >= 1000 ? '₹' + (v/1000) + 'k' : '₹' + v, font: { family: 'DM Sans', size: 11 } } }
      }
    }
  });
});
