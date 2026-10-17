/* The game remains isolated from monitoring data and page styles. */
(() => {
  'use strict';
  const flame = document.querySelector('.brand-mark');
  if (!flame) return;
  const dialog = document.createElement('dialog');
  dialog.className = 'easter-dialog';
  dialog.setAttribute('aria-labelledby', 'easter-dialog-title');
  const header = document.createElement('div');
  header.className = 'easter-dialog-header';
  const title = document.createElement('h2');
  title.id = 'easter-dialog-title'; title.textContent = 'A little forest rescue';
  const closeButton = document.createElement('button');
  closeButton.type = 'button'; closeButton.className = 'easter-dialog-close';
  closeButton.textContent = 'Close'; closeButton.setAttribute('aria-label', 'Close forest rescue game');
  const frame = document.createElement('iframe');
  frame.title = 'Forest rescue mini-game. Fictional play only.';
  header.append(title, closeButton); dialog.append(header, frame); document.body.append(dialog);
  let sparks = 0, lastSpark = 0;
  function open() {
    if (dialog.open) return;
    frame.src = 'easter_egg.html?embedded=1';
    document.body.classList.add('easter-open');
    dialog.showModal();
    closeButton.focus();
  }
  function close() { if (dialog.open) dialog.close(); }
  dialog.addEventListener('close', () => {
    frame.removeAttribute('src'); frame.src = 'about:blank';
    document.body.classList.remove('easter-open');
    sparks = 0;
    flame.focus({preventScroll:true});
  });
  closeButton.addEventListener('click', close);
  dialog.addEventListener('click', event => { if (event.target === dialog) { const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)close(); } });
  window.addEventListener('message', event => {
    if (event.origin === window.location.origin && event.source === frame.contentWindow && event.data?.type === 'forest-game-close') close();
  });
  flame.addEventListener('click', () => {
    const now = performance.now();
    sparks = now - lastSpark > 2000 ? 1 : sparks + 1;
    lastSpark = now;
    if (sparks >= 5) { sparks = 0; open(); }
  });
})();
