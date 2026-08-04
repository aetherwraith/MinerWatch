// Zero-Dependency Native Web Components Frontend for MinerWatch Deno

/** MinerCard Custom Web Component */
class MinerCard extends HTMLElement {
  connectedCallback() {
    this.render();
  }

  static get observedAttributes() {
    return ['ip', 'hostname', 'family', 'hashrate', 'power', 'efficiency', 'chiptemp', 'vrtemp', 'fan', 'online', 'asiccount'];
  }

  attributeChangedCallback() {
    this.render();
  }

  render() {
    const ip = this.getAttribute('ip') || '--';
    const hostname = this.getAttribute('hostname') || ip;
    const family = this.getAttribute('family') || 'miner';
    const hr = this.getAttribute('hashrate');
    const power = this.getAttribute('power');
    const eff = this.getAttribute('efficiency');
    const chipTemp = this.getAttribute('chiptemp');
    const vrTemp = this.getAttribute('vrtemp');
    const fan = this.getAttribute('fan');
    const online = this.getAttribute('online') === 'true';
    const asicCount = parseInt(this.getAttribute('asiccount') || '0');

    let displayFamily = family.toUpperCase();
    if (family === 'nerdoctaxe' || family === 'qaxe' || hostname.toLowerCase().includes('qaxe')) {
      if (asicCount === 4 || hostname.toLowerCase().includes('qaxe')) {
        displayFamily = 'NERDQAXE';
      } else if (asicCount === 8 || hostname.toLowerCase().includes('octaxe')) {
        displayFamily = 'NERDOCTAXE';
      }
    }

    const tempVal = chipTemp ? parseFloat(chipTemp) : 0;
    const tempColor = tempVal > 80 ? '#ef4444' : tempVal > 70 ? '#f59e0b' : '#f3f4f6';

    this.innerHTML = `
      <div class="miner-card-element">
        <div class="card-header">
          <div>
            <div class="miner-name">${hostname}</div>
            <div class="miner-meta">${ip} · ${displayFamily}</div>
          </div>
          <span class="status-indicator ${online ? '' : 'offline'}"></span>
        </div>

        <div class="stat-group">
          <div class="stat-line">
            <span class="stat-key">Hashrate</span>
            <span class="stat-val" style="color: #38bdf8;">${hr ? hr + ' TH/s' : '--'}</span>
          </div>

          <div class="stat-line">
            <span class="stat-key">Power</span>
            <span class="stat-val">${power ? power + ' W' : '--'}</span>
          </div>

          <div class="stat-line">
            <span class="stat-key">Efficiency</span>
            <span class="stat-val" style="color: #10b981;">${eff ? eff + ' J/TH' : '--'}</span>
          </div>

          <div class="stat-line">
            <span class="stat-key">Chip / VR Temp</span>
            <span class="stat-val" style="color: ${tempColor};">${chipTemp ? chipTemp + '°C' : '--'} / ${vrTemp ? vrTemp + '°C' : '--'}</span>
          </div>

          <div class="stat-line">
            <span class="stat-key">Fan Speed</span>
            <span class="stat-val">${fan ? fan + '%' : '--'}</span>
          </div>
        </div>

        <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
          <button class="btn-action btn-primary" style="flex: 1;" onclick="openMinerDetail('${ip}')">Manage & Tune Miner</button>
        </div>
      </div>
    `;
  }
}
customElements.define('miner-card', MinerCard);

/** Benchmark Visualizer Web Component with Native SVG Chart */
class BenchmarkVisualizer extends HTMLElement {
  set data({ samples, running, currentStep, totalSteps, isMicroPhase, microCurrent, microTotal, activePoint }) {
    this._samples = samples || [];
    this._running = running;
    this._step = currentStep || 0;
    this._total = totalSteps || 0;
    this._isMicro = isMicroPhase;
    this._microCurrent = microCurrent || 0;
    this._microTotal = microTotal || 0;
    this._activePoint = activePoint;
    this.render();
  }

