// Small UI helpers shared by the shelf and the notebook: toast, modal dialogs, popover menus.
const $ = s => document.querySelector(s);

let toastTimer;
export function toast(msg, action) {
  const t = $('#toast');
  t.replaceChildren(msg);
  if (action) {
    const b = document.createElement('button');
    b.textContent = action.label;
    b.onclick = () => { action.fn(); t.classList.remove('show'); };
    t.append(b);
  }
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), action ? 5000 : 3600);
}

export const COVER_COLORS = ['#2c4a8a', '#b8473b', '#3f7a5a', '#d29b2b', '#6b4fa0', '#2a8a8f', '#3a3a40', '#d0607a'];

function el(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const k in props) {
    if (k === 'style') for (const [p, v] of Object.entries(props[k])) n.style.setProperty(p.replace(/[A-Z]/g, c => `-${c.toLowerCase()}`), v);
    else if (k.startsWith('on')) n[k] = props[k];
    else if (k in n && k !== 'list') n[k] = props[k];
    else n.setAttribute(k, props[k]);
  }
  n.append(...kids.flat().filter(k => k != null));
  return n;
}
export { el };

// Generic modal; resolves with the submitted value or null when dismissed.
function modal(build) {
  return new Promise(resolve => {
    const root = $('#modal');
    const done = v => { root.hidden = true; root.replaceChildren(); document.removeEventListener('keydown', onKey, true); resolve(v); };
    const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); done(null); } };
    const card = build(done);
    root.replaceChildren(card);
    root.hidden = false;
    root.onpointerdown = e => { if (e.target === root) done(null); };
    document.addEventListener('keydown', onKey, true);
    requestAnimationFrame(() => [...card.querySelectorAll('input, button.primary')].find(x => !x.closest('[hidden]'))?.focus());
  });
}

// Title + cover colour (new notebook, rename).
export function notebookDialog({ heading, title = '', color = COVER_COLORS[0], submit = 'Create' }) {
  return modal(done => {
    let picked = color;
    const input = el('input', { type: 'text', value: title, placeholder: 'e.g. Calculus', maxLength: 40, autocomplete: 'off', spellcheck: false, 'aria-label': 'Notebook title' });
    const swatches = el('div', { className: 'cover-swatches', role: 'radiogroup', 'aria-label': 'Cover colour' },
      COVER_COLORS.map(c => el('button', { type: 'button', style: { '--c': c }, 'aria-pressed': String(c === picked), title: 'Cover colour', onclick(e) {
        picked = c; swatches.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', b === e.currentTarget));
        preview.style.setProperty('--cover', c);
      } })));
    const preview = el('div', { className: 'cover mini', style: { '--cover': picked } }, el('span', { className: 'label' }));
    const sync = () => { preview.querySelector('.label').textContent = input.value.trim() || 'Untitled'; };
    input.oninput = sync; sync();
    return el('form', { className: 'dialog', onsubmit(e) { e.preventDefault(); done({ title: input.value.trim() || 'Untitled', color: picked }); } },
      el('h2', {}, heading),
      el('div', { className: 'dialog-row' }, preview, el('div', { className: 'dialog-fields' }, el('label', {}, 'Title', input), el('div', { className: 'field-label' }, 'Cover'), swatches)),
      el('div', { className: 'dialog-actions' },
        el('button', { type: 'button', className: 'ghost', onclick: () => done(null) }, 'Cancel'),
        el('button', { type: 'submit', className: 'primary' }, submit)));
  });
}

export function confirmDialog({ heading, body, confirm = 'Delete', danger = true }) {
  return modal(done => el('form', { className: 'dialog small', onsubmit(e) { e.preventDefault(); done(true); } },
    el('h2', {}, heading),
    el('p', {}, body),
    el('div', { className: 'dialog-actions' },
      el('button', { type: 'button', className: 'ghost', onclick: () => done(false) }, 'Cancel'),
      el('button', { type: 'submit', className: danger ? 'primary danger' : 'primary' }, confirm))));
}

export const MATH_SYMBOLS = [
  ['∫ ', '∫', 'Integral'], ['dx', 'dx', 'dx'], ['d/dx ', 'd/dx', 'Derivative'],
  ['²', 'x²', 'Squared'], ['³', 'x³', 'Cubed'], ['√(', '√', 'Square root'],
  ['π', 'π', 'Pi'], ['sin(', 'sin', 'Sine'], ['cos(', 'cos', 'Cosine'],
  ['ln(', 'ln', 'Natural log'], ['e^(', 'eˣ', 'Exponential'], [' + C', '+ C', 'Constant C'],
];

