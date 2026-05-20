class AlexaDeviceManagementPanel extends HTMLElement {
  connectedCallback() {
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          padding: 16px;
          font-family: sans-serif;
        }
        .card {
          border: 1px solid #ddd;
          border-radius: 8px;
          padding: 16px;
          max-width: 800px;
          background: #fff;
        }
        h2 {
          margin-top: 0;
        }
      </style>
      <div class="card">
        <h2>Alexa Device Management</h2>
        <p>Grundgerüst aktiv. Hier können später Alexa-Geräte geladen und gelöscht werden.</p>
      </div>
    `;
  }
}

customElements.define("alexa-device-management", AlexaDeviceManagementPanel);
