(() => {
  const ready = (fn) => document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', fn)
    : fn();

  const initPicker = () => {
    const picker = document.querySelector('[data-crypto-picker]');
    if (!picker) return;
    const select = picker.querySelector('[data-crypto-native-select]');
    const trigger = picker.querySelector('[data-crypto-trigger]');
    const search = picker.querySelector('[data-crypto-search]');
    const showAllButton = picker.querySelector('[data-crypto-show-all]');
    const options = [...picker.querySelectorAll('[data-crypto-option]')];
    const empty = picker.querySelector('[data-crypto-empty]');
    const icon = picker.querySelector('[data-selected-icon]');
    const title = picker.querySelector('[data-selected-title]');
    const subtitle = picker.querySelector('[data-selected-subtitle]');
    if (!select || !trigger) return;

    let showAll = false;
    const compactLimit = 6;

    const applyFilter = () => {
      const query = (search?.value || '').trim().toLowerCase();
      let visible = 0;
      options.forEach((option) => {
        const rank = Number(option.dataset.rank || 9999);
        const matchesQuery = !query || (option.dataset.search || '').includes(query);
        const allowedByCompact = query || showAll || rank <= compactLimit;
        const visibleNow = Boolean(matchesQuery && allowedByCompact);
        option.hidden = !visibleNow;
        if (visibleNow) visible += 1;
      });
      if (empty) empty.style.display = visible ? 'none' : 'block';
      if (showAllButton) showAllButton.textContent = showAll ? 'Ver menos' : 'Ver todas';
    };

    const choose = (option, focusTrigger = true) => {
      if (!option) return;
      select.value = option.dataset.value || '';
      select.dispatchEvent(new Event('change', { bubbles: true }));
      options.forEach((item) => item.classList.toggle('is-selected', item === option));
      if (icon) {
        icon.textContent = option.dataset.icon || '◈';
        icon.dataset.symbol = option.dataset.symbol || '';
      }
      if (title) title.textContent = option.dataset.title || 'Criptomoneda';
      if (subtitle) subtitle.textContent = option.dataset.subtitle || 'NOWPayments';
      picker.classList.remove('open');
      trigger.setAttribute('aria-expanded', 'false');
      if (search) search.value = '';
      showAll = false;
      applyFilter();
      if (focusTrigger) trigger.focus();
    };

    const current = options.find((option) => option.dataset.value === select.value);
    if (current) choose(current, false);
    else applyFilter();

    trigger.addEventListener('click', () => {
      const willOpen = !picker.classList.contains('open');
      picker.classList.toggle('open', willOpen);
      trigger.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
      if (willOpen) {
        showAll = false;
        applyFilter();
        if (search) window.setTimeout(() => search.focus(), 20);
      }
    });

    options.forEach((option) => option.addEventListener('click', () => choose(option)));

    if (search) search.addEventListener('input', applyFilter);
    if (showAllButton) {
      showAllButton.addEventListener('click', () => {
        showAll = !showAll;
        if (showAll && search) search.value = '';
        applyFilter();
      });
    }

    document.addEventListener('click', (event) => {
      if (!picker.contains(event.target)) {
        picker.classList.remove('open');
        trigger.setAttribute('aria-expanded', 'false');
      }
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && picker.classList.contains('open')) {
        picker.classList.remove('open');
        trigger.setAttribute('aria-expanded', 'false');
        trigger.focus();
      }
    });
  };

  const formatRemaining = (milliseconds) => {
    const total = Math.max(0, Math.floor(milliseconds / 1000));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    return hours > 0
      ? `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
      : `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  };

  const postRecheck = async (root) => {
    const url = root?.dataset.recheckUrl;
    if (!url || !window.HBL?.post) return null;
    try {
      const response = await window.HBL.post(url);
      if (!response.ok) return null;
      return await response.json();
    } catch (_) {
      return null;
    }
  };

  const initTimer = () => {
    const timer = document.querySelector('[data-order-timer]');
    const root = document.querySelector('[data-wallet-root]');
    if (!timer) return;
    const expiry = Date.parse(timer.dataset.expires || '');
    const start = Date.parse(timer.dataset.start || '');
    const clock = timer.querySelector('[data-timer-clock]');
    const bar = timer.querySelector('[data-timer-bar]');
    const note = timer.querySelector('[data-timer-note]');
    if (!Number.isFinite(expiry)) return;
    const duration = Number.isFinite(start) && expiry > start ? expiry - start : null;
    let expiredHandled = false;

    const tick = async () => {
      const remaining = expiry - Date.now();
      if (clock) clock.textContent = formatRemaining(remaining);
      if (bar && duration) {
        const ratio = Math.max(0, Math.min(1, remaining / duration));
        bar.style.transform = `scaleX(${ratio})`;
      }
      if (remaining <= 0 && !expiredHandled) {
        expiredHandled = true;
        timer.classList.add('is-expired');
        if (clock) clock.textContent = '00:00';
        if (note) note.textContent = 'Tiempo agotado. Verificando el estado real con NOWPayments…';
        const data = await postRecheck(root);
        if (data) window.setTimeout(() => window.location.reload(), 900);
      }
    };

    tick();
    window.setInterval(tick, 1000);
  };

  const initPolling = () => {
    const root = document.querySelector('[data-wallet-root]');
    if (!root?.dataset.recheckUrl) return;
    let attempts = 0;
    const maxAttempts = 36;

    const poll = async () => {
      if (attempts >= maxAttempts) return;
      attempts += 1;
      const data = await postRecheck(root);
      if (!data) {
        if (attempts < maxAttempts) window.setTimeout(poll, 15000);
        return;
      }
      if (data.approved > 0 || data.expired > 0) {
        window.location.reload();
        return;
      }
      if (data.processing > 0) window.setTimeout(poll, 10000);
    };

    window.setTimeout(poll, 5000);
  };

  ready(() => {
    initPicker();
    initTimer();
    initPolling();
  });
})();