  render() {
    const samples = this._samples || [];
    const points = samples
      .map((s, idx) => ({ s, origStep: idx + 1 }))
      .filter(({ s }) => (s.stable === true || s.stable === 1) && !s.abort_reason && s.efficiency_j_th != null && s.efficiency_j_th > 0);

    let svgPoly = '';
    if (points.length > 1) {
      const width = 600;
      const height = 140;
      const maxEff = Math.max(...points.map(p => p.s.efficiency_j_th)) || 30;
      const minEff = Math.min(...points.map(p => p.s.efficiency_j_th)) || 10;
      const effSpan = Math.max(1, maxEff - minEff);

      const polyPoints = points.map((p, idx) => {
        const x = (idx / (points.length - 1)) * width;
        const y = height - ((p.s.efficiency_j_th - minEff) / effSpan) * (height - 20) - 10;
        return `${x},${y}`;
      }).join(' ');

      const circles = points.map((p, idx) => {
        const x = (idx / (points.length - 1)) * width;
        const y = height - ((p.s.efficiency_j_th - minEff) / effSpan) * (height - 20) - 10;
        return `<circle cx="${x}" cy="${y}" r="4" fill="#38bdf8" stroke="#0284c7" stroke-width="1.5"><title>Step ${p.origStep}: ${p.s.freq_mhz}MHz / ${p.s.voltage_mv}mV - ${p.s.efficiency_j_th.toFixed(1)} J/TH</title></circle>`;
      }).join('');

      svgPoly = `
        <polyline fill="none" stroke="#c084fc" stroke-width="3" points="${polyPoints}" />
        ${circles}
      `;
    }

    const activeStepText = this._isMicro ? `Micro Step ${this._microCurrent} of ${this._microTotal}` : `Step ${this._step} of ${this._total}`;

    this.innerHTML = `
      <div style="background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); border-radius: 0.75rem; padding: 1.25rem;">
        <div style="display:flex; justify-between; align-items: center; margin-bottom: 1rem;">
          <div>
            <h4 style="font-size: 1rem; color: var(--color-purple); font-weight: 700;">Efficiency Sweep Matrix Graph (J/TH)</h4>
            <span style="font-size: 0.75rem; color: var(--text-muted);">Strictly plotting stable operating points</span>
          </div>
          <span style="font-size: 0.8rem; color: var(--text-muted); font-family: var(--font-mono); background: rgba(255,255,255,0.05); padding: 0.25rem 0.6rem; border-radius: 0.4rem;">
            ${this._running ? activeStepText : 'Completed'}
          </span>
        </div>

        ${points.length > 0 ? `
          <svg width="100%" height="140" viewBox="0 0 600 140" preserveAspectRatio="none">
            <line x1="0" y1="130" x2="600" y2="130" stroke="rgba(255,255,255,0.1)" stroke-dasharray="4" />
            <line x1="0" y1="70" x2="600" y2="70" stroke="rgba(255,255,255,0.1)" stroke-dasharray="4" />
            ${svgPoly}
          </svg>
        ` : `
          <div style="text-align: center; padding: 2.5rem 1rem; color: var(--text-muted); background: rgba(0,0,0,0.2); border-radius: 0.5rem; border: 1px dashed var(--border-color); font-size: 0.85rem;">
            ${this._running ? `
              <div style="font-weight: 700; color: var(--color-primary); margin-bottom: 0.25rem;">Sampling ${activeStepText} in Progress...</div>
              <div>Telemetry graph will render as soon as a stable operating point settles.</div>
            ` : `
              <div style="font-weight: 700; color: var(--color-warning); margin-bottom: 0.25rem;">No Stable Operating Points Plotted</div>
              <div>All sampled combinations were unstable or exceeded safety error limits.</div>
            `}
          </div>
        `}

        <div style="margin-top: 1.25rem; max-height: 220px; overflow-y: auto;">
          <table style="width: 100%; border-collapse: collapse; font-size: 0.8rem; font-family: var(--font-mono);">
            <thead>
              <tr style="text-align: left; color: var(--text-muted); border-bottom: 1px solid var(--border-color);">
                <th style="padding: 0.5rem;">Step</th>
                <th style="padding: 0.5rem;">Freq/Volt</th>
                <th style="padding: 0.5rem;">Hashrate</th>
                <th style="padding: 0.5rem;">Power</th>
                <th style="padding: 0.5rem;">Efficiency</th>
                <th style="padding: 0.5rem;">Status</th>
              </tr>
            </thead>
            <tbody>
              ${samples.map((s, idx) => `
                <tr style="border-bottom: 1px solid rgba(255,255,255,0.03); background: ${s.stable ? 'rgba(16, 185, 129, 0.05)' : 'rgba(239, 68, 68, 0.05)'};">
                  <td style="padding: 0.5rem;">Step #${idx + 1}</td>
                  <td style="padding: 0.5rem;">${s.freq_mhz}MHz / ${s.voltage_mv}mV</td>
                  <td style="padding: 0.5rem; color: #38bdf8;">${s.hashrate_ths ? s.hashrate_ths.toFixed(2) + ' TH/s' : '--'}</td>
                  <td style="padding: 0.5rem;">${s.power_w ? s.power_w.toFixed(1) + ' W' : '--'}</td>
                  <td style="padding: 0.5rem; color: #10b981;">${s.efficiency_j_th ? s.efficiency_j_th.toFixed(1) + ' J/TH' : '--'}</td>
                  <td style="padding: 0.5rem;">
                    <span style="padding: 0.15rem 0.4rem; border-radius: 4px; background: ${s.stable ? 'rgba(16,185,129,0.2)' : 'rgba(239,68,68,0.2)'}; color: ${s.stable ? '#10b981' : '#ef4444'}; font-size: 0.7rem;">
                      ${s.stable ? 'Stable' : 'Unstable'}
                    </span>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }
}
customElements.define('benchmark-visualizer', BenchmarkVisualizer);

