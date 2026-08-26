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

  // Invitación oficial a la comunidad de Telegram.
  // Se muestra una vez por entrada/sesión para no interrumpir cada navegación interna.
  const TELEGRAM_INVITE_URL = 'https://t.me/+PRaTd4Uyh8ZlNDA5';
  const TELEGRAM_MODAL_KEY = 'hbl_telegram_invite_shown';

  const installTelegramInviteStyles = () => {
    if (document.getElementById('hbl-telegram-modal-styles')) return;
    const style = document.createElement('style');
    style.id = 'hbl-telegram-modal-styles';
    style.textContent = `
      .hbl-tg-overlay{position:fixed;inset:0;z-index:99999;display:grid;place-items:center;padding:20px;background:rgba(3,8,18,.76);backdrop-filter:blur(13px);-webkit-backdrop-filter:blur(13px);opacity:0;visibility:hidden;transition:opacity .22s ease,visibility .22s ease}
      .hbl-tg-overlay.is-open{opacity:1;visibility:visible}
      .hbl-tg-modal{position:relative;width:min(94vw,470px);overflow:hidden;border-radius:28px;border:1px solid rgba(255,255,255,.12);background:linear-gradient(155deg,rgba(20,31,53,.99),rgba(7,12,24,.99));box-shadow:0 30px 90px rgba(0,0,0,.5);transform:translateY(14px) scale(.97);transition:transform .25s ease}
      .hbl-tg-overlay.is-open .hbl-tg-modal{transform:translateY(0) scale(1)}
      .hbl-tg-glow{position:absolute;width:260px;height:260px;border-radius:50%;right:-100px;top:-120px;background:radial-gradient(circle,rgba(39,167,231,.38),rgba(39,167,231,0) 70%);pointer-events:none}
      .hbl-tg-glow.two{width:220px;height:220px;left:-100px;right:auto;top:auto;bottom:-140px;background:radial-gradient(circle,rgba(37,217,166,.2),rgba(37,217,166,0) 70%)}
      .hbl-tg-close{position:absolute;right:15px;top:15px;z-index:2;width:38px;height:38px;border:1px solid rgba(255,255,255,.1);border-radius:13px;background:rgba(255,255,255,.06);color:#fff;font-size:22px;line-height:1;cursor:pointer;transition:.18s ease}
      .hbl-tg-close:hover{background:rgba(255,255,255,.12);transform:rotate(4deg)}
      .hbl-tg-content{position:relative;z-index:1;padding:34px 30px 30px;text-align:center}
      .hbl-tg-icon{width:82px;height:82px;margin:2px auto 18px;border-radius:25px;display:grid;place-items:center;background:linear-gradient(145deg,#32b7f4,#168acd);box-shadow:0 18px 42px rgba(31,157,218,.32)}
      .hbl-tg-icon svg{width:45px;height:45px;fill:#fff;transform:translate(-1px,1px)}
      .hbl-tg-kicker{display:inline-flex;align-items:center;gap:7px;padding:7px 11px;border-radius:999px;border:1px solid rgba(50,183,244,.24);background:rgba(50,183,244,.09);color:#8edaff;font-size:11px;font-weight:900;letter-spacing:.12em;text-transform:uppercase}
      .hbl-tg-title{margin:15px 0 10px;color:#fff;font-size:clamp(26px,6vw,34px);line-height:1.08;letter-spacing:-.035em}
      .hbl-tg-text{margin:0 auto;color:#aab5c9;max-width:370px;font-size:14px;line-height:1.65}
      .hbl-tg-points{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:22px 0}
      .hbl-tg-point{padding:11px 7px;border-radius:14px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);color:#dce5f2;font-size:11px;font-weight:800}
      .hbl-tg-point span{display:block;font-size:17px;margin-bottom:4px}
      .hbl-tg-actions{display:grid;grid-template-columns:1.35fr .85fr;gap:10px;margin-top:10px}
      .hbl-tg-join,.hbl-tg-later{min-height:50px;border-radius:15px;font-weight:900;font-size:14px;display:flex;align-items:center;justify-content:center;text-decoration:none;cursor:pointer;transition:.18s ease}
      .hbl-tg-join{border:0;color:#fff;background:linear-gradient(135deg,#2aabee,#178ed1);box-shadow:0 14px 28px rgba(31,159,219,.25)}
      .hbl-tg-join:hover{transform:translateY(-1px);filter:brightness(1.06)}
      .hbl-tg-later{border:1px solid rgba(255,255,255,.1);color:#d3dbea;background:rgba(255,255,255,.045)}
      .hbl-tg-later:hover{background:rgba(255,255,255,.09)}
      .hbl-tg-foot{display:block;margin-top:13px;color:#6f7c92;font-size:10px;line-height:1.4}
      @media(max-width:520px){.hbl-tg-content{padding:31px 20px 23px}.hbl-tg-modal{border-radius:24px}.hbl-tg-points{grid-template-columns:1fr}.hbl-tg-point{display:flex;align-items:center;justify-content:center;gap:7px;padding:9px}.hbl-tg-point span{display:inline;margin:0}.hbl-tg-actions{grid-template-columns:1fr}.hbl-tg-icon{width:72px;height:72px;border-radius:22px}.hbl-tg-icon svg{width:39px;height:39px}}
    `;
    document.head.appendChild(style);
  };

  const closeTelegramInvite = (overlay) => {
    overlay.classList.remove('is-open');
    document.body.style.overflow = overlay.dataset.previousOverflow || '';
    setTimeout(() => overlay.remove(), 240);
  };

  const showTelegramInvite = () => {
    if (!timezoneUrl || sessionStorage.getItem(TELEGRAM_MODAL_KEY) === '1') return;

    // Marcamos al mostrar, no al cerrar, para evitar que una recarga automática
    // por sincronización de zona horaria duplique el modal.
    sessionStorage.setItem(TELEGRAM_MODAL_KEY, '1');
    installTelegramInviteStyles();

    const overlay = document.createElement('div');
    overlay.className = 'hbl-tg-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-labelledby', 'hbl-tg-title');
    overlay.dataset.previousOverflow = document.body.style.overflow || '';
    overlay.innerHTML = `
      <section class="hbl-tg-modal">
        <div class="hbl-tg-glow"></div>
        <div class="hbl-tg-glow two"></div>
        <button class="hbl-tg-close" type="button" aria-label="Cerrar invitación">×</button>
        <div class="hbl-tg-content">
          <div class="hbl-tg-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d="M21.7 3.4 18.6 19c-.2 1.1-.9 1.4-1.8.9l-4.7-3.5-2.3 2.2c-.2.2-.5.5-1 .5l.3-4.8 8.8-7.9c.4-.3-.1-.5-.6-.2L6.4 13l-4.7-1.5c-1-.3-1-1 .2-1.5L20.3 2.9c.9-.3 1.6.2 1.4.5Z"/></svg>
          </div>
          <span class="hbl-tg-kicker">Comunidad oficial HBL</span>
          <h2 class="hbl-tg-title" id="hbl-tg-title">Únete a nuestro grupo de Telegram</h2>
          <p class="hbl-tg-text">Forma parte de la comunidad HBL para estar pendiente de novedades, avisos de la plataforma y contenido importante para los miembros.</p>
          <div class="hbl-tg-points">
            <div class="hbl-tg-point"><span>🔔</span>Avisos</div>
            <div class="hbl-tg-point"><span>🎵</span>Novedades</div>
            <div class="hbl-tg-point"><span>💬</span>Comunidad</div>
          </div>
          <div class="hbl-tg-actions">
            <a class="hbl-tg-join" href="${TELEGRAM_INVITE_URL}" target="_blank" rel="noopener noreferrer">Ir al grupo de Telegram</a>
            <button class="hbl-tg-later" type="button">Cerrar</button>
          </div>
          <small class="hbl-tg-foot">El enlace abrirá Telegram en una nueva pestaña o en la aplicación si está instalada.</small>
        </div>
      </section>
    `;

    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';

    const close = () => closeTelegramInvite(overlay);
    overlay.querySelector('.hbl-tg-close')?.addEventListener('click', close);
    overlay.querySelector('.hbl-tg-later')?.addEventListener('click', close);
    overlay.querySelector('.hbl-tg-join')?.addEventListener('click', () => setTimeout(close, 180));
    overlay.addEventListener('click', (event) => { if (event.target === overlay) close(); });
    document.addEventListener('keydown', function onEscape(event) {
      if (event.key !== 'Escape' || !document.body.contains(overlay)) return;
      document.removeEventListener('keydown', onEscape);
      close();
    });

    requestAnimationFrame(() => requestAnimationFrame(() => {
      overlay.classList.add('is-open');
      overlay.querySelector('.hbl-tg-join')?.focus({preventScroll: true});
    }));
  };

  // Al cerrar sesión limpiamos la marca: la próxima vez que el usuario entre
  // a HBL volverá a ver la invitación.
  document.querySelectorAll('.logout-form').forEach(form => {
    form.addEventListener('submit', () => sessionStorage.removeItem(TELEGRAM_MODAL_KEY));
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setTimeout(showTelegramInvite, 350), {once: true});
  } else {
    setTimeout(showTelegramInvite, 350);
  }
})();
