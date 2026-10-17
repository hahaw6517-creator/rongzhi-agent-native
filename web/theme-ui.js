'use strict';
/* 主题化 UI 原子组件：下拉（ui-select）与对话框（ui-confirm / ui-alert），
   统一替换浏览器原生 <select> 弹层与 confirm()/alert()。
   前台工作台与管理后台共用本文件；下拉用隐藏 input 携带值，
   兼容 FormData 与 [name=x].value 两种读取方式。 */

const uiEsc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const UI_CARET_SVG = '<svg class="icon ui-select-caret" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>';
const UI_CHECK_SVG = '<svg class="icon ui-select-check" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>';
const UI_WARN_SVG = '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>';

/* ---- 主题化下拉 ----
   options：'a' | ['value','label'] | {value,label}；value：当前值；extra：附加到容器上的属性。 */
function uiSelect(name, options, value, extra = '') {
    const norm = options.map(o => typeof o === 'string' ? { value: o, label: o } : Array.isArray(o) ? { value: o[0], label: o[1] ?? o[0] } : o);
    const current = norm.find(o => String(o.value) === String(value)) || norm[0];
    const items = norm.map(o => {
        const on = current && String(o.value) === String(current.value);
        return `<button type="button" class="ui-select-option${on ? ' selected' : ''}" role="option" aria-selected="${on}" data-value="${uiEsc(o.value)}"><span>${uiEsc(o.label)}</span>${on ? UI_CHECK_SVG : ''}</button>`;
    }).join('');
    return `<div class="ui-select" data-ui-select${extra ? ' ' + extra : ''}>
    <input type="hidden" name="${uiEsc(name)}" value="${uiEsc(current ? current.value : '')}">
    <button type="button" class="ui-select-trigger" aria-haspopup="listbox" aria-expanded="false"><span class="ui-select-value">${uiEsc(current ? current.label : '请选择')}</span>${UI_CARET_SVG}</button>
    <div class="ui-select-list" role="listbox">${items}</div>
  </div>`;
}

function uiCloseSelect(el) {
    el.classList.remove('open');
    el.querySelector('.ui-select-trigger')?.setAttribute('aria-expanded', 'false');
}

/* 选中某项：同步隐藏值、展示文本与选中态，值变化时派发 change（冒泡，供监听方刷新联动）。 */
function uiChooseOption(select, option) {
    const hidden = select.querySelector('input[type=hidden]');
    if (!hidden) return;
    const changed = hidden.value !== option.dataset.value;
    hidden.value = option.dataset.value;
    select.querySelector('.ui-select-value').textContent = option.querySelector('span')?.textContent || option.textContent;
    select.querySelectorAll('.ui-select-option').forEach(o => {
        const on = o === option;
        o.classList.toggle('selected', on);
        o.setAttribute('aria-selected', on ? 'true' : 'false');
        if (on && !o.querySelector('.ui-select-check')) o.insertAdjacentHTML('beforeend', UI_CHECK_SVG);
        else if (!on) o.querySelector('.ui-select-check')?.remove();
    });
    uiCloseSelect(select);
    if (changed) hidden.dispatchEvent(new Event('change', { bubbles: true }));
}

/* 点击外部收起；点触发器开合；点选项选中。全局只绑一次。
   用捕获阶段：app.js 在 .dialog/.drawer 上 stopPropagation() 拦截冒泡，
   捕获先于面板处理，保证弹窗内的下拉与确认弹窗正常响应。 */
document.addEventListener('click', ev => {
    const select = ev.target.closest('[data-ui-select]');
    document.querySelectorAll('[data-ui-select].open').forEach(el => { if (el !== select) uiCloseSelect(el); });
    if (!select) return;
    const option = ev.target.closest('.ui-select-option');
    if (option) { uiChooseOption(select, option); return; }
    if (ev.target.closest('.ui-select-trigger')) {
        const open = select.classList.toggle('open');
        select.querySelector('.ui-select-trigger').setAttribute('aria-expanded', open ? 'true' : 'false');
        if (open) select.querySelector('.ui-select-option.selected')?.focus({ preventScroll: true });
    }
}, true);

/* 键盘可达：Enter/Space/方向键打开，上下移动、Enter 选中、Esc/Tab 收起。 */
document.addEventListener('keydown', ev => {
    const select = ev.target instanceof Element ? ev.target.closest('[data-ui-select]') : null;
    if (!select) return;
    const options = [...select.querySelectorAll('.ui-select-option')];
    const trigger = select.querySelector('.ui-select-trigger');
    if (!select.classList.contains('open')) {
        if (['Enter', ' ', 'ArrowDown', 'ArrowUp'].includes(ev.key)) {
            ev.preventDefault();
            select.classList.add('open');
            trigger?.setAttribute('aria-expanded', 'true');
            (options.find(o => o.classList.contains('selected')) || options[0])?.focus({ preventScroll: true });
        }
        return;
    }
    const index = options.indexOf(document.activeElement);
    if (ev.key === 'ArrowDown') { ev.preventDefault(); options[(index + 1 + options.length) % options.length]?.focus({ preventScroll: true }); }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); options[(index - 1 + options.length) % options.length]?.focus({ preventScroll: true }); }
    else if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        if (document.activeElement?.classList.contains('ui-select-option')) uiChooseOption(select, document.activeElement);
        else { select.classList.add('open'); trigger?.setAttribute('aria-expanded', 'true'); }
    }
    else if (ev.key === 'Escape') { uiCloseSelect(select); trigger?.focus({ preventScroll: true }); }
    else if (ev.key === 'Tab') uiCloseSelect(select);
});