// Global SSE & State Engine
let currentMiners = [];
let currentFilterQuery = '';

const sse = new EventSource('/api/stream');
sse.onmessage = (evt) => {
  const data = JSON.parse(evt.data);
  currentMiners = data.miners || [];
  updateFleetSummary(currentMiners);
  renderMinersGrid(currentMiners);
};

function updateFleetSummary(miners) {
  const activeCount = miners.filter(m => m.online).length;
  const totalHash = miners.reduce((acc, m) => acc + (m.hashrate_ths || 0), 0);
  const totalPower = miners.reduce((acc, m) => acc + (m.power_w || 0), 0);
  const fleetEff = totalHash > 0 ? (totalPower / totalHash) : 0;

  document.getElementById('summary-miners').textContent = `${activeCount} / ${miners.length}`;
  document.getElementById('summary-hashrate').textContent = `${totalHash.toFixed(2)} TH/s`;
  document.getElementById('summary-power').textContent = `${totalPower.toFixed(1)} W`;
  document.getElementById('summary-eff').textContent = `${fleetEff.toFixed(1)} J/TH`;
}

window.filterMinersGrid = function() {
  const query = document.getElementById('search-filter').value.toLowerCase().trim();
  currentFilterQuery = query;
  renderMinersGrid(currentMiners);
};

