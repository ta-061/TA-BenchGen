'use strict';
const form = document.getElementById('review-form');
if (form) {
  const reviewer = document.getElementById('reviewer');
  const statusLabels = JSON.parse(form.dataset.statusLabels);
  form.addEventListener('keydown', event => {
    if (event.key !== 'Enter' || event.target.tagName !== 'INPUT') return;
    const card = event.target.closest('[data-defect]');
    event.preventDefault();
    if (card) form.requestSubmit(card.querySelector(event.target.closest('.label-editor')
      ? 'button[value=edit]' : 'button[value=save]'));
  });
  form.addEventListener('change', async event => {
    if (event.target.type !== 'checkbox') return;
    const card = event.target.closest('[data-defect]');
    const hint = card.querySelector('.save-hint');
    if (!reviewer.value.trim()) {
      hint.textContent = hint.dataset.needReviewer;
      reviewer.focus();
      return;
    }
    // A checkbox autosave must never publish a location the reviewer is still editing.
    const body = new FormData();
    body.set('csrf_token', form.elements.csrf_token.value);
    body.set('reviewer', reviewer.value);
    body.set('action', 'save');
    for (const input of card.querySelectorAll('input[type=hidden], input[type=checkbox]:checked, textarea')) {
      body.set(input.name, input.value);
    }
    hint.textContent = hint.dataset.saving;
    const enabled = [...card.querySelectorAll('input[type=checkbox], button')].filter(c => !c.disabled);
    enabled.forEach(control => { control.disabled = true; });
    try {
      const response = await fetch(card.dataset.reviewUrl, {
        method: 'POST', body, credentials: 'same-origin', headers: {Accept: 'application/json'}
      });
      if (!response.ok) throw new Error('save failed');
      const result = await response.json();
      hint.textContent = hint.dataset.saved;
      for (const [badge, value] of [
        [document.querySelector('main > .heading .status'), result.status],
        [card.querySelector('[data-defect-status]'), result.per_defect[card.dataset.defect]]
      ]) {
        badge.textContent = statusLabels[value];
        badge.className = 'status ' + value;
      }
    } catch (_) {
      hint.textContent = hint.dataset.failed;
    } finally {
      enabled.forEach(control => { control.disabled = false; });
    }
  });
}

const picker = document.getElementById('source-picker');
if (picker) {
  const section = picker.closest('.source-review');
  const files = [...section.querySelectorAll('.source-file')];
  const previous = section.querySelector('[data-previous]');
  const current = section.querySelector('[data-current]');
  const next = section.querySelector('[data-next]');
  let changes = [];
  let index = 0;

  function showChange(number, target) {
    changes[index]?.classList.remove('current-change');
    index = number;
    const change = changes[index];
    change?.classList.add('current-change');
    current.textContent = change
      ? current.dataset.format.replace('{current}', index + 1).replace('{total}', changes.length)
      : current.dataset.empty;
    previous.disabled = index <= 0;
    current.disabled = !change;
    next.disabled = index + 1 >= changes.length;

    const row = target || change;
    if (row) {
      const viewport = row.closest('.source-viewport');
      const headerHeight = viewport.querySelector('thead').offsetHeight;
      const context = Math.min(90, (viewport.clientHeight - headerHeight) / 4);
      viewport.scrollTop += row.getBoundingClientRect().top - viewport.getBoundingClientRect().top - headerHeight - context;
    }
  }

  function openFile(file, target) {
    changes[index]?.classList.remove('current-change');
    files.forEach(panel => { panel.hidden = panel !== file; });
    picker.value = file.id;
    changes = [...file.querySelectorAll('tbody[data-change]')];
    // For a target on an unchanged line, navigation starts at the next change, or the last one.
    let number = 0;
    if (target && changes.length) {
      number = changes.findIndex(change => change.contains(target) ||
        (target.compareDocumentPosition(change) & Node.DOCUMENT_POSITION_FOLLOWING));
      if (number < 0) number = changes.length - 1;
    }
    file.querySelector('.source-viewport').scrollTop = 0;
    showChange(number, target);
  }

  function followLocation() {
    const target = document.getElementById(window.location.hash.slice(1));
    const file = target?.closest('.source-file');
    if (!file) return false;
    openFile(file, file === target ? null : target);
    section.scrollIntoView({block: 'start'});
    return true;
  }

  picker.addEventListener('change', () => {
    const file = document.getElementById(picker.value);
    openFile(file);
    history.replaceState(null, '', '#' + file.id);
  });
  previous.addEventListener('click', () => showChange(index - 1));
  next.addEventListener('click', () => showChange(index + 1));
  current.addEventListener('click', () => showChange(index));
  window.addEventListener('hashchange', followLocation);
  document.querySelectorAll('.source-location').forEach(link => {
    link.addEventListener('click', event => {
      if (link.hash === window.location.hash && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
        event.preventDefault();
        followLocation();
      }
    });
  });
  section.querySelector('.source-tools').hidden = false;
  section.classList.add('with-picker');
  if (!followLocation()) openFile(files[0]);
}