/* ---- 主题化对话框：替代 confirm() / alert()，返回 Promise ----
   danger 为真时确认按钮呈警示红、默认焦点落在取消键（防误触）。 */
function uiDialog({ title = '确认操作', message = '', confirmText = '确认', cancelText = '取消', danger = false, cancel = true } = {}) {
    return new Promise(resolve => {
        const backdrop = document.createElement('div');
        backdrop.className = 'dialog-backdrop ui-confirm-backdrop';
        backdrop.innerHTML = `<div class="dialog ui-confirm" role="alertdialog" aria-modal="true" aria-label="${uiEsc(title)}">
      <div class="ui-confirm-icon${danger ? ' danger' : ''}" aria-hidden="true">${UI_WARN_SVG}</div>
      <h2>${uiEsc(title)}</h2>
      ${message ? `<p>${uiEsc(message)}</p>` : ''}
      <div class="form-actions">
        ${cancel ? `<button type="button" class="btn" data-ui-action="cancel">${uiEsc(cancelText)}</button>` : ''}
        <button type="button" class="btn ${danger ? 'danger' : 'primary'}" data-ui-action="confirm">${uiEsc(confirmText)}</button>
      </div>
    </div>`;
        const finish = val => {
            document.removeEventListener('keydown', onKey, true);
            backdrop.remove();
            resolve(val);
        };
        const onKey = ev => {
            if (ev.key === 'Escape') { ev.stopPropagation(); finish(false); }
            else if (ev.key === 'Enter' && !(ev.target instanceof Element && ev.target.closest('button'))) { ev.preventDefault(); finish(true); }
        };
        backdrop.addEventListener('click', ev => {
            if (ev.target === backdrop) { finish(false); return; }
            const action = ev.target.closest('[data-ui-action]')?.dataset.uiAction;
            if (action === 'confirm') finish(true);
            else if (action === 'cancel') finish(false);
        });
        document.addEventListener('keydown', onKey, true);
        document.body.append(backdrop);
        backdrop.querySelector(danger && cancel ? '[data-ui-action=cancel]' : '[data-ui-action=confirm]')?.focus();
    });
}

function uiConfirm(opts = {}) {
    return uiDialog({ confirmText: '确认', cancelText: '取消', ...opts });
}

/* 带输入框的主题化弹窗：返回 Promise<string|null>（确认返回输入值，取消返回 null）。
   用于后台重置密码等需要现场录入的场景。 */
function uiPrompt({ title = '请输入', message = '', placeholder = '', type = 'text', value = '', confirmText = '确认', cancelText = '取消', required = false, minlength = 0, danger = false } = {}) {
    return new Promise(resolve => {
        const backdrop = document.createElement('div');
        backdrop.className = 'dialog-backdrop ui-confirm-backdrop';
        backdrop.innerHTML = `<div class="dialog ui-confirm" role="alertdialog" aria-modal="true" aria-label="${uiEsc(title)}">
      <div class="ui-confirm-icon${danger ? ' danger' : ''}" aria-hidden="true">${UI_WARN_SVG}</div>
      <h2>${uiEsc(title)}</h2>
      ${message ? `<p>${uiEsc(message)}</p>` : ''}
      <form class="ui-prompt-form">
        <input class="ui-prompt-input" type="${uiEsc(type)}" value="${uiEsc(value)}" placeholder="${uiEsc(placeholder)}"
          ${minlength ? `minlength="${minlength}"` : ''} ${required ? 'required' : ''} autocomplete="off">
        <div class="form-error" role="alert"></div>
        <div class="form-actions">
          <button type="button" class="btn" data-ui-action="cancel">${uiEsc(cancelText)}</button>
          <button type="submit" class="btn ${danger ? 'danger' : 'primary'}" data-ui-action="confirm">${uiEsc(confirmText)}</button>
        </div>
      </form>
    </div>`;
        const finish = val => { document.removeEventListener('keydown', onKey, true); backdrop.remove(); resolve(val); };
        const onKey = ev => { if (ev.key === 'Escape') { ev.stopPropagation(); finish(null); } };
        backdrop.querySelector('.ui-prompt-input')?.focus();
        backdrop.querySelector('form').addEventListener('submit', ev => {
            ev.preventDefault();
            const input = ev.currentTarget.querySelector('.ui-prompt-input');
            if (required && !input.value.trim()) { ev.currentTarget.querySelector('.form-error').textContent = '请填写内容'; input.focus(); return; }
            if (minlength && input.value.length < minlength) { ev.currentTarget.querySelector('.form-error').textContent = `至少 ${minlength} 个字符`; input.focus(); return; }
            finish(input.value);
        });
        backdrop.addEventListener('click', ev => {
            if (ev.target === backdrop) { finish(null); return; }
            if (ev.target.closest('[data-ui-action=cancel]')) finish(null);
        });
        document.addEventListener('keydown', onKey, true);
        document.body.append(backdrop);
    });
}