function renderMinersGrid(miners) {
  const container = document.getElementById('cards-grid');
  const label = document.getElementById('miner-count-label');

  let filtered = miners;
  if (currentFilterQuery) {
    filtered = miners.filter(m => {
      const item = m.miner ? { ...m.miner, ...(m.live_sample || {}) } : m;
      const ip = (item.ip || item.host || '').toLowerCase();
      const name = (item.hostname || item.name || '').toLowerCase();
      return ip.includes(currentFilterQuery) || name.includes(currentFilterQuery);
    });
  }

  if (label) {
    label.textContent = `Showing ${filtered.length} of ${miners.length} miner(s)`;
  }

  if (!filtered || filtered.length === 0) {
    container.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 3rem; grid-column: 1/-1;">No matching miners active. Run subnet discovery to auto-detect miners.</div>';
    return;
  }

  container.innerHTML = filtered.map(m => {
    const item = m.miner ? { ...m.miner, ...(m.live_sample || {}) } : m;
    const ip = item.ip || item.host || '';
    const hostname = item.hostname || item.name || ip;
    const family = item.family || 'miner';
    const fanVal = item.fan_pct ?? item.fan_speed ?? item.fan ?? item.fan_speed_pct ?? item.live_sample?.fan_pct ?? item.last_metric?.fan_pct;
    return `
      <miner-card
        ip="${ip}"
        hostname="${hostname}"
        family="${family}"
        asiccount="${item.asic_count || ''}"
        hashrate="${item.hashrate_ths != null ? item.hashrate_ths : ''}"
        power="${item.power_w != null ? item.power_w : ''}"
        efficiency="${item.efficiency_j_th != null ? item.efficiency_j_th : ''}"
        chiptemp="${item.temp_chip_c != null ? item.temp_chip_c : (item.chip_temp_c != null ? item.chip_temp_c : '')}"
        vrtemp="${item.temp_vr_c != null ? item.temp_vr_c : (item.vr_temp_c != null ? item.vr_temp_c : '')}"
        fan="${fanVal != null ? fanVal : ''}"
        online="${item.online !== false}"
      ></miner-card>
    `;
  }).join('');
}