// Fix a misread handwritten line and re-check with Meta.
export function editReadDialog({ text = '' }) {
  return modal(done => {
    const input = el('input', { type: 'text', value: text, placeholder: 'e.g. ∫ e^x / sin(x) dx', maxLength: 300, autocomplete: 'off', spellcheck: false, 'aria-label': 'What you wrote' });
    const bar = el('div', { className: 'math-bar dialog-math', role: 'toolbar', 'aria-label': 'Math symbols' },
      MATH_SYMBOLS.map(([ins, label, title]) => el('button', { type: 'button', title, onclick() {
        const s = input.selectionStart ?? input.value.length, e = input.selectionEnd ?? s;
        input.value = input.value.slice(0, s) + ins + input.value.slice(e);
        input.focus();
        input.setSelectionRange(s + ins.length, s + ins.length);
      } }, label)));
    return el('form', { className: 'dialog small', onsubmit(e) { e.preventDefault(); done(input.value.trim()); } },
      el('h2', {}, 'Fix what Meta read'),
      el('p', {}, 'Edit this line so Meta checks the exact expression you meant.'),
      el('div', { className: 'dialog-fields' }, el('label', {}, 'Expression', input), bar),
      el('div', { className: 'dialog-actions' },
        el('button', { type: 'button', className: 'ghost', onclick: () => done(null) }, 'Cancel'),
        el('button', { type: 'submit', className: 'primary' }, 'Re-check with Meta')));
  });
}

export function userInitials(user) {
  const src = (user?.display_name || user?.email || '').trim();
  if (!src) return 'M';
  if (user?.display_name?.trim()) {
    const parts = user.display_name.trim().split(/\s+/);
    return (parts[0][0] + (parts[1]?.[0] || '')).toUpperCase();
  }
  return src.slice(0, 2).toUpperCase();
}

