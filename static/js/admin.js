const CSRF_TOKEN = document
    .querySelector('input[name="csrf_token"]')?.value || '';

function log(msg) {
    const el = document.getElementById('console');
    el.innerText = msg;
}

async function api(url, options) {
    const res = await fetch(url, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': CSRF_TOKEN,
            ...options.headers,
        },
    });
    return res.json();
}

// --- Tabs ---
function activateTab(tabName) {
    document.querySelectorAll('.tab-btn').forEach(function(b) {
        b.classList.toggle('active', b.dataset.tab === tabName);
    });
    document.querySelectorAll('.tab-content').forEach(function(c) {
        c.classList.toggle('active', c.id === 'tab-' + tabName);
    });
    window.location.hash = tabName;
}

document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.tab-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            activateTab(this.dataset.tab);
        });
    });

    // Restore active tab from URL hash on page load
    var hash = window.location.hash.replace('#', '');
    if (hash && document.getElementById('tab-' + hash)) {
        activateTab(hash);
    }
});

// --- Domain Form ---
const GRADIENTS = [
    'linear-gradient(45deg, #00f2fe, #4facfe)',
    'linear-gradient(45deg, #11998e, #38ef7d)',
    'linear-gradient(45deg, #ff9966, #ff5e62)',
    'linear-gradient(45deg, #8a2387, #e94057)',
    'linear-gradient(45deg, #fce38a, #f38181)',
    'linear-gradient(45deg, #f12711, #f5af19)',
    'linear-gradient(45deg, #3a7bd5, #3a6073)',
    'linear-gradient(45deg, #e01c34, #670010)',
    'linear-gradient(45deg, #00b4db, #0083b0)',
    'linear-gradient(45deg, #667eea, #764ba2)',
    'linear-gradient(45deg, #f093fb, #f5576c)',
    'linear-gradient(45deg, #4facfe, #00f2fe)',
    'linear-gradient(45deg, #43e97b, #38f9d7)',
    'linear-gradient(45deg, #fa709a, #fee140)',
    'linear-gradient(45deg, #a18cd1, #fbc2eb)',
    'linear-gradient(45deg, #fccb90, #d57eeb)',
    'linear-gradient(45deg, #e0c3fc, #8ec5fc)',
    'linear-gradient(45deg, #f5576c, #ff6a88)',
    'linear-gradient(45deg, #89f7fe, #66a6ff)',
    'linear-gradient(45deg, #fddb92, #d1fdff)',
    'linear-gradient(45deg, #9890e3, #b1f4cf)',
    'linear-gradient(45deg, #ebc0fd, #d9ded8)',
    'linear-gradient(45deg, #f6d365, #fda085)',
    'linear-gradient(45deg, #fbc2eb, #a6c1ee)',
    'linear-gradient(45deg, #fdcbf1, #e6dee9)',
    'linear-gradient(45deg, #a1c4fd, #c2e9fb)',
    'linear-gradient(45deg, #d4fc79, #96e6a1)',
    'linear-gradient(45deg, #84fab0, #8fd3f4)',
    'linear-gradient(45deg, #cfd9df, #e2ebf0)',
    'linear-gradient(45deg, #a6c0fe, #f68084)',
    'linear-gradient(45deg, #e6b980, #eacda3)',
    'linear-gradient(45deg, #f5f7fa, #c3cfe2)',
    'linear-gradient(45deg, #ffecd2, #fcb69f)',
    'linear-gradient(45deg, #ff758c, #ff7eb3)',
    'linear-gradient(45deg, #6a11cb, #2575fc)',
    'linear-gradient(45deg, #c471f5, #fa71cd)',
    'linear-gradient(45deg, #48c6ef, #6f86d6)',
    'linear-gradient(45deg, #feada6, #f5efef)',
    'linear-gradient(45deg, #a8edea, #fed6e3)',
    'linear-gradient(45deg, #d299c2, #fef9d7)',
    'linear-gradient(45deg, #7f7fd5, #86a8e7)',
    'linear-gradient(45deg, #fbc2eb, #a18cd1)',
    'linear-gradient(45deg, #ff9a9e, #fecfef)',
    'linear-gradient(45deg, #96fbc4, #f9f586)',
    'linear-gradient(45deg, #f4d03f, #16a085)',
    'linear-gradient(45deg, #e55d87, #5fc3e4)',
    'linear-gradient(45deg, #16a085, #f4d03f)',
    'linear-gradient(45deg, #b224ef, #7579ff)',
    'linear-gradient(45deg, #ff6a00, #ee0979)',
    'linear-gradient(45deg, #00c6ff, #0072ff)',
    'linear-gradient(45deg, #fc5c7d, #6a82fb)',
    'linear-gradient(45deg, #2b5876, #4e4376)',
    'linear-gradient(45deg, #f78ca0, #f9748f)',
    'linear-gradient(45deg, #c33764, #1d2671)',
];

function randomGradient() {
    return GRADIENTS[Math.floor(Math.random() * GRADIENTS.length)];
}

const form = document.getElementById('domain-form');
const editIndexInput = document.getElementById('edit-index');
const cancelBtn = document.getElementById('cancel-edit');

form.addEventListener('submit', function(e) {
    e.preventDefault();
    const idx = parseInt(editIndexInput.value);
    const data = {
        domain: document.getElementById('domain').value,
        keyword: document.getElementById('keyword').value,
        gradient: idx >= 0
            ? document.querySelector(
                `tr[data-index="${idx}"] .color-preview`
              )?.dataset.gradient || randomGradient()
            : randomGradient(),
    };

    const method = idx >= 0 ? 'PUT' : 'POST';
    const url = idx >= 0 ? `/api/domains/${idx}` : '/api/domains';

    api(url, { method, body: JSON.stringify(data) }).then(res => {
        log(res.status === 'success'
            ? `✅ ${res.message}` : `❌ ${res.message}`);
        if (res.status === 'success') {
            // Auto-apply config after saving domain
            log('⏳ 正在编译并重载 Nginx，请勿刷新网页...');
            api('/api/apply', { method: 'POST' }).then(applyRes => {
                log(applyRes.status === 'success'
                    ? `✅ ${applyRes.message}` : `❌ ${applyRes.message}`);
                location.reload();
            });
        }
    });
});