// Modal Detail View Handler
window.openMinerDetail = async function(ip) {
  const res = await fetch(`/api/miners`);
  const data = await res.json();
  const minerObj = data.miners.find(m => (m.miner ? m.miner.ip === ip : m.ip === ip));
  if (!minerObj) return;

  const miner = minerObj.miner || minerObj;
  
  // Fetch detailed live endpoint & Guardian status for complete field population
  const [detailData, guardianData] = await Promise.all([
    fetch(`/api/miners/${miner.id}`).then(r => r.ok ? r.json() : null).catch(() => null),
    fetch(`/api/miners/${miner.id}/guardian/status`).then(r => r.ok ? r.json() : null).catch(() => null)
  ]);

  const live = detailData?.miner || miner;
  const sample = detailData?.live_sample || minerObj.live_sample || {};
  const gStatus = guardianData || {};

  const curFreq = sample.freq_mhz || sample.frequency_mhz || live.freq_mhz || 500;
  const curVolt = sample.voltage_mv || live.voltage_mv || 1200;
  const pool1Url = live.pool1_url || live.stratum_url || (live.pools?.[0]?.url) || '';
  const pool1User = live.pool1_user || live.stratum_user || (live.pools?.[0]?.user) || '';
  const pool2Url = live.pool2_url || (live.pools?.[1]?.url) || '';
  const pool2User = live.pool2_user || (live.pools?.[1]?.user) || '';

  const modal = document.createElement('div');
  modal.className = 'modal-overlay';
  modal.id = 'active-modal';

  modal.innerHTML = `
    <div class="modal-content">
      <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-color); padding-bottom: 1rem;">
        <div>
          <h2 style="font-size: 1.3rem; font-weight: 800;">${live.hostname || live.name || live.ip}</h2>
          <span style="font-size: 0.8rem; color: var(--text-muted); font-family: var(--font-mono);">${live.ip} (${live.family})</span>
        </div>
        <button class="btn-action" onclick="closeModal()">Close</button>
      </div>

      <div class="tabs-header">
        <button class="tab-btn active" onclick="switchModalTab('controls')">Tuning & Controls</button>
        <button class="tab-btn" onclick="switchModalTab('autofan')">Autofan</button>
        <button class="tab-btn" onclick="switchModalTab('guardian')">Guardian Governor</button>
        <button class="tab-btn" onclick="switchModalTab('pools')">Stratum Pools</button>
        <button class="tab-btn" onclick="switchModalTab('benchmark')">Automated Benchmark</button>
      </div>

      <!-- Tab 1: Tuning & Controls -->
      <div id="tab-controls" style="display: flex; flex-direction: column; gap: 1rem;">
        <div class="form-grid">
          <div class="form-group">
            <label class="form-label">Frequency (MHz)</label>
            <input type="number" id="input-freq" value="${curFreq}" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label">Core Voltage (mV)</label>
            <input type="number" id="input-volt" value="${curVolt}" class="form-input">
          </div>
          <div class="form-group" style="justify-content: flex-end;">
            <button class="btn-action btn-primary" onclick="setFreqVolt(${live.id})">Apply Freq & Voltage</button>
          </div>
        </div>

        <div style="display: flex; gap: 1rem; border-top: 1px solid var(--border-color); padding-top: 1rem;">
          <input type="text" id="input-name" placeholder="Custom Display Name" value="${live.name || ''}" class="form-input" style="flex: 1;">
          <button class="btn-action" onclick="saveMinerName(${live.id})">Save Name</button>
          <button class="btn-action btn-danger" onclick="restartMiner(${live.id})">Restart Miner Hardware</button>
        </div>
      </div>

      <!-- Tab 2: Autofan -->
      <div id="tab-autofan" style="display: none; flex-direction: column; gap: 1rem;">
        <div class="form-grid">
          <div class="form-group">
            <label class="form-label">Fan Mode</label>
            <select id="select-fan-mode" class="form-select">
              <option value="firmware" ${live.fan_mode === 'firmware' ? 'selected' : ''}>Firmware Auto</option>
              <option value="manual" ${live.fan_mode === 'manual' ? 'selected' : ''}>Manual Fixed Speed (%)</option>
              <option value="minerwatch" ${live.fan_mode === 'minerwatch' ? 'selected' : ''}>MinerWatch Auto-Fan</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Manual Speed (%)</label>
            <input type="number" id="input-fan-speed" value="${live.fan_speed_pct || live.pin_fan_pct || 95}" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label">Target Temp (°C)</label>
            <input type="number" id="input-auto-target" value="${live.auto_target_c || 65}" class="form-input">
          </div>
        </div>
        <button class="btn-action btn-primary" style="align-self: flex-start;" onclick="saveFanSettings(${live.id})">Save Fan Settings</button>
      </div>

      <!-- Tab 3: Guardian Governor -->
      <div id="tab-guardian" style="display: none; flex-direction: column; gap: 1rem;">
        <div class="form-grid">
          <div class="form-group">
            <label class="form-label">Guardian Opt-In</label>
            <select id="select-guardian-enabled" class="form-select">
              <option value="1" ${gStatus.miner_enabled || live.guardian_enabled ? 'selected' : ''}>Enabled (Active Thermal Protection)</option>
              <option value="0" ${!gStatus.miner_enabled && !live.guardian_enabled ? 'selected' : ''}>Disabled</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Max Frequency Ceiling (MHz)</label>
            <input type="number" id="input-g-max-freq" value="${gStatus.max_freq_mhz || live.guardian_max_freq_mhz || curFreq}" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label">Frequency Floor (MHz)</label>
            <input type="number" id="input-g-freq-floor" value="${gStatus.freq_floor_mhz || live.guardian_freq_floor_mhz || 400}" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label">Voltage Ceiling (mV)</label>
            <input type="number" id="input-g-max-volt" value="${gStatus.max_voltage_mv || live.guardian_max_voltage_mv || 1300}" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label">Voltage Floor (mV)</label>
            <input type="number" id="input-g-volt-floor" value="${gStatus.voltage_floor_mv || live.guardian_voltage_floor_mv || 1150}" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label">Max Chip Temp Cap (°C)</label>
            <input type="number" id="input-g-max-temp" value="${gStatus.max_chip_temp_c || live.guardian_max_chip_temp_c || 68}" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label">Max VR Temp Cap (°C)</label>
            <input type="number" id="input-g-max-vr" value="${gStatus.max_vr_temp_c || live.guardian_max_vr_temp_c || 82}" class="form-input">
          </div>
        </div>
        <button class="btn-action btn-primary" style="align-self: flex-start;" onclick="saveGuardianSettings(${live.id})">Save Guardian Settings</button>
      </div>

      <!-- Tab 4: Stratum Pools -->
      <div id="tab-pools" style="display: none; flex-direction: column; gap: 1rem;">
        <div class="form-group">
          <label class="form-label">Primary Stratum Pool URL</label>
          <input type="text" id="input-pool1-url" value="${pool1Url}" placeholder="stratum+tcp://solo.ckpool.org:3333" class="form-input">
        </div>
        <div class="form-group">
          <label class="form-label">Primary Worker / BTC Address</label>
          <input type="text" id="input-pool1-user" value="${pool1User}" placeholder="bc1q...worker1" class="form-input">
        </div>
        <div class="form-group">
          <label class="form-label">Secondary Stratum Pool URL</label>
          <input type="text" id="input-pool2-url" value="${pool2Url}" placeholder="stratum+tcp://btc.viabtc.io:3333" class="form-input">
        </div>
        <div class="form-group">
          <label class="form-label">Secondary Worker / BTC Address</label>
          <input type="text" id="input-pool2-user" value="${pool2User}" placeholder="bc1q...worker2" class="form-input">
        </div>
        <button class="btn-action btn-primary" style="align-self: flex-start;" onclick="savePoolSettings(${live.id})">Save Stratum Pool Config</button>
      </div>

      <!-- Tab 5: Automated Benchmark -->
      <div id="tab-benchmark" style="display: none; flex-direction: column; gap: 1.25rem;">
        <div class="form-grid" style="background: rgba(0,0,0,0.25); padding: 1rem; border-radius: 0.75rem; border: 1px solid var(--border-color);">
          <div class="form-group">
            <label class="form-label">Min Freq (MHz)</label>
            <input type="number" id="bench-min-freq" value="500" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label">Max Freq (MHz)</label>
            <input type="number" id="bench-max-freq" value="600" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label">Freq Step (MHz)</label>
            <input type="number" id="bench-freq-step" value="25" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label">Min Voltage (mV)</label>
            <input type="number" id="bench-min-volt" value="1200" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label">Max Voltage (mV)</label>
            <input type="number" id="bench-max-volt" value="1300" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label">Volt Step (mV)</label>
            <input type="number" id="bench-volt-step" value="25" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label">Dwell Time (sec)</label>
            <input type="number" id="bench-dwell" value="30" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label">Max Error Rate %</label>
            <input type="number" step="0.1" id="bench-max-err" value="1.1" class="form-input">
          </div>
        </div>

        <div style="display: flex; justify-content: space-between; align-items: center;">
          <button class="btn-action btn-primary" onclick="startBenchConfigured(${live.id})">🚀 Run Efficiency Benchmark</button>
          <button class="btn-action btn-danger" onclick="stopBench(${live.id})">Stop Benchmark</button>
        </div>

        <benchmark-visualizer id="bench-vis"></benchmark-visualizer>
      </div>
    </div>
  `;

  document.body.appendChild(modal);
  pollBenchStatus(live.id);
};