// Cloud Account & Session Manager dialog (Sign In / Sign Up / Active Sessions / Quota).
export function accountDialog(authClient, { onSync } = {}) {
  return modal(done => {
    if (authClient.isAuthenticated()) {
      const renderQuota = u => {
        const usedBytes = u?.storage_bytes_used || 0;
        const quotaBytes = u?.storage_quota_bytes || 52428800;
        const usedMb = (usedBytes / (1024 * 1024)).toFixed(2);
        const quotaMb = (quotaBytes / (1024 * 1024)).toFixed(0);
        const pct = Math.min(100, Math.round((usedBytes / Math.max(1, quotaBytes)) * 100));
        return { usedMb, quotaMb, pct };
      };
      const u = authClient.user || {};
      const q0 = renderQuota(u);
      const quotaText = el('span', { className: 'storage-nums' }, `${q0.usedMb} / ${q0.quotaMb} MB`);
      const quotaFill = el('div', { className: 'storage-fill', style: { width: `${Math.max(3, q0.pct)}%` } });

      authClient.fetchMe?.().then(fresh => {
        if (!fresh) return;
        const q = renderQuota(fresh);
        quotaText.textContent = `${q.usedMb} / ${q.quotaMb} MB`;
        quotaFill.style.width = `${Math.max(3, q.pct)}%`;
      });

      const sessList = el('div', { className: 'sess-list' }, el('small', { className: 'sess-empty' }, 'Loading active devices…'));
      const loadSessions = () => authClient.listSessions().then(sessions => {
        if (!sessions.length) {
          sessList.replaceChildren(el('div', { className: 'sess-row' },
            el('div', { className: 'sess-meta' }, el('b', {}, 'Current Browser'), el('small', {}, 'Active now')),
            el('span', { className: 'sess-badge current' }, 'This device')));
          return;
        }
        sessList.replaceChildren(...sessions.map(s => el('div', { className: 'sess-row' },
          el('div', { className: 'sess-meta' },
            el('b', {}, s.device_name || 'Web Browser'),
            el('small', {}, `${s.ip_address ? `${s.ip_address} · ` : ''}${s.is_current ? 'Active now' : 'Signed in'}`)),
          s.is_current
            ? el('span', { className: 'sess-badge current' }, 'This device')
            : el('button', { type: 'button', className: 'ghost tiny-btn danger-text', onclick: async e => {
                e.currentTarget.disabled = true;
                e.currentTarget.textContent = 'Revoking…';
                await authClient.revokeSession(s.id);
                loadSessions();
              } }, 'Revoke'))));
      });
      loadSessions();

      const syncBtn = el('button', { type: 'button', className: 'ghost', onclick: async () => {
        syncBtn.disabled = true;
        syncBtn.textContent = 'Syncing…';
        try { await onSync?.(); done('synced'); }
        finally { syncBtn.disabled = false; syncBtn.textContent = 'Sync now'; }
      } }, 'Sync now');

      const displayName = u.display_name || (u.email ? u.email.split('@')[0] : 'Margin Account');
      return el('div', { className: 'dialog auth-dialog' },
        el('div', { className: 'auth-top' },
          el('div', { className: 'acct-profile' },
            el('div', { className: 'acct-badge' }, userInitials(u)),
            el('div', { className: 'acct-info' },
              el('div', { className: 'acct-name-row' },
                el('h2', {}, displayName),
                el('span', { className: 'sync-pill' }, 'Synced')),
              el('span', { className: 'acct-email' }, u.email || ''))),
          el('button', { type: 'button', className: 'dialog-close', 'aria-label': 'Close', onclick: () => done(null) }, '×')),
        el('div', { className: 'storage-card' },
          el('div', { className: 'storage-head' }, el('span', {}, 'Cloud Notebook Backup'), quotaText),
          el('div', { className: 'storage-bar' }, quotaFill)),
        el('div', { className: 'field-label' }, 'Active Devices & Sessions'),
        sessList,
        el('div', { className: 'dialog-actions auth-acct-actions' },
          syncBtn,
          el('button', { type: 'button', className: 'primary danger', onclick: async () => { await authClient.logout(); done('logout'); } }, 'Sign Out')));
    }

    let isRegister = false;
    const errBox = el('div', { className: 'auth-error', role: 'alert', hidden: true });
    const nameInput = el('input', { type: 'text', id: 'auth-name', name: 'name', autocomplete: 'name', placeholder: 'e.g. Ada Lovelace', maxLength: 80 });
    const nameWrap = el('label', { for: 'auth-name', className: 'auth-field', hidden: true },
      el('span', { className: 'auth-label-row' }, 'Full name', el('small', {}, 'Optional')),
      nameInput);
    const emailInput = el('input', { type: 'email', id: 'auth-email', name: 'email', autocomplete: 'username', inputMode: 'email', placeholder: 'you@example.com', required: true });
    const passInput = el('input', { type: 'password', id: 'auth-password', name: 'password', autocomplete: 'current-password', placeholder: 'Enter your password', minLength: 8, maxLength: 128, required: true });

    const pwToggle = el('button', { type: 'button', className: 'pw-toggle', 'aria-label': 'Show password', onclick() {
      const show = passInput.type === 'password';
      passInput.type = show ? 'text' : 'password';
      pwToggle.textContent = show ? 'Hide' : 'Show';
      pwToggle.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
      passInput.focus();
    } }, 'Show');

    const reqLen = el('span', { className: 'pw-chip' }, '8+ chars');
    const reqLet = el('span', { className: 'pw-chip' }, '1+ letter');
    const reqNum = el('span', { className: 'pw-chip' }, '1+ number/symbol');
    const pwHints = el('div', { className: 'pw-hints', hidden: true }, reqLen, reqLet, reqNum);

    passInput.addEventListener('input', () => {
      const v = passInput.value;
      reqLen.classList.toggle('met', v.length >= 8);
      reqLet.classList.toggle('met', /[a-zA-Z]/.test(v));
      reqNum.classList.toggle('met', /[^a-zA-Z\s]/.test(v));
    });

    const heading = el('h2', {}, 'Welcome back');
    const sub = el('p', {}, 'Sign in to sync your notebooks, handwriting, and Meta’s hints across devices.');
    const submitBtn = el('button', { type: 'submit', className: 'primary auth-submit' }, 'Sign In');
    const tabSignIn = el('button', { type: 'button', role: 'tab', 'aria-selected': 'true', onclick: () => setMode(false) }, 'Sign In');
    const tabRegister = el('button', { type: 'button', role: 'tab', 'aria-selected': 'false', onclick: () => setMode(true) }, 'Create Account');
    const footPrompt = el('span', {}, 'New to Margin?');
    const footLink = el('button', { type: 'button', className: 'auth-link', onclick: () => setMode(!isRegister) }, 'Create an account');

    function setMode(registerMode) {
      isRegister = registerMode;
      tabSignIn.setAttribute('aria-selected', String(!isRegister));
      tabRegister.setAttribute('aria-selected', String(isRegister));
      heading.textContent = isRegister ? 'Create your account' : 'Welcome back';
      sub.textContent = isRegister
        ? 'Back up your notebooks, ink, and Meta’s margin notes in the cloud.'
        : 'Sign in to sync your notebooks, handwriting, and Meta’s hints across devices.';
      nameWrap.hidden = !isRegister;
      pwHints.hidden = !isRegister;
      passInput.autocomplete = isRegister ? 'new-password' : 'current-password';
      passInput.placeholder = isRegister ? 'Create a password (8+ chars)' : 'Enter your password';
      submitBtn.textContent = isRegister ? 'Create Account' : 'Sign In';
      footPrompt.textContent = isRegister ? 'Already have an account?' : 'New to Margin?';
      footLink.textContent = isRegister ? 'Sign in' : 'Create an account';
      errBox.hidden = true;
      (isRegister ? nameInput : emailInput).focus();
    }

    return el('form', { className: 'dialog auth-dialog', novalidate: true, async onsubmit(e) {
      e.preventDefault();
      errBox.hidden = true;
      const email = emailInput.value.trim();
      const pass = passInput.value;
      if (!email) {
        errBox.textContent = 'Please enter your email address.';
        errBox.hidden = false;
        emailInput.focus();
        return;
      }
      if (!pass || (isRegister && pass.length < 8)) {
        errBox.textContent = isRegister ? 'Password must be at least 8 characters with a letter and number.' : 'Please enter your password.';
        errBox.hidden = false;
        passInput.focus();
        return;
      }
      submitBtn.disabled = true;
      submitBtn.textContent = isRegister ? 'Creating account…' : 'Signing in…';
      try {
        if (isRegister) await authClient.register(email, pass, nameInput.value);
        else await authClient.login(email, pass);
        await onSync?.();
        done('authenticated');
      } catch (err) {
        errBox.textContent = err.message || 'Authentication failed. Please check your details.';
        errBox.hidden = false;
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = isRegister ? 'Create Account' : 'Sign In';
      }
    } },
      el('div', { className: 'auth-top' },
        el('div', { className: 'auth-brand' },
          el('span', { className: 'mark-logo auth-logo' }),
          el('div', {}, heading, sub)),
        el('button', { type: 'button', className: 'dialog-close', 'aria-label': 'Close', onclick: () => done(null) }, '×')),
      el('div', { className: 'auth-tabs', role: 'tablist' }, tabSignIn, tabRegister),
      errBox,
      el('div', { className: 'dialog-fields auth-fields' },
        nameWrap,
        el('label', { for: 'auth-email', className: 'auth-field' },
          el('span', { className: 'auth-label-row' }, 'Email address'),
          emailInput),
        el('label', { for: 'auth-password', className: 'auth-field' },
          el('span', { className: 'auth-label-row' }, 'Password'),
          el('div', { className: 'pw-wrap' }, passInput, pwToggle)),
        pwHints),
      submitBtn,
      el('div', { className: 'auth-foot' }, footPrompt, footLink));
  });
}

// A popover menu anchored to a button. items: [{ label, fn, danger }]
export function popover(anchor, items) {
  closePopover();
  const r = anchor.getBoundingClientRect();
  const m = el('div', { className: 'menu popover', role: 'menu' },
    items.map(it => el('button', { type: 'button', role: 'menuitem', className: it.danger ? 'danger' : '', onclick(e) { e.stopPropagation(); closePopover(); it.fn(); } }, it.label)));
  document.body.append(m);
  const w = m.offsetWidth;
  m.style.left = `${Math.max(8, Math.min(innerWidth - w - 8, r.right - w))}px`;
  m.style.top = `${Math.min(innerHeight - m.offsetHeight - 8, r.bottom + 6)}px`;
  setTimeout(() => document.addEventListener('pointerdown', outside, true));
}
function outside(e) { if (!e.target.closest('.popover')) closePopover(); }
export function closePopover() {
  document.querySelectorAll('.popover').forEach(p => p.remove());
  document.removeEventListener('pointerdown', outside, true);
}
