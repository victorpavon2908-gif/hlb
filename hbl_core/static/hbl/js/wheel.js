(() => {
  const wheel = document.querySelector('#hbl-wheel');
  const button = document.querySelector('#wheel-spin-btn');
  const result = document.querySelector('#wheel-result');
  const dataNodes = [...document.querySelectorAll('#wheel-prizes-data i')];
  if (!wheel || !button || !dataNodes.length) return;

  const prizes = dataNodes.map((n, index) => ({
    id: Number(n.dataset.id), name: n.dataset.name, icon: n.dataset.icon || '🎁',
    color: n.dataset.color || '#7C5CFC', index,
  }));
  const segment = 360 / prizes.length;
  const gradient = prizes.map((p, i) => `${p.color} ${i * segment}deg ${(i + 1) * segment}deg`).join(',');
  wheel.style.background = `conic-gradient(from -90deg, ${gradient})`;

  prizes.forEach((p, i) => {
    const label = document.createElement('span');
    label.className = 'wheel-label';
    const angle = i * segment + segment / 2;
    label.style.setProperty('--angle', `${angle}deg`);
    const icon = document.createElement('b'); icon.textContent = p.icon;
    const name = document.createElement('small'); name.textContent = p.name;
    label.append(icon, name);
    wheel.appendChild(label);
  });

  let rotation = 0;
  button.addEventListener('click', async () => {
    if (button.disabled) return;
    button.disabled = true;
    result.textContent = 'Girando…';
    try {
      const response = await fetch(wheel.dataset.spinUrl, {
        method: 'POST', headers: {'X-CSRFToken': window.HBL?.csrf?.() || '', 'X-Requested-With': 'XMLHttpRequest'},
      });
      const data = await response.json();
      if (!data.ok) throw new Error(data.error || 'No se pudo girar.');
      const selected = prizes.find(p => p.id === Number(data.prize_id)) || prizes[0];
      const targetCenter = selected.index * segment + segment / 2;
      const extra = 5 * 360;
      const desired = 360 - targetCenter;
      rotation = Math.ceil(rotation / 360) * 360 + extra + desired;
      wheel.style.transform = `rotate(${rotation}deg)`;
      window.setTimeout(() => {
        result.replaceChildren();
        const icon = document.createTextNode(`${data.icon || '🎁'} `);
        const name = document.createElement('b'); name.textContent = data.prize || 'Premio';
        result.append(icon, name);
        button.textContent = 'Giro usado';
      }, 3900);
    } catch (err) {
      result.textContent = err.message;
      button.disabled = false;
    }
  });
})();