window.closeModal = function() {
  const m = document.getElementById('active-modal');
  if (m) m.remove();
};

window.switchModalTab = function(tab) {
  const tabs = ['controls', 'autofan', 'guardian', 'pools', 'benchmark'];
  tabs.forEach(t => {
    const el = document.getElementById(`tab-${t}`);
    if (el) el.style.display = t === tab ? 'flex' : 'none';
  });
  const btns = document.querySelectorAll('.tab-btn');
  btns.forEach(b => {
    b.classList.toggle('active', b.getAttribute('onclick')?.includes(`'${tab}'`));
  });
};

window.setFreqVolt = async function(minerId) {
  const freq = parseInt(document.getElementById('input-freq').value);
  const volt = parseInt(document.getElementById('input-volt').value);
  await fetch(`/api/miners/${minerId}/control/frequency`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ freq_mhz: freq, voltage_mv: volt }),
  });
  alert('Frequency/Voltage updated!');
};

window.saveMinerName = async function(minerId) {
  const name = document.getElementById('input-name').value;
  await fetch(`/api/miners/${minerId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  alert('Miner display name saved!');
};

window.saveFanSettings = async function(minerId) {
  const mode = document.getElementById('select-fan-mode').value;
  const speed = parseInt(document.getElementById('input-fan-speed').value);
  const target = parseInt(document.getElementById('input-auto-target').value);
  await fetch(`/api/miners/${minerId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fan_mode: mode, fan_speed_pct: speed, auto_target_c: target }),
  });
  alert('Fan settings updated!');
};