cancelBtn.addEventListener('click', function() {
    editIndexInput.value = -1;
    form.reset();
    cancelBtn.style.display = 'none';
});

function editDomain(index) {
    const row = document.querySelector(`tr[data-index="${index}"]`);
    if (!row) return;
    const cells = row.querySelectorAll('td');
    document.getElementById('domain').value = cells[0].textContent.trim();
    document.getElementById('keyword').value = cells[1].textContent.trim();
    editIndexInput.value = index;
    cancelBtn.style.display = 'block';
    // Switch to domains tab
    activateTab('domains');
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function deleteDomain(index) {
    if (!confirm('确定删除该域名吗？')) return;
    api(`/api/domains/${index}`, { method: 'DELETE' }).then(res => {
        log(res.status === 'success'
            ? `✅ ${res.message}` : `❌ ${res.message}`);
        if (res.status === 'success') {
            log('⏳ 正在编译并重载 Nginx，请勿刷新网页...');
            api('/api/apply', { method: 'POST' }).then(applyRes => {
                log(applyRes.status === 'success'
                    ? `✅ ${applyRes.message}` : `❌ ${applyRes.message}`);
                location.reload();
            });
        }
    });
}

// --- Certificate Status ---
function loadCertStatus() {
    api('/api/ssl/status', { method: 'GET' }).then(data => {
        data.certificates.forEach(cert => {
            const cell = document.querySelector(
                `.cert-expiry[data-domain="${cert.domain}"]`);
            if (cell) {
                if (cert.https_enabled && cert.expiry) {
                    cell.textContent = cert.expiry;
                } else if (cert.https_enabled) {
                    cell.textContent = '已启用';
                } else {
                    cell.textContent = '-';
                }
            }
        });
    });
}

// --- Per-Domain HTTPS Toggle ---
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.https-toggle').forEach(function(toggle) {
        toggle.addEventListener('change', function() {
            const index = this.dataset.index;
            const domain = this.dataset.domain;
            const enabled = this.checked;

            log(`⏳ 正在${enabled ? '启用' : '关闭'} ${domain} 的 HTTPS...`);

            api(`/api/domains/${index}/https`, {
                method: 'PUT',
                body: JSON.stringify({ https_enabled: enabled }),
            }).then(res => {
                if (res.status === 'success') {
                    log(`✅ ${res.message}`);
                    location.reload();
                } else if (res.status === 'error') {
                    log(`❌ ${res.message}`);
                    toggle.checked = !enabled;
                    location.reload();
                } else {
                    log(`❌ ${res.message}`);
                    toggle.checked = !enabled;
                }
            });
        });
    });
});

// --- DNS Check ---
const STATUS_MAP = {
    ok: '正常',
    no_record: '无记录',
    not_found: '域名不存在',
    timeout: '超时',
    error: '错误',
};

function checkAllDNS() {
    const section = document.getElementById('dns-section');
    section.style.display = 'block';
    log('⏳ 正在批量检测域名 A 记录...');

    api('/api/dns/check', { method: 'POST' }).then(data => {
        const tbody = document.getElementById('dns-results');
        tbody.innerHTML = '';
        data.results.forEach(r => {
            const tr = document.createElement('tr');
            const records = r.a_records.length > 0
                ? r.a_records.join(', ') : '-';
            const ttl = r.ttl !== null && r.ttl !== undefined
                ? `${r.ttl}s` : '-';
            const statusText = STATUS_MAP[r.status] || r.status;
            tr.innerHTML = `
                <td><strong>${r.domain}</strong></td>
                <td><code>${records}</code></td>
                <td>${statusText}</td>
                <td>${ttl}</td>
            `;
            tbody.appendChild(tr);
        });
        document.getElementById('last-check').textContent = (
            `上次检测: ${new Date(data.timestamp).toLocaleString()}`);
        log(`✅ DNS 检测完成，共检测 ${data.total} 个域名`);
    });
}

// --- Settings ---
function loadSettings() {
    api('/api/settings', { method: 'GET' }).then(data => {
        document.getElementById('allowed-ips').value = data.allowed_ips || '';
    });
}

function saveSettings() {
    const payload = {
        allowed_ips: document.getElementById('allowed-ips').value.trim(),
    };
    api('/api/settings', {
        method: 'PUT', body: JSON.stringify(payload),
    }).then(res => {
        log(res.status === 'success' ? `✅ ${res.message}` : `❌ ${res.message}`);
    });
}

function changePassword() {
    const newPassword = document.getElementById('admin-password').value;
    if (!newPassword) {
        log('❌ 请输入新密码');
        return;
    }
    api('/api/password', {
        method: 'PUT', body: JSON.stringify({ password: newPassword }),
    }).then(res => {
        log(res.status === 'success' ? `✅ ${res.message}` : `❌ ${res.message}`);
        if (res.status === 'success') {
            document.getElementById('admin-password').value = '';
        }
    });
}

// Init
document.addEventListener('DOMContentLoaded', function() {
    loadSettings();

    // Apply gradient CSS variables to color preview elements
    document.querySelectorAll('.color-preview.gradient-bg')
        .forEach(function(el) {
        const gradient = el.dataset.gradient;
        if (gradient) {
            el.style.setProperty('--item-gradient', gradient);
        }
    });
});
