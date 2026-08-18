(() => {
  let activeCard = null;
  const post = async (url, body = {}) => {
    const data = new URLSearchParams(body);
    const r = await fetch(url, {
      method:'POST',
      headers:{'X-CSRFToken':window.HBL.csrf(),'X-Requested-With':'XMLHttpRequest'},
      body:data,
      credentials:'same-origin'
    });
    const json = await r.json().catch(() => ({ok:false,error:'Respuesta inválida del servidor'}));
    if (!r.ok && !json.error) json.error = 'No se pudo completar la operación.';
    return json;
  };

  document.addEventListener('visibilitychange', () => {
    if (document.hidden && activeCard) {
      const audio = activeCard.querySelector('audio');
      const btn = activeCard.querySelector('.play-btn');
      const status = activeCard.querySelector('.player-status');
      audio?.pause();
      if (btn && !btn.disabled) { btn.classList.remove('active'); btn.textContent = '▶ Continuar'; }
      if (status) status.textContent = 'Pausado porque la página dejó de estar visible.';
    }
  });

  document.querySelectorAll('.track-card').forEach(card => {
    const audio = card.querySelector('audio');
    const btn = card.querySelector('.play-btn');
    const status = card.querySelector('.player-status');
    const bar = card.querySelector('.progress span');
    if (!audio || !btn || !status || !bar || btn.disabled) return;

    let sessionId = null;
    let completing = false;
    let pingTimer = null;
    let verified = 0;
    const symbol = card.dataset.symbol || '';
    const required = Number(card.dataset.min || 10);

    const updateProgress = () => {
      const pct = required ? Math.min(100, (verified / required) * 100) : 0;
      bar.style.width = `${pct}%`;
    };

    const maybeComplete = async () => {
      if (!sessionId || completing || verified < required) return;
      completing = true;
      status.textContent = `Validando ${required} segundos en el servidor…`;
      const res = await post(card.dataset.completeUrl);
      if (res.ok) {
        clearInterval(pingTimer);
        status.textContent = Number(res.reward || 0) > 0
          ? (res.credited ? `✓ Día completado · ${symbol} ${res.reward} acreditados` : `✓ Día ya acreditado · ${symbol} ${res.reward}`)
          : '✓ Canción verificada · continúa con las demás';
        btn.textContent='✓ Verificada';
        btn.disabled=true;
        audio.pause();
        bar.style.width='100%';
        setTimeout(() => location.reload(), 900);
      } else {
        status.textContent = res.error;
        completing = false;
      }
    };

    btn.addEventListener('click', async () => {
      if (audio.paused) {
        if (activeCard && activeCard !== card) activeCard.querySelector('audio')?.pause();
        if (!sessionId) {
          btn.disabled = true;
          status.textContent = 'Creando sesión segura…';
          const res = await post(card.dataset.startUrl, {nonce: crypto.randomUUID?.() || String(Date.now())});
          btn.disabled = false;
          if (!res.ok) { status.textContent = res.error; return; }
          sessionId = res.session_id;
          card.dataset.completeUrl = `/api/escucha/${sessionId}/completar/`;
          card.dataset.pingUrl = `/api/escucha/${sessionId}/ping/`;
          pingTimer = setInterval(async () => {
            if (!audio.paused && !document.hidden && sessionId && !completing) {
              const ping = await post(card.dataset.pingUrl);
              if (ping.ok) {
                verified = Number(ping.verified_seconds || 0);
                status.textContent = `Escucha verificada: ${Math.min(verified, required)}s / ${required}s`;
                updateProgress();
                await maybeComplete();
              } else if (ping.error) {
                status.textContent = ping.error;
              }
            }
          }, 5000);
        }
        try {
          await audio.play();
          activeCard = card;
          btn.classList.add('active');
          btn.textContent='❚❚ Pausar';
          status.textContent=`Escuchando · ${Math.min(verified, required)}s / ${required}s`;
        } catch (_) {
          status.textContent='El navegador bloqueó la reproducción. Pulsa otra vez.';
        }
      } else {
        audio.pause();
        btn.classList.remove('active');
        btn.textContent='▶ Continuar';
        status.textContent=`Pausado · progreso ${Math.min(verified, required)}s / ${required}s`;
      }
    });

    audio.addEventListener('pause', () => {
      if (!btn.disabled) btn.classList.remove('active');
    });
    audio.addEventListener('error', () => {
      status.textContent='No se pudo cargar el audio. Informa al soporte.';
      btn.disabled=true;
    });
  });
})();
