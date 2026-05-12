(function(){
  const I18N = window.MAAT_I18N || {};
  function tr(key){ return I18N[key] || key; }

  async function computeBrowserFingerprint(){
    const parts = [navigator.userAgent || '', navigator.language || '', navigator.platform || '', String(screen.width || ''), String(screen.height || ''), String(screen.colorDepth || ''), Intl.DateTimeFormat().resolvedOptions().timeZone || ''];
    const raw = parts.join('|');
    if(window.crypto && crypto.subtle){
      const data = new TextEncoder().encode(raw);
      const digest = await crypto.subtle.digest('SHA-256', data);
      return Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('');
    }
    let h = 0; for(let i=0;i<raw.length;i++){ h = ((h << 5) - h + raw.charCodeAt(i)) | 0; }
    return `fallback-${Math.abs(h)}`;
  }

  computeBrowserFingerprint().then(fp => {
    localStorage.setItem('maat-browser-fingerprint', fp);
    for(const input of document.querySelectorAll('input[name="browser_fingerprint"]')) input.value = fp;
  });

  function applyTheme(choice){
    const theme = choice === 'light' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-bs-theme', theme);
    localStorage.setItem('maat-theme', theme);
    for(const btn of document.querySelectorAll('[data-theme-choice]')){
      btn.classList.toggle('active', btn.dataset.themeChoice === theme);
    }
  }

  function applyFont(scale){
    const value = Math.min(1.35, Math.max(0.85, Number(scale) || 1));
    document.documentElement.style.setProperty('--maat-font-scale', String(value));
    localStorage.setItem('maat-font-scale', String(value));
  }

  function applyLanguage(lang){
    localStorage.setItem('maat-language', lang);
    document.cookie = `maat-language=${lang};path=/;max-age=31536000;samesite=lax`;
    const url = new URL(window.location.href);
    url.searchParams.set('lang', lang);
    window.location.href = url.toString();
  }

  const savedTheme = localStorage.getItem('maat-theme') || 'dark';
  applyTheme(savedTheme);
  applyFont(localStorage.getItem('maat-font-scale') || '1');

  for(const btn of document.querySelectorAll('[data-theme-choice]')){
    btn.addEventListener('click', () => applyTheme(btn.dataset.themeChoice || 'dark'));
  }
  for(const btn of document.querySelectorAll('[data-font-action]')){
    btn.addEventListener('click', () => {
      const current = Number(localStorage.getItem('maat-font-scale') || '1');
      applyFont(current + (btn.dataset.fontAction === 'increase' ? 0.05 : -0.05));
    });
  }
  for(const btn of document.querySelectorAll('[data-language-choice]')){
    btn.addEventListener('click', () => applyLanguage(btn.dataset.languageChoice || 'fr'));
  }

  const tokenInput = document.querySelector('input[name="token"]');
  if(tokenInput){
    tokenInput.value = localStorage.getItem('maat-token') || '';
    tokenInput.addEventListener('input', () => localStorage.setItem('maat-token', tokenInput.value.trim().toUpperCase()));
    const form = tokenInput.closest('form');
    if(form){
      form.addEventListener('submit', () => {
        localStorage.setItem('maat-token', tokenInput.value.trim().toUpperCase());
        const fpInput = form.querySelector('input[name="browser_fingerprint"]');
        if(fpInput && !fpInput.value) fpInput.value = localStorage.getItem('maat-browser-fingerprint') || '';
      });
    }
  }

  const heuristicInput = document.querySelector('input[name="heuristic_name"]');
  if(heuristicInput){
    heuristicInput.value = heuristicInput.value || localStorage.getItem('maat-heuristic-name') || '';
    heuristicInput.addEventListener('input', () => localStorage.setItem('maat-heuristic-name', heuristicInput.value.trim()));
    const form = heuristicInput.closest('form');
    if(form){
      form.addEventListener('submit', () => localStorage.setItem('maat-heuristic-name', heuristicInput.value.trim()));
    }
  }

  for(const button of document.querySelectorAll('[data-copy-target]')){
    button.addEventListener('click', async () => {
      const target = document.getElementById(button.dataset.copyTarget || '');
      if(!target) return;
      const original = button.textContent;
      try{
        await navigator.clipboard.writeText(target.textContent || '');
        button.textContent = tr('copied');
      }catch(_){
        const range = document.createRange();
        range.selectNodeContents(target);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        document.execCommand('copy');
        selection.removeAllRanges();
        button.textContent = tr('copied');
      }
      window.setTimeout(() => { button.textContent = original; }, 1500);
    });
  }

  function currentSubmissionToken(){
    const input = document.querySelector('input[name="token"]');
    const raw = input ? input.value : (localStorage.getItem('maat-token') || '');
    return String(raw || '').trim().toUpperCase();
  }

  function totalInstances(row){
    return row.total_instances || row.expected_instances_count || 0;
  }

  async function refreshLocalSubmissions(){
    const tbody = document.getElementById('local-submissions');
    if(!tbody) return;
    const token = currentSubmissionToken();
    const colspan = 9;
    if(!token){
      tbody.innerHTML = `<tr><td colspan="${colspan}">${tr('no_local_submissions')}</td></tr>`;
      return;
    }
    const r = await fetch(`/api/submissions?token=${encodeURIComponent(token)}`, {cache:'no-store'});
    if(!r.ok) return;
    const data = await r.json();
    const owners = JSON.parse(localStorage.getItem('maat-submission-owners') || '{}');
    const meta = window.STATUS_META || window.statusMeta || {};
    tbody.innerHTML = '';
    if(!data.rows || data.rows.length === 0){
      tbody.innerHTML = `<tr><td colspan="${colspan}">${tr('no_local_submissions')}</td></tr>`;
      return;
    }
    for(const row of data.rows){
      const m = meta[row.status] || {abbr: row.status || '—', label: row.status || '—', class: 'text-bg-secondary'};
      const trEl = document.createElement('tr');
      trEl.className = 'clickable-row';
      const owner = owners[row.submission_id] ? `?owner=${encodeURIComponent(owners[row.submission_id])}` : '';
      trEl.dataset.href = `/submission/${row.submission_id}${owner}`;
      const score = row.score_total === null || row.score_total === undefined ? '—' : Number(row.score_total).toLocaleString(window.MAAT_LANG || undefined, {maximumFractionDigits: 3});
      const total = totalInstances(row);
      trEl.innerHTML = `<td data-label="${tr('submission_id')}">${row.submission_id}</td><td data-label="${tr('status')}"><span class="badge ${m.class}" title="${m.label}">${m.abbr}</span></td><td data-label="${tr('heuristic')}">${row.heuristic_name || '—'}</td><td data-label="${tr('language')}">${row.language || '—'}</td><td data-label="${tr('main_metric')}">${score}</td><td data-label="${tr('instances_passed')}">${row.passed_instances ?? row.valid_instances ?? 0}/${total}</td><td data-label="${tr('instances_failed')}">${row.failed_instances ?? 0}/${total}</td><td data-label="${tr('date')}">${row.submitted_at || ''}</td><td data-label="${tr('download_report')}"><a class="btn btn-sm btn-report" href="/submission/${row.submission_id}/report.pdf${owner}" onclick="event.stopPropagation()">PDF</a></td>`;
      trEl.addEventListener('click', () => { window.location.href = trEl.dataset.href; });
      tbody.appendChild(trEl);
    }
  }
  refreshLocalSubmissions();
  if(document.getElementById('local-submissions')) window.setInterval(refreshLocalSubmissions, 10000);
  if(tokenInput){ tokenInput.addEventListener('input', refreshLocalSubmissions); }


  function setSubmissionDisabled(disabled){
    const form = document.getElementById('submission-form');
    if(!form) return;
    for(const item of form.querySelectorAll('input, button, select, textarea')){
      item.disabled = disabled;
    }
  }

  const countdown = document.getElementById('session-countdown');
  if(countdown){
    let remaining = Number(countdown.dataset.seconds || '0');
    const total = Math.max(1, Number(countdown.dataset.totalSeconds || countdown.dataset.seconds || '1'));
    const renderCountdown = () => {
      const h = Math.floor(remaining / 3600);
      const m = Math.floor((remaining % 3600) / 60);
      const sec = Math.floor(remaining % 60);
      countdown.textContent = `🕒 ${tr('session_remaining')}: ${h}h ${String(m).padStart(2,'0')}m ${String(sec).padStart(2,'0')}s`;
      countdown.classList.remove('text-bg-warning', 'text-bg-danger', 'text-bg-success', 'session-time-green', 'session-time-orange', 'session-time-red');
      const ratio = remaining / total;
      if(remaining <= 0){
        countdown.classList.add('session-time-red');
        setSubmissionDisabled(true);
      }else if(ratio > 2 / 3){
        countdown.classList.add('session-time-green');
      }else if(ratio > 1 / 3){
        countdown.classList.add('session-time-orange');
      }else{
        countdown.classList.add('session-time-red');
      }
    };
    renderCountdown();
    window.setInterval(() => { remaining = Math.max(0, remaining - 1); renderCountdown(); }, 1000);
  }
})();
