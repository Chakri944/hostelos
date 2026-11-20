document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide) lucide.createIcons();
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('overlay');
  const menu = document.getElementById('menuButton');
  const closeMenu = () => { sidebar?.classList.remove('open'); overlay?.classList.remove('show'); };
  menu?.addEventListener('click', () => { sidebar?.classList.add('open'); overlay?.classList.add('show'); });
  overlay?.addEventListener('click', closeMenu);
});
function showToast(message) {
  let toast = document.querySelector('.toast-message');
  if (!toast) { toast = document.createElement('div'); toast.className = 'toast-message'; document.body.appendChild(toast); }
  toast.textContent = message; toast.classList.add('visible');
  clearTimeout(window.toastTimer);
  window.toastTimer = setTimeout(() => toast.classList.remove('visible'), 2600);
}
