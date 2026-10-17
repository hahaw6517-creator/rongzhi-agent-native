'use strict';
/* 模型配置共享组件：前台「模型设置」与后台「平台托管模型」共用同一套
   供应商宫格与接口表单（同字段、同交互），提高前后台复用。
   仅负责 HTML 生成与表单收集；状态与提交逻辑由 app.js / admin.js 各自持有。
   依赖 theme-ui.js（uiSelect / uiEsc），需在本文件之前加载。 */

const mpProtocolText = p => p === 'anthropic' ? 'Anthropic 格式' : 'OpenAI 兼容格式';

const MP_ICONS = {
    check: '<path d="M20 6 9 17l-5-5"/>',
    building: '<path d="M4 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16M12 21h8M16 8h2a2 2 0 0 1 2 2v11M8 7h2M8 11h2M8 15h2"/>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/>',
    book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 19.5A2.5 2.5 0 0 0 6.5 22H20V2H6.5A2.5 2.5 0 0 0 4 4.5v15Z"/>',
    arrow: '<path d="M5 12h14m-7-7 7 7-7 7"/>'
};
const mpIcon = (name, cls = '') => `<svg class="icon ${cls}" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${MP_ICONS[name] || ''}</svg>`;

/* 供应商宫格：prefix 决定 data-action（前台 model-pick / 后台 pm-pick）。 */
function mpProvGrid(providers, prefix) {
    const items = (providers || []).map(p => `<button type="button" class="prov-item" data-action="${uiEsc(prefix)}-pick" data-provider="${uiEsc(p.providerKey)}"><strong>${uiEsc(p.name)}</strong><small>${mpProtocolText(p.protocol)}</small></button>`).join('');
    return `<div class="prov-grid">${items || '<p class="subtle-caption">暂无可选供应商，请先在管理后台添加并启用。</p>'}</div>`;
}

/* 表单顶部的供应商固定条（选中后不可再点宫格，可重选）。 */
function mpProvFixed(provider, prefix) {
    return `<div class="prov-fixed"><span class="prov-fixed-label">供应商</span><strong>${mpIcon('building')}${uiEsc(provider ? provider.name : '自定义')}</strong><button type="button" class="btn ghost small" data-action="${uiEsc(prefix)}-repick">重选</button></div>`;
}

/* 官方控制台 / 接入文档链接。 */
function mpDocLinks(provider) {
    if (!provider) return '';
    const links = [
        provider.consoleUrl ? `<a class="doc-link" href="${uiEsc(provider.consoleUrl)}" target="_blank" rel="noopener">${mpIcon('shield')}接口控制台${mpIcon('arrow')}</a>` : '',
        provider.modelDocUrl ? `<a class="doc-link" href="${uiEsc(provider.modelDocUrl)}" target="_blank" rel="noopener">${mpIcon('book')}模型接入文档${mpIcon('arrow')}</a>` : ''
    ].filter(Boolean).join('');
    return links ? `<div class="doc-links">${links}</div>` : '';
}

function mpField(label, name, value, extra = '') {
    return `<label class="field"><span>${label}</span><input name="${uiEsc(name)}" value="${uiEsc(value ?? '')}" ${extra}></label>`;
}

/* 共享接口表单。
   form：{provider, protocol, baseUrl, modelId, displayName, apiKey}
   opts：{
     mode: 'add' | 'edit',    // edit 时 API Key 提示「留空保留原值」且不强制必填
     prefix: 'model' | 'pm',  // data-action 前缀（model-* 前台 / pm-* 后台）
     firstColHtml: '',        // 与 API Key 同排的首列（前台展示名称 / 后台配置名称）
     afterHtml: '',           // API Key 之后的附加字段（后台排序 + 启用）
     submitText: ''           // 提交按钮文案，缺省按 mode 取「添加模型 / 保存修改」
   } */
function mpFormHtml(form, provider, opts = {}) {
    const mode = opts.mode === 'edit' ? 'edit' : 'add';
    const prefix = opts.prefix || 'model';
    const firstCol = opts.firstColHtml ?? mpField('展示名称（选填）', 'display_name', form.displayName, 'maxlength="64" placeholder="我的 DeepSeek"');
    return `<form id="model-form" class="mp-form" data-provider="${uiEsc(form.provider || '')}">
    ${mpProvFixed(provider, prefix)}
    <div class="fields-row">
      <label class="field"><span>接口类型</span>${uiSelect('protocol', [['openai', 'OpenAI 兼容格式'], ['anthropic', 'Anthropic 格式']], form.protocol === 'anthropic' ? 'anthropic' : 'openai')}</label>
      ${mpField('模型 ID', 'model_id', form.modelId, 'required maxlength="128" placeholder="deepseek-chat"')}
    </div>
    ${mpField('接口地址', 'base_url', form.baseUrl, 'required maxlength="255" placeholder="https://api.deepseek.com/v1" inputmode="url"')}
    <div class="fields-row">${firstCol}${mpField(mode === 'edit' ? 'API Key（留空保留原值）' : 'API Key', 'api_key', '', `type="password" maxlength="255" autocomplete="new-password"${mode === 'edit' ? '' : ' required'}`)}</div>
    ${opts.afterHtml || ''}
    ${mpDocLinks(provider)}
    <div class="form-actions"><button type="submit" class="btn primary">${mpIcon('check')}${opts.submitText || (mode === 'edit' ? '保存修改' : '添加模型')}</button><button type="button" class="btn" data-action="${uiEsc(prefix)}-cancel">取消</button></div>
    <div id="model-error" class="form-error" role="alert"></div>
  </form>`;
}

/* 收集共享表单值（前后台同构）；scope 可为 form 元素、容器元素或缺省（整个文档）。 */
function mpCollect(scope) {
    const root = scope && scope.querySelector ? scope : document;
    const form = root.matches && root.matches('#model-form') ? root : root.querySelector('#model-form');
    if (!form) return null;
    return {
        provider: form.dataset.provider || '',
        protocol: form.querySelector('[name=protocol]')?.value || 'openai',
        baseUrl: form.querySelector('[name=base_url]')?.value.trim() || '',
        modelId: form.querySelector('[name=model_id]')?.value.trim() || '',
        displayName: form.querySelector('[name=display_name]')?.value.trim() || '',
        apiKey: form.querySelector('[name=api_key]')?.value ?? ''
    };
}
