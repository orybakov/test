(() => {
  'use strict';
  const el = id => document.getElementById(id);
  let key = sessionStorage.getItem('sentinel_api_key') || '';
  let soundOn = false, lastSpoken = 0, knownReady = null, polling = false;
  const formatTime = timestamp => new Date(timestamp * 1000).toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit'});
  const toast = text => { const t = el('toast'); t.textContent = text; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 4000); };
  function setAuthorized(ok) {
    el('connect').classList.toggle('hidden', ok);
    el('app-content').classList.toggle('hidden', !ok);
    el('disconnect').classList.toggle('hidden', !ok);
  }
  async function api(path, method = 'GET') {
    const response = await fetch(path, {method, headers: {'X-API-Key': key}, cache: 'no-store'});
    if (response.status === 401) {sessionStorage.removeItem('sentinel_api_key'); key = ''; setAuthorized(false); throw new Error('Неверный API-ключ');}
    if (!response.ok) throw new Error(`Ошибка сервера: ${response.status}`);
    return response.json();
  }
  function levelClass(level) {return ['critical','important','normal','silent'].includes(level) ? level : 'normal';}
  function createEvent(event) {
    const node = document.createElement('article'); node.className = 'event';
    const icon = document.createElement('span'); icon.className = 'event-icon ' + levelClass(event.priority);
    icon.textContent = ({critical:'!',important:'◆',normal:'◉',silent:'·'})[event.priority] || '◉';
    const body = document.createElement('div'); body.className = 'event-body';
    const head = document.createElement('div'); head.className = 'event-head';
    const title = document.createElement('span'); title.className = 'event-title'; title.textContent = event.title;
    const time = document.createElement('span'); time.className = 'event-time'; time.textContent = formatTime(event.created_at);
    head.append(title, time);
    const msg = document.createElement('p'); msg.className = 'event-message'; msg.textContent = event.message || event.speech;
    const meta = document.createElement('div'); meta.className = 'event-meta';
    const src = document.createElement('span'); src.className = 'pill'; src.textContent = event.source;
    const status = document.createElement('span'); status.textContent = event.status;
    meta.append(src, status);
    if (event.error) {const warn = document.createElement('span'); warn.textContent = '⚠ ' + event.error; warn.title = event.error; meta.append(warn);}
    body.append(head, msg, meta); node.append(icon, body);
    if (event.status === 'ready') {
      const play = document.createElement('button'); play.className = 'play-btn';
      play.textContent = '▶'; play.type = 'button'; play.setAttribute('aria-label', 'Прослушать сообщение');
      play.addEventListener('click', () => speak(event)); node.append(play);
    }
    return node;
  }
  async function speak(event) {
    try {
      if (event.audio_file) {
        const response = await fetch(`/api/events/${event.id}/audio`, {headers: {'X-API-Key': key}});
        if (response.ok) {
          const url = URL.createObjectURL(await response.blob());
          const audio = new Audio(url);
          audio.addEventListener('ended', () => URL.revokeObjectURL(url), {once:true});
          audio.addEventListener('error', () => URL.revokeObjectURL(url), {once:true});
          await audio.play(); return;
        }
      }
      if (!('speechSynthesis' in window)) {toast('На этом устройстве нет синтезатора речи'); return;}
      speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(event.speech || `${event.title}. ${event.message}`);
      utterance.lang = 'ru-RU'; utterance.rate = 1.04;
      speechSynthesis.speak(utterance);
    } catch (err) {toast('Не удалось воспроизвести: ' + err.message);}
  }
  async function refresh() {
    if (!key || polling) return;
    polling = true;
    try {
      const data = await api('/api/events');
      setAuthorized(true);
      el('count-total').textContent = data.stats.total || 0;
      el('count-attention').textContent = (data.stats.priority_important || 0) + (data.stats.priority_critical || 0);
      el('count-ready').textContent = data.stats.ready || 0;
      el('tts-badge').textContent = data.tts_provider === 'qwen' ? 'QWEN3-TTS' : 'BROWSER TTS';
      el('telegram-status').textContent = data.telegram_enabled ? 'ПОДКЛЮЧЕН' : 'НЕ НАСТРОЕН';
      el('telegram-status').classList.toggle('enabled', data.telegram_enabled);
      el('llm-status').textContent = data.llm_enabled ? 'LLM ВКЛЮЧЕН' : 'ПРАВИЛА';
      el('llm-status').classList.toggle('enabled', data.llm_enabled);
      const ready = data.events.filter(x => x.status === 'ready');
      if (knownReady !== null && soundOn) {
        const newReady = ready.filter(x => x.id > lastSpoken && !knownReady.has(x.id));
        if (newReady.length) {const next = newReady.sort((a,b) => b.id - a.id)[0]; lastSpoken = next.id; await speak(next);}
      }
      knownReady = new Set(ready.map(x => x.id));
      const list = el('events'); list.replaceChildren();
      if (!data.events.length) {const empty = document.createElement('div'); empty.className = 'empty'; empty.textContent = 'Пока нет событий. Нажми «Проверить уведомление», чтобы начать.'; list.append(empty);}
      else data.events.forEach(event => list.append(createEvent(event)));
    } catch (err) {toast(err.message);} finally {polling = false;}
  }
  el('auth-form').addEventListener('submit', e => {e.preventDefault(); key = el('key').value.trim(); sessionStorage.setItem('sentinel_api_key', key); refresh();});
  el('sound-toggle').addEventListener('click', () => {
    soundOn = !soundOn;
    el('sound-toggle').classList.toggle('active', soundOn);
    el('sound-toggle').setAttribute('aria-checked', String(soundOn));
    if (soundOn) {lastSpoken = Math.max(0,...(knownReady ? [...knownReady] : [0])); toast('Звук включён — новые события будут озвучиваться');}
    else {if ('speechSynthesis' in window) speechSynthesis.cancel(); toast('Звук выключен');}
  });
  el('demo').addEventListener('click', async () => {try {await api('/api/demo', 'POST'); toast('Тестовое событие создано'); await refresh();} catch(e){toast(e.message);}});
  el('digest').addEventListener('click', async () => {try {const r = await api('/api/digest', 'POST'); toast(`Добавлено в дайджест: ${r.digested}`); await refresh();} catch(e){toast(e.message);}});
  el('disconnect').addEventListener('click', () => {sessionStorage.removeItem('sentinel_api_key'); key = ''; soundOn = false; knownReady = null; setAuthorized(false);});
  function clock() {el('clock').textContent = new Date().toLocaleString('ru-RU', {day:'2-digit',month:'long',hour:'2-digit',minute:'2-digit'});}
  clock(); setInterval(clock, 30000); if (key) refresh(); setInterval(refresh, 4000);
})();
