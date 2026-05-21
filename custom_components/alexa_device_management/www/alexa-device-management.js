/**
 * Alexa Device Management Panel
 *
 * Full device management UI analogous to Z-Wave JS UI / Zigbee2MQTT dashboard.
 * Communicates with backend exclusively via WebSocket API.
 */

const WS_PREFIX = "alexa_device_management";

class AlexaDeviceManagementPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._devices = [];
    this._connectionState = "unknown";
    this._selectedDevice = null;
    this._view = "list"; // "list" | "detail"
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialize();
    }
  }

  connectedCallback() {
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<div class="loading">Lade...</div>`;
    this._applyStyles();
  }

  async _initialize() {
    this._initialized = true;
    this._applyStyles();
    await this._subscribeEvents();
    await this._fetchConnectionState();
    await this._fetchDevices();
    this._render();
  }

  // ------------------------------------------------------------------
  // WebSocket communication (like zwave-js frontend)
  // ------------------------------------------------------------------

  _sendCommand(command, params = {}) {
    return this._hass.callWS({ type: `${WS_PREFIX}/${command}`, ...params });
  }

  async _fetchConnectionState() {
    try {
      const result = await this._sendCommand("connection_state");
      this._connectionState = result.state;
    } catch (e) {
      this._connectionState = "error";
    }
  }

  async _fetchDevices() {
    try {
      const result = await this._sendCommand("list_devices");
      this._devices = result.devices || [];
    } catch (e) {
      this._devices = [];
    }
    this._render();
  }

  async _deleteDevice(deviceId) {
    if (!confirm(`Gerät wirklich löschen?`)) return;
    await this._sendCommand("delete_device", { device_id: deviceId });
    this._selectedDevice = null;
    this._view = "list";
    await this._fetchDevices();
  }

  async _renameDevice(deviceId, newName) {
    await this._sendCommand("rename_device", { device_id: deviceId, name: newName });
    await this._fetchDevices();
    // Update detail view
    this._selectedDevice = this._devices.find((d) => d.id === deviceId) || null;
    this._render();
  }

  async _refreshDevices() {
    const result = await this._sendCommand("refresh_devices");
    this._devices = result.devices || [];
    this._render();
  }

  async _subscribeEvents() {
    try {
      this._hass.connection.subscribeMessage(
        (event) => {
          if (event.new_state) {
            this._connectionState = event.new_state;
            this._render();
          } else {
            // devices updated
            this._fetchDevices();
          }
        },
        { type: `${WS_PREFIX}/subscribe` }
      );
    } catch (_e) {
      // subscription not critical
    }
  }

  // ------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------

  _applyStyles() {
    if (!this.shadowRoot) return;
    let style = this.shadowRoot.querySelector("style");
    if (!style) {
      style = document.createElement("style");
      this.shadowRoot.prepend(style);
    }
    style.textContent = `
      :host {
        display: block;
        padding: 16px 24px;
        font-family: var(--paper-font-body1_-_font-family, "Roboto", sans-serif);
        color: var(--primary-text-color, #212121);
        background: var(--primary-background-color, #fafafa);
        min-height: 100vh;
        box-sizing: border-box;
      }

      .toolbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 16px;
        flex-wrap: wrap;
        gap: 8px;
      }
      .toolbar h1 {
        margin: 0;
        font-size: 24px;
        font-weight: 400;
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .toolbar-actions {
        display: flex;
        gap: 8px;
      }

      .status-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 500;
        text-transform: uppercase;
      }
      .status-connected { background: #c8e6c9; color: #2e7d32; }
      .status-connecting { background: #fff9c4; color: #f57f17; }
      .status-disconnected { background: #ffcdd2; color: #c62828; }
      .status-unknown { background: #e0e0e0; color: #616161; }

      button {
        background: var(--primary-color, #03a9f4);
        color: #fff;
        border: none;
        border-radius: 4px;
        padding: 8px 16px;
        cursor: pointer;
        font-size: 14px;
        transition: background 0.2s;
      }
      button:hover { background: var(--dark-primary-color, #0288d1); }
      button.secondary {
        background: transparent;
        color: var(--primary-color, #03a9f4);
        border: 1px solid var(--primary-color, #03a9f4);
      }
      button.secondary:hover {
        background: var(--primary-color, #03a9f4);
        color: #fff;
      }
      button.danger { background: #e53935; }
      button.danger:hover { background: #b71c1c; }

      .device-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: 16px;
      }

      .device-card {
        background: var(--card-background-color, #fff);
        border-radius: 8px;
        padding: 16px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.1);
        cursor: pointer;
        transition: box-shadow 0.2s, transform 0.1s;
        position: relative;
      }
      .device-card:hover {
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        transform: translateY(-1px);
      }
      .device-card .device-name {
        font-size: 16px;
        font-weight: 500;
        margin-bottom: 4px;
      }
      .device-card .device-type {
        font-size: 13px;
        color: var(--secondary-text-color, #727272);
        margin-bottom: 8px;
      }
      .device-card .device-room {
        font-size: 12px;
        color: var(--secondary-text-color, #727272);
      }
      .device-card .online-indicator {
        position: absolute;
        top: 16px;
        right: 16px;
        width: 10px;
        height: 10px;
        border-radius: 50%;
      }
      .online-indicator.online { background: #4caf50; }
      .online-indicator.offline { background: #9e9e9e; }

      .detail-view {
        max-width: 700px;
      }
      .detail-header {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 24px;
      }
      .detail-header h2 {
        margin: 0;
        font-weight: 400;
      }
      .detail-section {
        background: var(--card-background-color, #fff);
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.1);
        margin-bottom: 16px;
      }
      .detail-section h3 {
        margin: 0 0 12px 0;
        font-size: 14px;
        font-weight: 500;
        text-transform: uppercase;
        color: var(--secondary-text-color, #727272);
      }
      .detail-row {
        display: flex;
        justify-content: space-between;
        padding: 8px 0;
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
      }
      .detail-row:last-child { border-bottom: none; }
      .detail-row .label { color: var(--secondary-text-color, #727272); }
      .detail-row .value { font-weight: 500; }

      .capabilities {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-top: 8px;
      }
      .capability-chip {
        background: var(--primary-color, #03a9f4);
        color: #fff;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 500;
      }

      .detail-actions {
        display: flex;
        gap: 8px;
        margin-top: 16px;
      }

      .empty-state {
        text-align: center;
        padding: 60px 20px;
        color: var(--secondary-text-color, #727272);
      }
      .empty-state svg {
        width: 64px;
        height: 64px;
        margin-bottom: 16px;
        opacity: 0.4;
      }

      .loading {
        text-align: center;
        padding: 60px;
        color: var(--secondary-text-color, #727272);
      }

      @media (max-width: 600px) {
        :host { padding: 12px; }
        .device-grid { grid-template-columns: 1fr; }
      }
    `;
  }

  _render() {
    if (!this.shadowRoot) return;

    // Keep existing <style> element
    const style = this.shadowRoot.querySelector("style");
    const container = this.shadowRoot.querySelector(".container") || document.createElement("div");
    container.className = "container";

    if (this._view === "detail" && this._selectedDevice) {
      container.innerHTML = this._renderDetail();
    } else {
      container.innerHTML = this._renderList();
    }

    // Rebuild shadow DOM (keep style)
    this.shadowRoot.innerHTML = "";
    if (style) this.shadowRoot.appendChild(style);
    else this._applyStyles();
    this.shadowRoot.appendChild(container);

    this._attachEventListeners();
  }

  _renderList() {
    const stateClass = `status-${this._connectionState}`;
    const stateLabel = {
      connected: "Verbunden",
      connecting: "Verbinde...",
      disconnected: "Getrennt",
    }[this._connectionState] || this._connectionState;

    let devicesHtml;
    if (this._devices.length === 0) {
      devicesHtml = `
        <div class="empty-state">
          <p>Keine Geräte gefunden.</p>
          <button class="secondary" data-action="refresh">Aktualisieren</button>
        </div>
      `;
    } else {
      devicesHtml = `<div class="device-grid">
        ${this._devices
          .map(
            (d) => `
          <div class="device-card" data-action="select" data-device-id="${d.id}">
            <div class="online-indicator ${d.online ? "online" : "offline"}"></div>
            <div class="device-name">${this._esc(d.name)}</div>
            <div class="device-type">${this._esc(d.type.replace(/_/g, " "))}</div>
            <div class="device-room">📍 ${this._esc(d.room || "—")}</div>
          </div>`
          )
          .join("")}
      </div>`;
    }

    return `
      <div class="toolbar">
        <h1>
          Alexa Geräte
          <span class="status-badge ${stateClass}">${stateLabel}</span>
        </h1>
        <div class="toolbar-actions">
          <button class="secondary" data-action="refresh">↻ Aktualisieren</button>
        </div>
      </div>
      ${devicesHtml}
    `;
  }

  _renderDetail() {
    const d = this._selectedDevice;
    return `
      <div class="detail-view">
        <div class="detail-header">
          <button class="secondary" data-action="back">← Zurück</button>
          <h2>${this._esc(d.name)}</h2>
          <span class="status-badge ${d.online ? "status-connected" : "status-disconnected"}">
            ${d.online ? "Online" : "Offline"}
          </span>
        </div>

        <div class="detail-section">
          <h3>Geräteinformationen</h3>
          <div class="detail-row"><span class="label">ID</span><span class="value">${this._esc(d.id)}</span></div>
          <div class="detail-row"><span class="label">Typ</span><span class="value">${this._esc(d.type.replace(/_/g, " "))}</span></div>
          <div class="detail-row"><span class="label">Familie</span><span class="value">${this._esc(d.family)}</span></div>
          <div class="detail-row"><span class="label">Seriennummer</span><span class="value">${this._esc(d.serial)}</span></div>
          <div class="detail-row"><span class="label">Firmware</span><span class="value">${this._esc(d.firmware)}</span></div>
          <div class="detail-row"><span class="label">Raum</span><span class="value">${this._esc(d.room || "—")}</span></div>
        </div>

        <div class="detail-section">
          <h3>Fähigkeiten</h3>
          <div class="capabilities">
            ${(d.capabilities || []).map((c) => `<span class="capability-chip">${this._esc(c)}</span>`).join("")}
          </div>
        </div>

        <div class="detail-section">
          <h3>Aktionen</h3>
          <div class="detail-actions">
            <button class="secondary" data-action="rename" data-device-id="${d.id}">✏️ Umbenennen</button>
            <button class="danger" data-action="delete" data-device-id="${d.id}">🗑️ Löschen</button>
          </div>
        </div>
      </div>
    `;
  }

  // ------------------------------------------------------------------
  // Event handling
  // ------------------------------------------------------------------

  _attachEventListeners() {
    this.shadowRoot.querySelectorAll("[data-action]").forEach((el) => {
      el.addEventListener("click", (e) => {
        const action = e.currentTarget.dataset.action;
        const deviceId = e.currentTarget.dataset.deviceId;

        switch (action) {
          case "select":
            this._selectedDevice = this._devices.find((d) => d.id === deviceId);
            this._view = "detail";
            this._render();
            break;
          case "back":
            this._selectedDevice = null;
            this._view = "list";
            this._render();
            break;
          case "refresh":
            this._refreshDevices();
            break;
          case "delete":
            this._deleteDevice(deviceId);
            break;
          case "rename":
            this._handleRename(deviceId);
            break;
        }
      });
    });
  }

  _handleRename(deviceId) {
    const device = this._devices.find((d) => d.id === deviceId);
    if (!device) return;
    const newName = prompt("Neuer Name:", device.name);
    if (newName && newName !== device.name) {
      this._renameDevice(deviceId, newName);
    }
  }

  // ------------------------------------------------------------------
  // Utilities
  // ------------------------------------------------------------------

  _esc(str) {
    const div = document.createElement("div");
    div.textContent = str || "";
    return div.innerHTML;
  }
}

customElements.define("alexa-device-management", AlexaDeviceManagementPanel);

