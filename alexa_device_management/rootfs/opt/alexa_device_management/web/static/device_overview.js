(() => {
  const BASE = document.documentElement.dataset.ingressPath || "";
  let model = null;
  let config = null;
  let saveTimer = null;
  let savePromise = Promise.resolve();
  let yamlRevision = null;
  let overviewPollTimer = null;
  let overviewPollCount = 0;
  const expandedAreas = new Set();
  const expandedDevices = new Set();
  const selectedAlexaKeys = new Set();
  const visibleAreaCounts = new Map();
  const renderedAreaItems = new Map();
  const AREA_PAGE_SIZE = 25;
  let alexaDeletePollTimer = null;

  const BUTTON_TOOLTIPS = {
    "btn-login": "Verbindet die App mit deinem Amazon-Alexa-Konto.",
    "btn-logout": "Löscht die gespeicherte Alexa-Web-Sitzung aus der App.",
    "btn-refresh": "Lädt Geräte, Entitäten, Räume und den Alexa-Bestand neu.",
    "btn-settings": "Öffnet Einstellungen für Alexa-Abgleich, Alexa-Gruppen und Export.",
    "btn-preview": "Zeigt die v6-Hauptkonfiguration; sie kann im YAML-Editor geändert werden.",
    "btn-restart": "Startet Home Assistant neu, um einen neu eingerichteten oder aktualisierten Alexa-Abgleichsdienst zu laden.",
    "btn-event-sync": "Sendet die v6-Endpunkte per AddOrUpdateReport, entfernte native Endpunkte per DeleteReport und bereinigt erkannte HA-v5-Geräte. Schreibt keine alexa.yaml.",
    "btn-group-sync": "Ordnet bereits vorhandene Alexa-Endpunkte den konfigurierten Alexa-Gruppen zu.",
    "btn-enable-useful": "Aktiviert alle aktuell sichtbaren, für Alexa sinnvoll erkannten Entitäten.",
    "btn-disable-visible": "Deaktiviert den Alexa-Export für alle aktuell sichtbaren Entitäten.",
    "btn-hide-technical": "Blendet aktuell sichtbare Diagnose-, Energie- und andere technische Entitäten aus.",
    "btn-unhide-visible": "Blendet die durch den aktuellen Filter gefundenen Einträge wieder ein.",
    "btn-save-settings": "Speichert die Einstellungen und richtet bei aktiviertem Alexa-Abgleich den benötigten HA-Dienst ein.",
    "btn-close-yaml": "Schließt den YAML-Editor.",
    "btn-save-yaml": "Validiert und speichert die v6-Hauptkonfiguration ohne AWS-Deployment."
  };
  const ACTION_TOOLTIPS = {
    "toggle-area": "Öffnet oder schließt diesen Raum.",
    "more-area": "Zeigt den nächsten Block von Geräten in diesem Raum.",
    "toggle-device": "Öffnet oder schließt die Entitäten dieses Geräts.",
    "prepare-device": "Aktiviert automatisch eine geeignete Entität dieses Geräts. Weitere Entitäten können danach manuell ergänzt werden.",
    "disable-device-export": "Deaktiviert alle Entitäten dieses Geräts für Alexa.",
    "toggle-simple-device": "Öffnet oder schließt die manuelle Entitäts- und Namensauswahl.",
    "hide-device": "Blendet das Gerät in dieser Verwaltung aus, ohne es aus Home Assistant zu löschen.",
    "show-device": "Blendet das Gerät in dieser Verwaltung wieder ein.",
    "hide-entity": "Blendet diese Entität in der Verwaltung aus.",
    "show-entity": "Blendet diese Entität in der Verwaltung wieder ein.",
    "hide-alexa": "Blendet diesen Alexa-Endpunkt nur in der Verwaltung aus.",
    "show-alexa": "Blendet diesen Alexa-Endpunkt in der Verwaltung wieder ein.",
    "details-alexa": "Zeigt die von Alexa gelieferten Rohdaten dieses Geräts aus dem letzten Bestandsabruf.",
    "rename-alexa": "Ändert den Namen des bereits bei Alexa vorhandenen Endpunkts.",
    "delete-alexa": "Löscht den bereits bei Alexa vorhandenen Endpunkt.",
    "delete-selected-alexa": "Löscht die ausgewählten Alexa-Geräte nach einer Sicherheitsabfrage nacheinander.",
    "assign-group": "Ordnet diesen Alexa-Endpunkt der angegebenen Alexa-Gruppe zu.",
    "configure-device-group": "Wählt die exportierten Entitäten, den Alexa-Gesamtnamen und die Exportform dieses Home-Assistant-Geräts.",
    "fill-entity": "Übernimmt den automatisch ermittelten Alexa-Namen und die passende Kategorie.",
    "suggest-simple-name": "Übernimmt den vorgeschlagenen Alexa-Namen in das weiterhin editierbare Namensfeld."
  };

  const STATUS_TEXT = {
    synced: "In Alexa zugeordnet",
    pending: "In Alexa ausstehend",
    only_alexa: "Deaktiviert, aber noch in Alexa",
    duplicate: "Mehrfach in Alexa",
    not_exposed: "Nicht für Alexa",
    problem: "Problem",
    orphaned: "Verwaist",
    unmatched: "Nur Alexa",
    alexa_device: "Alexa-Gerät"
  };

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
    })[char]);
  }
  function attr(value) { return esc(value).replace(/`/g, "&#096;"); }

  async function request(path, options = {}) {
    const response = await fetch(`${BASE}${path}`, {
      headers: {"Content-Type": "application/json", ...(options.headers || {})},
      ...options
    });
    let body = {};
    try { body = await response.json(); } catch (_) {}
    if (!response.ok) {
      const error = new Error(body.error || body.message || `HTTP ${response.status}`);
      error.body = body;
      throw error;
    }
    return body;
  }

  function message(text, type = "ok") {
    const element = document.getElementById("message");
    element.textContent = text;
    element.className = `message ${type}`;
  }
  function clearMessage() { document.getElementById("message").className = "message hidden"; }
  function setBusy(button, busy, text) {
    if (!button) return;
    if (busy) {
      button.dataset.oldText = button.textContent;
      button.disabled = true;
      button.textContent = text;
    } else {
      button.disabled = false;
      button.textContent = button.dataset.oldText || button.textContent;
    }
  }

  function buttonTooltipText(element) {
    if (!element) return "";
    if (BUTTON_TOOLTIPS[element.id]) return BUTTON_TOOLTIPS[element.id];
    if (ACTION_TOOLTIPS[element.dataset?.action]) return ACTION_TOOLTIPS[element.dataset.action];
    if (element.matches('a[href$="/debug"]')) return "Öffnet Diagnoseinformationen für die Fehlersuche.";
    if (element.value === "cancel" || element.textContent.trim() === "Schließen") return "Schließt dieses Fenster ohne weitere Aktion.";
    return element.title || "";
  }

  function showButtonTooltip(element) {
    const tooltip = document.getElementById("button-tooltip");
    const text = buttonTooltipText(element);
    if (!tooltip || !text) return;
    tooltip.textContent = text;
    tooltip.classList.add("visible");
    tooltip.setAttribute("aria-hidden", "false");
    element.setAttribute("aria-describedby", "button-tooltip");
    const rect = element.getBoundingClientRect();
    const tipRect = tooltip.getBoundingClientRect();
    const left = Math.max(12, Math.min(rect.left + (rect.width - tipRect.width) / 2, window.innerWidth - tipRect.width - 12));
    const below = rect.bottom + 8;
    const top = below + tipRect.height <= window.innerHeight - 8 ? below : Math.max(8, rect.top - tipRect.height - 8);
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }

  function hideButtonTooltip(element) {
    const tooltip = document.getElementById("button-tooltip");
    if (!tooltip) return;
    tooltip.classList.remove("visible");
    tooltip.setAttribute("aria-hidden", "true");
    element?.removeAttribute("aria-describedby");
  }

  function entityConfig(entityId) {
    config.entities ||= {};
    return config.entities[entityId] ||= {
      enabled: false, name: "", description: "", display_category: "", alexa_group: ""
    };
  }

  function isTechnical(entity) {
    const text = `${entity.entity_id || ""} ${entity.name || ""} ${entity.device_class || ""}`.toLowerCase();
    const technicalDomains = ["button", "update", "number", "select", "event"];
    const words = ["power", "energy", "leistung", "energie", "rssi", "signal", "battery", "batterie", "voltage", "spannung", "current", "strom", "diagnostic", "ping", "uptime", "last seen", "firmware", "linkquality", "illuminance"];
    return Boolean(entity.entity_category) || technicalDomains.includes(entity.domain) || words.