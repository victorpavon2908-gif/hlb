(() => {
  let activeCard = null;

  const post = async (url, body = {}) => {
    try {
      const data = new URLSearchParams(body);

      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'X-CSRFToken': window.HBL?.csrf?.() || '',
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: data,
        credentials: 'same-origin',
        redirect: 'follow'
      });

      // Si Django nos mandó al login, la sesión expiró.
      if (
        response.redirected &&
        new URL(response.url).pathname.includes('/login/')
      ) {
        return {
          ok: false,
          error: 'Tu sesión expiró. Recarga la página e inicia sesión nuevamente.'
        };
      }

      const contentType = response.headers.get('content-type') || '';
      const raw = await response.text();

      let json = null;

      if (raw && contentType.includes('application/json')) {
        try {
          json = JSON.parse(raw);
        } catch (error) {
          console.error('HBL: JSON inválido:', {
            url,
            status: response.status,
            raw
          });

          return {
            ok: false,
            error: `El servidor devolvió JSON inválido (HTTP ${response.status}).`
          };
        }
      }

      // El servidor devolvió HTML/texto en lugar de JSON.
      if (!contentType.includes('application/json')) {
        console.error('HBL: respuesta NO JSON:', {
          url,
          status: response.status,
          contentType,
          response: raw.substring(0, 1500)
        });

        if (response.status === 403) {
          return {
            ok: false,
            error: 'La solicitud fue rechazada por seguridad (CSRF 403). Recarga la página.'
          };
        }

        if (response.status === 404) {
          return {
            ok: false,
            error: 'No se encontró el endpoint de validación (HTTP 404).'
          };
        }

        if (response.status >= 500) {
          return {
            ok: false,
            error: `Error interno del servidor (HTTP ${response.status}). Revisa los Logs de Render.`
          };
        }

        return {
          ok: false,
          error: `Respuesta inesperada del servidor (HTTP ${response.status}).`
        };
      }

      if (!json || typeof json !== 'object') {
        return {
          ok: false,
          error: `Respuesta vacía o inválida del servidor (HTTP ${response.status}).`
        };
      }

      if (!response.ok) {
        return {
          ...json,
          ok: false,
          error:
            json.error ||
            json.message ||
            `La operación falló (HTTP ${response.status}).`
        };
      }

      return json;

    } catch (error) {
      console.error('HBL: error de conexión:', error);

      return {
        ok: false,
        error: 'No se pudo conectar con el servidor. Verifica tu conexión e intenta nuevamente.'
      };
    }
  };


  document.addEventListener('visibilitychange', () => {
    if (!document.hidden || !activeCard) return;

    const audio = activeCard.querySelector('audio');
    const btn = activeCard.querySelector('.play-btn');
    const status = activeCard.querySelector('.player-status');

    audio?.pause();

    if (btn && !btn.disabled) {
      btn.classList.remove('active');
      btn.textContent = '▶ Continuar';
    }

    if (status) {
      status.textContent =
        'Pausado porque la página dejó de estar visible.';
    }
  });


  document.querySelectorAll('.track-card').forEach(card => {
    const audio = card.querySelector('audio');
    const btn = card.querySelector('.play-btn');
    const status = card.querySelector('.player-status');
    const bar = card.querySelector('.progress span');

    if (!audio || !btn || !status || !bar || btn.disabled) {
      return;
    }

    let sessionId = null;
    let completing = false;
    let pingTimer = null;
    let verified = 0;

    const symbol = card.dataset.symbol || '';
    let required = Number(card.dataset.min || 10);


    const updateProgress = () => {
      const pct = required
        ? Math.min(100, (verified / required) * 100)
        : 0;

      bar.style.width = `${pct}%`;
    };


    const stopPing = () => {
      if (pingTimer) {
        clearInterval(pingTimer);
        pingTimer = null;
      }
    };


    const maybeComplete = async () => {
      if (
        !sessionId ||
        completing ||
        verified < required
      ) {
        return;
      }

      completing = true;

      status.textContent =
        `Validando ${required} segundos en el servidor…`;

      const completeUrl =
        card.dataset.completeUrl ||
        `/api/escucha/${sessionId}/completar/`;

      const res = await post(completeUrl);

      if (res.ok) {
        stopPing();

        if (Number(res.reward || 0) > 0) {
          status.textContent = res.credited
            ? `✓ Día completado · ${symbol} ${res.reward} acreditados`
            : `✓ Día ya acreditado · ${symbol} ${res.reward}`;
        } else {
          status.textContent =
            '✓ Canción verificada · continúa con las demás';
        }

        btn.classList.remove('active');
        btn.textContent = '✓ Verificada';
        btn.disabled = true;

        audio.pause();

        verified = required;
        updateProgress();

        setTimeout(() => {
          window.location.reload();
        }, 900);

        return;
      }

      console.error(
        'HBL: error completando escucha:',
        res
      );

      status.textContent =
        res.error ||
        'No se pudo validar la canción.';

      completing = false;
    };


    const sendPing = async () => {
      if (
        audio.paused ||
        document.hidden ||
        !sessionId ||
        completing
      ) {
        return;
      }

      const pingUrl =
        card.dataset.pingUrl ||
        `/api/escucha/${sessionId}/ping/`;

      const ping = await post(pingUrl);

      if (!ping.ok) {
        console.error(
          'HBL: error verificando escucha:',
          ping
        );

        status.textContent =
          ping.error ||
          'No se pudo verificar la escucha.';

        return;
      }

      verified = Number(
        ping.verified_seconds || 0
      );

      status.textContent =
        `Escucha verificada: ${Math.min(
          verified,
          required
        )}s / ${required}s`;

      updateProgress();

      await maybeComplete();
    };


    btn.addEventListener('click', async () => {

      if (!audio.paused) {
        audio.pause();

        btn.classList.remove('active');
        btn.textContent = '▶ Continuar';

        status.textContent =
          `Pausado · progreso ${Math.min(
            verified,
            required
          )}s / ${required}s`;

        return;
      }


      if (activeCard && activeCard !== card) {
        const previousAudio =
          activeCard.querySelector('audio');

        const previousButton =
          activeCard.querySelector('.play-btn');

        previousAudio?.pause();

        if (
          previousButton &&
          !previousButton.disabled
        ) {
          previousButton.classList.remove('active');
          previousButton.textContent =
            '▶ Continuar';
        }
      }


      if (!sessionId) {
        btn.disabled = true;

        status.textContent =
          'Creando sesión segura…';

        const res = await post(
          card.dataset.startUrl,
          {
            nonce:
              crypto.randomUUID?.() ||
              `${Date.now()}-${Math.random()}`
          }
        );

        btn.disabled = false;

        if (!res.ok) {
          console.error(
            'HBL: error iniciando escucha:',
            res
          );

          status.textContent =
            res.error ||
            'No se pudo iniciar la escucha.';

          return;
        }

        sessionId = res.session_id;

        if (res.min_seconds) {
          required = Number(
            res.min_seconds
          );
        }

        card.dataset.completeUrl =
          res.complete_url ||
          `/api/escucha/${sessionId}/completar/`;

        card.dataset.pingUrl =
          res.ping_url ||
          `/api/escucha/${sessionId}/ping/`;

        stopPing();

        pingTimer = setInterval(
          sendPing,
          5000
        );
      }


      try {
        await audio.play();

        activeCard = card;

        btn.classList.add('active');
        btn.textContent = '❚❚ Pausar';

        status.textContent =
          `Escuchando · ${Math.min(
            verified,
            required
          )}s / ${required}s`;

      } catch (error) {
        console.error(
          'HBL: audio.play() falló:',
          error
        );

        status.textContent =
          'El navegador bloqueó la reproducción. Pulsa nuevamente.';
      }
    });


    audio.addEventListener('pause', () => {
      if (!btn.disabled) {
        btn.classList.remove('active');
      }
    });


    audio.addEventListener('error', event => {
      console.error(
        'HBL: error cargando audio:',
        event
      );

      stopPing();

      status.textContent =
        'No se pudo cargar el audio. Verifica el archivo de la canción.';

      btn.disabled = true;
    });
  });
})();