window.saveGuardianSettings = async function(minerId) {
  const enabled = parseInt(document.getElementById('select-guardian-enabled').value) === 1;
  const maxFreq = parseInt(document.getElementById('input-g-max-freq').value);
  const freqFloor = parseInt(document.getElementById('input-g-freq-floor').value);
  const maxVolt = parseInt(document.getElementById('input-g-max-volt').value);
  const voltFloor = parseInt(document.getElementById('input-g-volt-floor').value);
  const maxChip = parseFloat(document.getElementById('input-g-max-temp').value);
  const maxVr = parseFloat(document.getElementById('input-g-max-vr').value);

  await fetch(`/api/miners/${minerId}/guardian/config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      enabled,
      max_freq_mhz: isNaN(maxFreq) ? null : maxFreq,
      freq_floor_mhz: isNaN(freqFloor) ? null : freqFloor,
      max_voltage_mv: isNaN(maxVolt) ? null : maxVolt,
      voltage_floor_mv: isNaN(voltFloor) ? null : voltFloor,
      max_chip_temp_c: isNaN(maxChip) ? null : maxChip,
      max_vr_temp_c: isNaN(maxVr) ? null : maxVr,
    }),
  });
  alert('Guardian settings updated!');
};

window.savePoolSettings = async function(minerId) {
  const url = document.getElementById('input-pool1-url').value;
  const user = document.getElementById('input-pool1-user').value;
  await fetch(`/api/miners/${minerId}/pools`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pool1_url: url, pool1_user: user }),
  });
  alert('Stratum pool settings saved!');
};

window.restartMiner = async function(minerId) {
  if (confirm('Are you sure you want to reboot this miner?')) {
    await fetch(`/api/miners/${minerId}/control/restart`, { method: 'POST' });
    alert('Miner rebooting...');
  }
};

window.startBenchConfigured = async function(minerId) {
  const minFreq = parseInt(document.getElementById('bench-min-freq').value);
  const maxFreq = parseInt(document.getElementById('bench-max-freq').value);
  const stepFreq = parseInt(document.getElementById('bench-freq-step').value);
  const minVolt = parseInt(document.getElementById('bench-min-volt').value);
  const maxVolt = parseInt(document.getElementById('bench-max-volt').value);
  const stepVolt = parseInt(document.getElementById('bench-volt-step').value);
  const dwell = parseInt(document.getElementById('bench-dwell').value);
  const maxErr = parseFloat(document.getElementById('bench-max-err').value);

  await fetch(`/api/miners/${minerId}/benchmark/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      min_freq_mhz: minFreq,
      max_freq_mhz: maxFreq,
      freq_step_mhz: stepFreq,
      min_voltage_mv: minVolt,
      max_voltage_mv: maxVolt,
      voltage_step_mv: stepVolt,
      dwell_time_s: dwell,
      max_error_rate_pct: maxErr,
      enable_microtuning: true,
    }),
  });
  pollBenchStatus(minerId);
};

window.stopBench = async function(minerId) {
  await fetch(`/api/miners/${minerId}/benchmark/cancel`, { method: 'POST' });
  alert('Benchmark canceled.');
};

async function pollBenchStatus(minerId) {
  const res = await fetch(`/api/miners/${minerId}/benchmark/status`);
  const data = await res.json();
  const vis = document.getElementById('bench-vis');
  if (vis && data.latest_run) {
    vis.data = {
      samples: data.latest_run.samples,
      running: data.running,
      currentStep: data.latest_run.current_step,
      totalSteps: data.latest_run.total_steps,
      isMicroPhase: data.latest_run.sweep_phase === 'microtuning',
      microCurrent: data.latest_run.micro_current_step,
      microTotal: data.latest_run.micro_total_steps,
      activePoint: data.live_metrics,
    };
  }
}
