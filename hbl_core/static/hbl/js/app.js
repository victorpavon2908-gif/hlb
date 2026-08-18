(() => {
  const csrf = () => document.cookie.split('; ').find(v => v.startsWith('csrftoken='))?.split('=')[1] || '';
  const post = async (url, body = {}) => {
    const data = new URLSearchParams(body);
    return fetch(url, {
      method: 'POST',
      headers: {'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest'},
      body: data,
      credentials: 'same-origin',
    });
  };
  window.HBL = { csrf, post };

  const detectedTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const timezoneInput = document.getElementById('id_timezone_name');
  if (timezoneInput) timezoneInput.value = detectedTimezone;

  const timezoneUrl = document.body?.dataset?.timezoneUrl;
  if (timezoneUrl) {
    const saved = sessionStorage.getItem('hbl_timezone_synced');
    if (saved !== detectedTimezone) {
      post(timezoneUrl, {timezone: detectedTimezone})
        .then(async r => {
          if (!r.ok) return;
          const data = await r.json().catch(() => ({}));
          // Guardamos la zona detectada como "intentada" para no bombardear el
          // endpoint si la zona de recompensa ya quedó bloqueada en la cuenta.
          sessionStorage.setItem('hbl_timezone_synced', detectedTimezone);
          // Solo recargamos cuando el servidor realmente cambió la zona; así se
          // regeneran las tareas con la fecha local correcta sin bucles.
          if (data.changed) location.reload();
        })
        .catch(() => {});
    }

    // Las tareas se generan bajo demanda. Recargamos la interfaz justo después
    // de la medianoche local para que aparezca la nueva playlist del día.
    const scheduleMidnightRefresh = () => {
      const now = new Date();
      const next = new Date(now);
      next.setHours(24, 0, 3, 0);
      const delay = Math.max(1000, next.getTime() - now.getTime());
      setTimeout(() => location.reload(), delay);
    };
    scheduleMidnightRefresh();
  }

  document.querySelectorAll('[data-copy],[data-copy-text]').forEach(btn => btn.addEventListener('click', async () => {
    const el = btn.dataset.copy ? document.querySelector(btn.dataset.copy) : null;
    const text = btn.dataset.copyText || el?.value || el?.textContent || '';
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      const previous = btn.textContent;
      btn.textContent = 'Copiado';
      setTimeout(() => { btn.textContent = previous || 'Copiar'; }, 1400);
    } catch (_) {
      if (el) { el.select?.(); document.execCommand('copy'); }
    }
  }));
})();
