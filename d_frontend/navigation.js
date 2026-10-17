/* Shared navigation interactions for Home and Analytics. */
(() => {
const navigationLinks = document.querySelectorAll('.nav-link');
const navigationDescriptions = { 'index.html': 'View the monitoring map, forecasts and simulated responses.', 'analytics.html': 'Explore historical weather, soil and hotspot measurements.' };
const navigationTooltip = document.createElement('div');
navigationTooltip.id = 'navigation-tooltip';
navigationTooltip.className = 'navigation-tooltip';
navigationTooltip.setAttribute('role', 'tooltip');
navigationTooltip.hidden = true;
document.body.append(navigationTooltip);
let tooltipTimer;
function hideNavigationTooltip() {
  clearTimeout(tooltipTimer);
  navigationTooltip.hidden = true;
}
for (const link of navigationLinks) {
  const label = link.querySelector('span').textContent;
  link.setAttribute('aria-label', label);
  const description = document.createElement('span');
  description.id = `nav-description-${link.getAttribute('href').replace('.html', '')}`;
  description.className = 'visually-hidden';
  description.textContent = navigationDescriptions[link.getAttribute('href')] || label;
  link.append(description);
  link.setAttribute('aria-describedby', description.id);
  const showTooltip = () => {
    clearTimeout(tooltipTimer);
    navigationTooltip.replaceChildren();
    const title = document.createElement('strong');
    title.textContent = label;
    const text = document.createElement('span');
    text.textContent = description.textContent;
    navigationTooltip.append(title, text);
    navigationTooltip.hidden = false;
    const bounds = link.getBoundingClientRect();
    const tooltipBounds = navigationTooltip.getBoundingClientRect();
    const left = bounds.right + 10 + tooltipBounds.width <= window.innerWidth - 12
      ? bounds.right + 10 : Math.max(12, Math.min(bounds.left, window.innerWidth - tooltipBounds.width - 12));
    const top = bounds.right + 10 + tooltipBounds.width <= window.innerWidth - 12
      ? bounds.top + (bounds.height - tooltipBounds.height) / 2 : bounds.bottom + 10;
    navigationTooltip.style.left = `${left}px`;
    navigationTooltip.style.top = `${Math.max(12, Math.min(top, window.innerHeight - tooltipBounds.height - 12))}px`;
  };
  link.addEventListener('mouseenter', showTooltip);
  link.addEventListener('focus', showTooltip);
  link.addEventListener('mouseleave', () => { tooltipTimer = setTimeout(hideNavigationTooltip, 120); });
  link.addEventListener('blur', hideNavigationTooltip);
  link.addEventListener('click', hideNavigationTooltip);
}
navigationTooltip.addEventListener('mouseenter', () => clearTimeout(tooltipTimer));
navigationTooltip.addEventListener('mouseleave', hideNavigationTooltip);
document.addEventListener('keydown', event => { if (event.key === 'Escape') hideNavigationTooltip(); });
window.addEventListener('resize', hideNavigationTooltip);
window.addEventListener('scroll', hideNavigationTooltip, true);

const sidebarToggle = document.querySelector('#sidebar-toggle');
const sidebar = document.querySelector('#sidebar');
function setSidebarOpen(open) {
  hideNavigationTooltip();
  sidebar.hidden = !open;
  document.body.classList.toggle('sidebar-closed', !open);
  sidebarToggle.setAttribute('aria-expanded', String(open));
  const label = open ? 'Close navigation' : 'Open navigation';
  sidebarToggle.setAttribute('aria-label', label);
  sidebarToggle.title = label;
}
sidebarToggle.addEventListener('click', () => setSidebarOpen(sidebar.hidden));
sidebar.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    setSidebarOpen(false);
    sidebarToggle.focus();
  }
});

})();
