// Zero-Dependency Native Web Components Frontend for MinerWatch Deno

/** MinerCard Custom Web Component */
class MinerCard extends HTMLElement {
  connectedCallback() {
    this.render();
  }

  static get observedAttributes() {
    return ['ip', 'hostname', 'family', 'hashrate', 'power', 'efficiency', 'chiptemp', 'vrtemp', 'fan', 'online'];
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
    const tempColor = tempVal > 70 ? '#f59e0b' : tempVal > 80 ? '#ef4444' : '#f3f4f6';

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
          <button class="btn-action btn-primary" style="flex: 1;" onclick="openMinerDetail('${ip}')">Open Tuning & Benchmark</button>
        </div>
      </div>
    `;
  }
}
customElements.define('miner-card', MinerCard);

/** Benchmark Visualizer Web Component with Native SVG Chart */
class BenchmarkVisualizer extends HTMLElement {
  set data({ samples, running, currentStep, totalSteps }) {
    this._samples = samples || [];
    this._running = running;
    this._step = currentStep;
    this._total = totalSteps;
    this.render();
  }

  render() {
    const samples = this._samples || [];
    const points = samples.filter(s => s.stable && s.efficiency_j_th != null);

    let svgPoly = '';
    if (points.length > 1) {
      const width = 600;
      const height = 150;
      const maxEff = Math.max(...points.map(p => p.efficiency_j_th)) || 30;
      const minEff = Math.min(...points.map(p => p.efficiency_j_th)) || 10;
      const effSpan = Math.max(1, maxEff - minEff);

      const polyPoints = points.map((p, idx) => {
        const x = (idx / (points.length - 1)) * width;
        const y = height - ((p.efficiency_j_th - minEff) / effSpan) * (height - 20) - 10;
        return `${x},${y}`;
      }).join(' ');

      svgPoly = `<polyline fill="none" stroke="#c084fc" stroke-width="3" points="${polyPoints}" />`;
    }

    this.innerHTML = `
      <div style="background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); border-radius: 0.75rem; padding: 1.25rem;">
        <div style="display:flex; justify-between; align-items: center; margin-bottom: 1rem;">
          <h4 style="font-size: 1rem; color: var(--color-purple); font-weight: 700;">Efficiency Sweep Graph (J/TH)</h4>
          <span style="font-size: 0.8rem; color: var(--text-muted); font-family: var(--font-mono);">
            ${this._running ? `Running Step ${this._step} / ${this._total}` : 'Completed'}
          </span>
        </div>

        <svg width="100%" height="150" viewBox="0 0 600 150" preserveAspectRatio="none">
          <line x1="0" y1="140" x2="600" y2="140" stroke="rgba(255,255,255,0.1)" stroke-dasharray="4" />
          <line x1="0" y1="75" x2="600" y2="75" stroke="rgba(255,255,255,0.1)" stroke-dasharray="4" />
          ${svgPoly}
        </svg>

        <div style="margin-top: 1.25rem; max-height: 200px; overflow-y: auto;">
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
                  <td style="padding: 0.5rem;">#${idx + 1}</td>
                  <td style="padding: 0.5rem;">${s.freq_mhz}MHz / ${s.voltage_mv}mV</td>
                  <td style="padding: 0.5rem; color: #38bdf8;">${s.hashrate_ths ? s.hashrate_ths.toFixed(2) + ' TH/s' : '--'}</td>
                  <td style="padding: 0.5rem;">${s.power_w ? s.power_w + ' W' : '--'}</td>
                  <td style="padding: 0.5rem; color: #10b981;">${s.efficiency_j_th ? s.efficiency_j_th.toFixed(2) + ' J/TH' : '--'}</td>
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

function renderMinersGrid(miners) {
  const container = document.getElementById('cards-grid');
  if (!miners || miners.length === 0) {
    container.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 3rem; grid-column: 1/-1;">No miners active. Run subnet discovery to auto-detect miners.</div>';
    return;
  }

  container.innerHTML = miners.map(m => {
    const item = m.miner ? { ...m.miner, ...(m.live_sample || {}) } : m;
    const ip = item.ip || item.host || '';
    const hostname = item.hostname || item.name || ip;
    const family = item.family || 'miner';
    return `
      <miner-card
        ip="${ip}"
        hostname="${hostname}"
        family="${family}"
        asiccount="${item.asic_count || ''}"
        hashrate="${item.hashrate_ths != null ? item.hashrate_ths : ''}"
        power="${item.power_w != null ? item.power_w : ''}"
        efficiency="${item.efficiency_j_th != null ? item.efficiency_j_th : ''}"
        chiptemp="${item.temp_chip_c != null ? item.temp_chip_c : ''}"
        vrtemp="${item.temp_vr_c != null ? item.temp_vr_c : ''}"
        fan="${item.fan_pct != null ? item.fan_pct : ''}"
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
  const modal = document.createElement('div');
  modal.className = 'modal-overlay';
  modal.id = 'active-modal';

  modal.innerHTML = `
    <div class="modal-content">
      <div style="display: flex; justify-between; align-items: center; border-bottom: 1px solid var(--border-color); padding-bottom: 1rem;">
        <div>
          <h2 style="font-size: 1.3rem; font-weight: 800;">${miner.hostname || miner.ip}</h2>
          <span style="font-size: 0.8rem; color: var(--text-muted); font-family: var(--font-mono);">${miner.ip} (${miner.family})</span>
        </div>
        <button class="btn-action" onclick="closeModal()">Close</button>
      </div>

      <div class="tabs-header">
        <button class="tab-btn active" onclick="switchModalTab('controls')">Tuning & Controls</button>
        <button class="tab-btn" onclick="switchModalTab('benchmark')">Automated Benchmark</button>
      </div>

      <div id="tab-controls" style="display: flex; flex-direction: column; gap: 1rem;">
        <div style="display: flex; gap: 1rem;">
          <input type="number" id="input-freq" placeholder="Frequency (MHz)" value="500" style="background: rgba(0,0,0,0.4); border: 1px solid var(--border-color); color: white; padding: 0.5rem; border-radius: 0.5rem; flex: 1;">
          <input type="number" id="input-volt" placeholder="Voltage (mV)" value="1200" style="background: rgba(0,0,0,0.4); border: 1px solid var(--border-color); color: white; padding: 0.5rem; border-radius: 0.5rem; flex: 1;">
          <button class="btn-action btn-primary" onclick="setFreqVolt(${miner.id})">Apply Frequency/Voltage</button>
        </div>

        <div style="display: flex; gap: 1rem;">
          <input type="number" id="input-fan" placeholder="Fan Speed (%)" value="95" style="background: rgba(0,0,0,0.4); border: 1px solid var(--border-color); color: white; padding: 0.5rem; border-radius: 0.5rem; flex: 1;">
          <button class="btn-action" onclick="setFan(${miner.id})">Set Fixed Fan</button>
          <button class="btn-action" onclick="restartMiner(${miner.id})">Restart Miner</button>
        </div>
      </div>

      <div id="tab-benchmark" style="display: none; flex-direction: column; gap: 1rem;">
        <div style="display: flex; gap: 0.5rem;">
          <button class="btn-action btn-primary" style="flex: 1;" onclick="startBench(${miner.id})">🚀 Run Efficiency Benchmark</button>
        </div>
        <benchmark-visualizer id="bench-vis"></benchmark-visualizer>
      </div>
    </div>
  `;

  document.body.appendChild(modal);
  pollBenchStatus(miner.id);
};

window.closeModal = function() {
  const m = document.getElementById('active-modal');
  if (m) m.remove();
};

window.switchModalTab = function(tab) {
  document.getElementById('tab-controls').style.display = tab === 'controls' ? 'flex' : 'none';
  document.getElementById('tab-benchmark').style.display = tab === 'benchmark' ? 'flex' : 'none';
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

window.setFan = async function(minerId) {
  const fan = parseInt(document.getElementById('input-fan').value);
  await fetch(`/api/miners/${minerId}/control/fan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ speed_pct: fan }),
  });
  alert('Fan speed updated!');
};

window.restartMiner = async function(minerId) {
  await fetch(`/api/miners/${minerId}/control/restart`, { method: 'POST' });
  alert('Miner rebooting...');
};

window.startBench = async function(minerId) {
  await fetch(`/api/miners/${minerId}/benchmark/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      min_freq_mhz: 500,
      max_freq_mhz: 550,
      freq_step_mhz: 25,
      min_voltage_mv: 1200,
      max_voltage_mv: 1250,
      voltage_step_mv: 25,
      dwell_time_s: 5,
      max_error_rate_pct: 1.1,
      enable_microtuning: true,
    }),
  });
  pollBenchStatus(minerId);
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
    };
  }
}
