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
  const expandedSimpleDevices = new Set();
  const stagedAutoGroupDeviceIds = new Set();
  const pendingVirtualGroups = new Map();
  const selectedAlexaKeys = new Set();
  const visibleAreaCounts = new Map();
  const renderedAreaItems = new Map();
  let includeHiddenSummaryMatches = false;
  const AREA_PAGE_SIZE = 25;
  const EDIT_DRAFT_KEY = "alexa_device_management_edit_draft_v1";
  const EDITABLE_ENTITY_FIELDS = ["enabled", "name", "description", "display_category", "display_category_mode", "alexa_group", "capability_mode", "capabilities"];
  let globalEditMode = false;
  let pendingGlobalEdit = false;
  let editBaseEntities = null;
  let draftRestoreFilters = null;
  let draftRestoreScrollY = null;
  let draftRestoreActiveVirtualGroupId = null;
  let activeVirtualGroupId = null;
  let draftPersistenceTimer = null;
  let alexaDeletePollTimer = null;
  let syncPauseClientId = null;
  let syncPausePromise = null;
  let syncPauseHeartbeatTimer = null;
  let lifecyclePausedElsewhere = false;

  const BUTTON_TOOLTIPS = {
    "btn-login": "Verbindet die App mit deinem Amazon-Alexa-Konto.",
    "btn-logout": "Löscht die gespeicherte Alexa-Web-Sitzung aus der App.",
    "btn-refresh": "Lädt Geräte, Entitäten, Räume und den Alexa-Bestand neu.",
    "btn-settings": "Öffnet Einstellungen für Alexa-Abgleich, Alexa-Gruppen und Export.",
    "btn-preview": "Zeigt die v6-Hauptkonfiguration; sie kann im YAML-Editor geändert werden.",
    "btn-restart": "Startet Home Assistant neu, um einen neu eingerichteten oder aktualisierten Alexa-Abgleichsdienst zu laden.",
    "btn-event-sync": "Übernimmt bei alten, noch nicht gruppierten v6-Geräten den Standard, fasst bereits ausgewählte Entities desselben HA-Geräts zusammen und sendet danach per AddOrUpdateReport die Änderungen an Alexa. Entfernte Endpunkte werden per DeleteReport bereinigt. Deaktivierte Entities bleiben deaktiviert; ausdrücklich getrennte oder angepasste Geräte bleiben erhalten. Schreibt keine alexa.yaml.",
    "btn-group-sync": "Ordnet bereits vorhandene Alexa-Endpunkte den konfigurierten Alexa-Gruppen zu.",
    "btn-enable-useful": "Merkt für die aktuell sichtbaren Home-Assistant-Geräte die unterstützten Standardfunktionen vor. Erst „Fertig“ speichert sie gemeinsam mit den anderen Änderungen.",
    "btn-start-edit": "Pausiert den Alexa-Abgleich und aktiviert die Eingaben für alle geöffneten Entitätenlisten.",
    "btn-finish-edit": "Speichert alle Änderungen und vorgemerkten Standardprofile gemeinsam und setzt danach den Alexa-Abgleich fort.",
    "btn-discard-edit": "Verwirft den ungespeicherten Entwurf und setzt den Alexa-Abgleich fort.",
    "btn-create-virtual-group": "Stellt ein Alexa-Gesamtgerät aus Entitäten beliebiger Home-Assistant-Geräte zusammen. Es wird erst mit „Fertig“ gespeichert.",
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
    "toggle-simple-device": "Öffnet oder schließt die Entitäten dieses Geräts.",
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
    "configure-device-group": "Zeigt die Alexa-Vorschau und lässt Mehrfachausgänge bei Bedarf auf mehrere Alexa-Geräte aufteilen.",
    "edit-virtual-group": "Öffnet das virtuelle Alexa-Gesamtgerät im zentralen Bearbeitungsentwurf.",
    "remove-virtual-group": "Löst dieses virtuelle Gesamtgerät im Entwurf auf. Die Entities bleiben als einzelne Alexa-Geräte erhalten.",
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
  function hasEditorSession() {
    return globalEditMode || pendingGlobalEdit;
  }
  function editPauseClientId() {
    if (!syncPauseClientId) {
      syncPauseClientId = window.crypto?.randomUUID?.()
        || `adm-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    }
    return syncPauseClientId;
  }
  function updateSyncEditStatus() {
    const status = document.getElementById("sync-edit-status");
    if (!status) return;
    const paused = hasEditorSession() || lifecyclePausedElsewhere;
    status.classList.toggle("hidden", !paused);
    status.textContent = pendingGlobalEdit
      ? "Warte auf den Abschluss eines laufenden Abgleichs. Danach werden die Eingaben freigeschaltet."
      : globalEditMode
        ? "Bearbeitungsmodus aktiv: Der Alexa-Abgleich ist pausiert. Alle Änderungen werden als Entwurf gesichert und erst gemeinsam mit „Fertig“ übernommen."
        : lifecyclePausedElsewhere
          ? "Der Alexa-Hintergrundabgleich ist pausiert, weil eine andere Ansicht gerade Geräte bearbeitet."
          : "";
    for (const id of [
      "btn-refresh", "btn-event-sync", "btn-group-sync",
      "btn-hide-technical", "btn-unhide-visible", "btn-preview", "btn-settings", "btn-restart", "btn-logout"
    ]) {
      const button = document.getElementById(id);
      if (button) {
        const busy = button.dataset.oldText && button.textContent !== button.dataset.oldText;
        button.disabled = paused || Boolean(busy);
      }
    }
    const start = document.getElementById("btn-start-edit");
    const finish = document.getElementById("btn-finish-edit");
    const discard = document.getElementById("btn-discard-edit");
    if (start) {
      start.classList.toggle("hidden", globalEditMode || pendingGlobalEdit);
      start.disabled = pendingGlobalEdit || lifecyclePausedElsewhere;
      start.textContent = hasSavedEditDraft() ? "Entwurf fortsetzen" : "Bearbeiten";
    }
    const autoGroup = document.getElementById("btn-enable-useful");
    if (autoGroup) autoGroup.disabled = !globalEditMode || pendingGlobalEdit;
    const virtualGroup = document.getElementById("btn-create-virtual-group");
    if (virtualGroup) virtualGroup.disabled = !globalEditMode || pendingGlobalEdit;
    if (finish) {
      finish.classList.toggle("hidden", !globalEditMode && !pendingGlobalEdit);
      finish.disabled = !globalEditMode || pendingGlobalEdit;
    }
    if (discard) {
      discard.classList.toggle("hidden", !globalEditMode && !pendingGlobalEdit && !hasSavedEditDraft());
      discard.disabled = pendingGlobalEdit;
    }
    document.getElementById("device-edit-title")?.replaceChildren(document.createTextNode(globalEditMode
      ? "Geräte zentral bearbeiten" : hasSavedEditDraft() ? "Offener Entwurf" : "Geräte zentral bearbeiten"));
    document.getElementById("device-edit-description")?.replaceChildren(document.createTextNode(globalEditMode
      ? "Eingaben und Auswahl werden automatisch als Entwurf gesichert. „Fertig“ übernimmt alles gemeinsam; ein Neuladen verwirft nichts." + (stagedAutoGroupDeviceIds.size ? " " + stagedAutoGroupDeviceIds.size + " Standardgeräte vorgemerkt." : "")
      : "Einmal bearbeiten, dann alle Änderungen gemeinsam speichern. Ein offener Entwurf bleibt auch nach einem Neuladen erhalten."));
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
    return Boolean(entity.entity_category) || technicalDomains.includes(entity.domain) || words.some(word => text.includes(word));
  }
  function isUseful(entity) {
    return !isTechnical(entity) && ["light", "switch", "cover", "climate", "fan"].includes(entity.domain);
  }
  function suggestedCategory(entity, device = null) {
    if (entity.domain === "light") return "LIGHT";
    if (entity.domain === "cover") return entity.device_class === "garage" ? "GARAGE_DOOR" : "INTERIOR_BLIND";
    if (entity.domain === "climate") return "THERMOSTAT";
    if (entity.domain === "lock") return "LOCK";
    if (entity.domain === "camera") return "CAMERA";
    if (["scene", "script"].includes(entity.domain)) return "SCENE_TRIGGER";
    if (entity.domain === "switch") {
      const text = `${entity.entity_id || ""} ${entity.name || ""} ${device?.name || ""}`.toLocaleLowerCase();
      if (entity.device_class === "outlet" || /steckdose|stecker|smart ?plug|socket|outlet|plug/.test(text)) return "SMARTPLUG";
      if (/lampe|licht|light|beleuchtung|bulb/.test(text)) return "LIGHT";
      if (entity.category_suggestion && entity.category_suggestion !== "OTHER") return entity.category_suggestion;
      return "SWITCH";
    }
    if (entity.category_suggestion && entity.category_suggestion !== "OTHER") return entity.category_suggestion;
    return "SWITCH";
  }
  function capabilityOptions(entity) {
    const power = {id: "Alexa.PowerController", label: "Ein/Aus-Schalter"};
    if (entity.domain === "light") {
      const options = [power];
      const modes = entity.supported_color_modes || [];
      if (modes.some(mode => !["onoff", "unknown"].includes(mode))) {
        options.push({id: "Alexa.BrightnessController", label: "Helligkeit / Dimmer-Slider"});
      }
      return options;
    }
    if (["switch", "fan"].includes(entity.domain)) return [power];
    if (entity.domain === "cover") {
      const options = [];
      if ((Number(entity.supported_features || 0) & 4) === 4) {
        options.push({id: "Alexa.RangeController", label: "Position / Slider"});
      }
      options.push({id: "Alexa.PlaybackController", label: "Stopp-Taste"});
      return options;
    }
    if (entity.domain === "climate") return [{id: "Alexa.ThermostatController", label: "Thermostat: Modus, Sollwert und Ist-Temperatur"}];
    if (entity.domain === "binary_sensor") {
      if (["door", "window", "opening", "garage_door", "lock"].includes(entity.device_class)) {
        return [{id: "Alexa.ContactSensor", label: "Kontaktstatus (nur lesen)"}];
      }
      if (["motion", "occupancy", "presence"].includes(entity.device_class)) {
        return [{id: "Alexa.MotionSensor", label: "Bewegung (nur lesen)"}];
      }
    }
    if (entity.domain === "sensor" && entity.device_class === "temperature") {
      return [{id: "Alexa.TemperatureSensor", label: "Temperatur (nur lesen)"}];
    }
    return [];
  }
  function defaultAlexaRangeUnit(entity) {
    const unit = String(entity.unit_of_measurement || "").trim().toLocaleLowerCase();
    if (["%", "percent", "percentage"].includes(unit)) return "Alexa.Unit.Percent";
    if (["l", "liter", "liters", "litre", "litres"].includes(unit)) return "Alexa.Unit.Liters";
    if (["°c", "c", "celsius"].includes(unit)) return "Alexa.Unit.Temperature";
    return "";
  }
  function canUseReadOnlyRange(entity) {
    if (!entity || !["sensor", "number", "input_number"].includes(entity.domain)) return false;
    return Number.isFinite(Number(entity.state)) && String(entity.state ?? "").trim() !== "";
  }
  function virtualProfileOptions(entity, keepExisting = false) {
    const options = [];
    if (capabilityOptions(entity).length) options.push({id: "standard", label: "Standardfunktionen"});
    if (canUseReadOnlyRange(entity)) options.push({id: "read_only_range", label: "Zahlenwert (nur lesen, Alexa-Slider)"});
    if (keepExisting) options.push({id: "preserve", label: "Bisherige Alexa-Funktion beibehalten"});
    return options;
  }
  function virtualCapabilityLabels(entity, profile) {
    if (profile?.mode === "read_only_range") return [`Messwert-Slider (${profile.unit || entity.unit_of_measurement || "Einheit festlegen"})`];
    if (profile?.mode === "preserve") return ["bisherige Alexa-Funktion"];
    return capabilityOptions(entity).map(option => option.label);
  }
  function roleNote(entity) {
    const text = `${entity.entity_id || ""} ${entity.name || ""}`.toLocaleLowerCase();
    if (entity.domain === "switch" && /heiz|thermostat|radiator|heating|valve|ventil/.test(text)) {
      return "Heizventil-Relais werden als Ein/Aus-Schalter exportiert. Sollwert und Temperatur kommen von einer climate-Entität.";
    }
    return "";
  }
  function suggestedName(entity, device) {
    let value = String(entity.name || device.name || entity.entity_id || "Gerät")
      .replace(/\b(node|channel|kanal|switch|sensor|device|entity)\b/gi, "")
      .replace(/\b\d{3,}\b/g, "").replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
    if (device.area_name && !value.toLowerCase().includes(device.area_name.toLowerCase())) value += ` ${device.area_name}`;
    if (device.floor_name && !value.toLowerCase().includes(device.floor_name.toLowerCase())) value += ` ${device.floor_name}`;
    return value.trim() || entity.entity_id;
  }
  function statusBadge(status) {
    const problem = ["only_alexa", "duplicate", "problem", "orphaned"].includes(status);
    const cls = status === "synced" ? "synced" : status === "pending" ? "pending" : problem ? "problem" : "";
    return `<span class="badge ${cls}">${esc(STATUS_TEXT[status] || status)}</span>`;
  }

  function devicePreviewText(device) {
    const suggestion = device.grouping_suggestion || {};
    const ids = Array.isArray(suggestion.entity_ids) ? suggestion.entity_ids : [];
    if (!ids.length) return "Alexa-Vorschau: keine unterstützte Standardfunktion";
    const selected = ids.map(id => (device.entities || []).find(entity => entity.entity_id === id))
      .filter(Boolean);
    const mode = suggestion.mode === "separate" ? "separate" : "combined";
    const descriptions = selected.map(entity => {
      const settings = entityConfig(entity.entity_id);
      const funcs = entity.export?.capability_mode === "custom"
        ? (entity.export.capabilities || []).map(id => ({id, label: capabilityOptions(entity).find(option => option.id === id)?.label || id}))
        : capabilityOptions(entity).filter(option => option.id !== "Alexa.PlaybackController");
      const controls = funcs.map(option => option.label).join(", ") || "Funktion";
      return `${settings.name || entity.name || entity.entity_id} (${controls})`;
    });
    if (mode === "separate") {
      const label = suggestion.reason === "configured" ? "Alexa aktuell" : "Alexa-Vorschau (Standard)";
      return `${label}: ${selected.length} Gerät${selected.length === 1 ? "" : "e"} · ${descriptions.slice(0, 3).join("; ")}${descriptions.length > 3 ? `; +${descriptions.length - 3}` : ""}`;
    }
    const functions = selected.flatMap(entity => {
      const settings = entityConfig(entity.entity_id);
      const funcs = entity.export?.capability_mode === "custom"
        ? (entity.export.capabilities || []).map(id => ({id, label: capabilityOptions(entity).find(option => option.id === id)?.label || id}))
        : capabilityOptions(entity).filter(option => option.id !== "Alexa.PlaybackController");
      return funcs.map(option => `${settings.name || entity.name || entity.entity_id}: ${option.label}`);
    });
    const name = suggestion.name || device.name || "Home-Assistant-Gerät";
    const label = suggestion.reason === "configured" ? "Alexa aktuell" : "Alexa-Vorschau (Standard)";
    return `${label}: 1 Gerät „${name}“ · ${functions.slice(0, 4).join("; ")}${functions.length > 4 ? `; +${functions.length - 4}` : ""}`;
  }

  function readEditDraft() {
    try {
      const value = localStorage.getItem(EDIT_DRAFT_KEY);
      if (!value) return null;
      const draft = JSON.parse(value);
      return draft && draft.version === 1 && draft.entities && typeof draft.entities === "object" ? draft : null;
    } catch (_) {
      return null;
    }
  }

  function hasSavedEditDraft() { return Boolean(readEditDraft()); }

  function persistEditDraft() {
    if ((!globalEditMode && !pendingGlobalEdit) || !config) return;
    clearTimeout(draftPersistenceTimer);
    draftPersistenceTimer = null;
    const draft = {
      version: 1,
      client_id: syncPauseClientId,
      base_revision: editBaseEntities?.revision || config.native_revision,
      base_entities: editBaseEntities?.entities || {},
      entities: config.entities || {},
      ui: {
        expanded_areas: [...expandedAreas],
        expanded_devices: [...expandedDevices],
        expanded_simple_devices: [...expandedSimpleDevices],
        auto_group_device_ids: [...stagedAutoGroupDeviceIds],
        pending_virtual_groups: [...pendingVirtualGroups.entries()],
        active_virtual_group_id: activeVirtualGroupId,
        visible_area_counts: [...visibleAreaCounts.entries()],
        scroll_y: window.scrollY,
        filters: {
          query: document.getElementById("search")?.value || "",
          status: document.getElementById("status-filter")?.value || "all",
          area: document.getElementById("area-filter")?.value || "",
          domain: document.getElementById("domain-filter")?.value || "",
          include_hidden: includeHiddenSummaryMatches
        }
      }
    };
    try {
      localStorage.setItem(EDIT_DRAFT_KEY, JSON.stringify(draft));
    } catch (error) {
      message(`Der Entwurf konnte nicht lokal gesichert werden: ${error.message}`, "err");
    }
  }

  function scheduleEditDraftPersistence() {
    if (!globalEditMode) return;
    clearTimeout(draftPersistenceTimer);
    draftPersistenceTimer = setTimeout(persistEditDraft, 100);
  }

  function syncEntityModelFromConfig() {
    for (const device of model?.devices || []) for (const entity of device.entities || []) {
      const settings = config.entities?.[entity.entity_id];
      if (settings) entity.export = {...(entity.export || {}), ...settings};
    }
  }

  function restoreEditDraft() {
    const draft = readEditDraft();
    if (!draft || !config) return false;
    const baseEntities = draft.base_entities && typeof draft.base_entities === "object" ? draft.base_entities : {};
    const draftEntities = draft.entities && typeof draft.entities === "object" ? draft.entities : {};
    config.entities ||= {};
    const defaults = {enabled: false, name: "", description: "", display_category: "", alexa_group: ""};
    for (const [entityId, saved] of Object.entries(draftEntities)) {
      if (!saved || typeof saved !== "object") continue;
      const baseline = baseEntities[entityId] || defaults;
      const current = config.entities[entityId] ||= {...defaults};
      for (const field of EDITABLE_ENTITY_FIELDS) {
        if (JSON.stringify(saved[field]) !== JSON.stringify(baseline[field]) && field in saved) current[field] = saved[field];
      }
    }
    editBaseEntities = {revision: draft.base_revision, entities: baseEntities};
    syncPauseClientId = typeof draft.client_id === "string" && draft.client_id ? draft.client_id : null;
    const ui = draft.ui || {};
    expandedAreas.clear();
    for (const value of Array.isArray(ui.expanded_areas) ? ui.expanded_areas : []) expandedAreas.add(String(value));
    expandedDevices.clear();
    for (const value of Array.isArray(ui.expanded_devices) ? ui.expanded_devices : []) expandedDevices.add(String(value));
    expandedSimpleDevices.clear();
    for (const value of Array.isArray(ui.expanded_simple_devices) ? ui.expanded_simple_devices : []) expandedSimpleDevices.add(String(value));
    stagedAutoGroupDeviceIds.clear();
    for (const value of Array.isArray(ui.auto_group_device_ids) ? ui.auto_group_device_ids : []) stagedAutoGroupDeviceIds.add(String(value));
    pendingVirtualGroups.clear();
    for (const pair of Array.isArray(ui.pending_virtual_groups) ? ui.pending_virtual_groups : []) {
      if (Array.isArray(pair) && pair.length === 2 && typeof pair[0] === "string") {
        pendingVirtualGroups.set(pair[0], pair[1] === null ? null : pair[1]);
      }
    }
    draftRestoreActiveVirtualGroupId = typeof ui.active_virtual_group_id === "string"
      ? ui.active_virtual_group_id : null;
    visibleAreaCounts.clear();
    for (const pair of Array.isArray(ui.visible_area_counts) ? ui.visible_area_counts : []) {
      if (Array.isArray(pair) && pair.length === 2) visibleAreaCounts.set(String(pair[0]), Number(pair[1]) || AREA_PAGE_SIZE);
    }
    draftRestoreFilters = ui.filters && typeof ui.filters === "object" ? ui.filters : null;
    draftRestoreScrollY = Number.isFinite(Number(ui.scroll_y)) ? Number(ui.scroll_y) : null;
    if (draftRestoreFilters) {
      document.getElementById("search").value = String(draftRestoreFilters.query || "");
      document.getElementById("status-filter").value = String(draftRestoreFilters.status || "all");
      includeHiddenSummaryMatches = Boolean(draftRestoreFilters.include_hidden);
    }
    pendingGlobalEdit = true;
    syncEntityModelFromConfig();
    return true;
  }

  function scheduleSave() {
    if (globalEditMode || pendingGlobalEdit) {
      scheduleEditDraftPersistence();
      return;
    }
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => { saveConfig().catch(() => {}); }, 500);
  }
  function saveConfig() {
    clearTimeout(saveTimer);
    if (!config) return Promise.resolve();
    savePromise = savePromise.catch(() => {}).then(async () => {
      // Capture only after earlier queued saves complete so the native revision
      // is current and rapid edits cannot overwrite each other with a stale CAS.
      const snapshot = JSON.parse(JSON.stringify(config));
      try {
        const result = await request("/api/ha-export/autosave", {method: "POST", body: JSON.stringify(snapshot)});
        if (result.configuration?.native_revision) config.native_revision = result.configuration.native_revision;
        for (const [entityId, saved] of Object.entries(result.configuration?.entities || {})) {
          const current = config.entities?.[entityId];
          if (current) {
            for (const field of ["enabled", "name", "description", "display_category", "display_category_mode", "alexa_group", "capability_mode", "capabilities"]) {
              if (current[field] === snapshot.entities?.[entityId]?.[field]) current[field] = saved[field];
            }
          }
        }
        return result;
      } catch (error) {
        message(`Autosave fehlgeschlagen: ${error.message}`, "err");
        throw error;
      }
    });
    return savePromise;
  }

  function allAlexaItems() {
    const values = [];
    for (const device of model?.devices || []) for (const entity of device.entities || []) values.push(...(entity.alexa?.matches || []));
    values.push(...(model?.alexa_only || []));
    return values;
  }
  function findAlexa(key) { return allAlexaItems().find(item => item.key === key); }
  function filters() {
    return {
      query: document.getElementById("search").value.trim().toLowerCase(),
      status: document.getElementById("status-filter").value,
      area: document.getElementById("area-filter").value,
      domain: document.getElementById("domain-filter").value,
      includeHidden: includeHiddenSummaryMatches
    };
  }

  function entityMatchesFilter(entity, device, filter) {
    const hidden = entity.hidden || device.hidden;
    if (filter.status === "hidden") { if (!hidden) return false; }
    else if (hidden && !filter.includeHidden) return false;
    if (filter.area && device.area_id !== filter.area) return false;
    if (filter.domain && entity.domain !== filter.domain) return false;
    if (filter.status === "selected" && !entity.export.enabled && !entity.native?.enabled) return false;
    if (filter.status === "synced" && entity.status !== "synced") return false;
    if (filter.status === "pending" && entity.status !== "pending") return false;
    if (filter.status === "only_alexa" && entity.status !== "only_alexa") return false;
    if (filter.status === "duplicates" && entity.status !== "duplicate") return false;
    if (filter.status === "problems" && !["only_alexa", "duplicate"].includes(entity.status)) return false;
    if (filter.status === "alexa_only") return false;
    if (filter.query) {
      const alexaText = (entity.alexa?.matches || []).map(item => `${item.name} ${item.room} ${(item.groups || []).join(" ")}`).join(" ");
      const haystack = `${device.name} ${device.area_name || ""} ${device.manufacturer || ""} ${entity.name} ${entity.entity_id} ${alexaText}`.toLowerCase();
      if (!haystack.includes(filter.query)) return false;
    }
    return true;
  }

  function alexaOnlyMatchesFilter(item, filter) {
    if (filter.status === "hidden") { if (!item.hidden) return false; }
    else if (item.hidden && !filter.includeHidden) return false;
    if (!["all", "alexa_only", "problems", "hidden"].includes(filter.status)) return false;
    if (filter.status === "problems" && !["orphaned", "unmatched"].includes(item.status)) return false;
    if (filter.query) {
      const haystack = `${item.name} ${item.serial} ${item.family} ${item.skill} ${item.room} ${(item.groups || []).join(" ")}`.toLowerCase();
      if (!haystack.includes(filter.query)) return false;
    }
    return true;
  }

  async function acquireSyncPause() {
    if (syncPausePromise) return syncPausePromise;
    const clientId = editPauseClientId();
    syncPausePromise = request("/api/native-export/lifecycle/pause", {
      method: "POST", body: JSON.stringify({client_id: clientId})
    }).then(() => {
      clearInterval(syncPauseHeartbeatTimer);
      syncPauseHeartbeatTimer = setInterval(async () => {
        if (!hasEditorSession() || !syncPauseClientId) return;
        try {
          await request("/api/native-export/lifecycle/pause", {
            method: "POST", body: JSON.stringify({client_id: syncPauseClientId})
          });
        } catch (error) {
          message(`Alexa-Abgleich konnte nicht weiter pausiert werden: ${error.message}`, "err");
        }
      }, 60_000);
    }).catch(error => {
      syncPausePromise = null;
      throw error;
    });
    return syncPausePromise;
  }

  async function releaseSyncPause() {
    if (!syncPauseClientId) return;
    await request("/api/native-export/lifecycle/resume", {
      method: "POST", body: JSON.stringify({client_id: syncPauseClientId})
    });
    clearInterval(syncPauseHeartbeatTimer);
    syncPauseHeartbeatTimer = null;
    syncPauseClientId = null;
    syncPausePromise = null;
  }

  window.addEventListener("pagehide", () => {
    if (!syncPauseClientId) return;
    clearInterval(syncPauseHeartbeatTimer);
    if (globalEditMode || pendingGlobalEdit || hasSavedEditDraft()) {
      persistEditDraft();
      return;
    }
    const url = `${BASE}/api/native-export/lifecycle/resume`;
    const body = new Blob([JSON.stringify({client_id: syncPauseClientId})], {type: "application/json"});
    if (!navigator.sendBeacon?.(url, body)) {
      fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body, keepalive: true}).catch(() => {});
    }
  });
  window.addEventListener("pageshow", event => {
    if (!event.persisted || !globalEditMode || !syncPauseClientId) return;
    syncPausePromise = null;
    acquireSyncPause().catch(error => message(`Alexa-Abgleich konnte nach dem Zurückkehren nicht erneut pausiert werden: ${error.message}`, "err"));
  });
  window.addEventListener("scroll", scheduleEditDraftPersistence, {passive: true});

  function renderSummary() {
    const s = model.summary || {};
    const cards = [
      ["HA-Geräte", s.ha_devices || 0, "ha_devices"],
      ["HA-Entitäten", s.ha_entities || 0, "ha_entities"],
      ["v6-Endpunkte", s.selected || 0, "selected"],
      ["In Alexa zugeordnet", s.synced || 0, "synced"],
      ["Ausstehend", s.pending || 0, "pending"],
      ["Alte v5-Geräte", s.only_alexa || 0, "only_alexa"],
      ["Duplikate", s.duplicates || 0, "duplicates"],
      ["Nur Alexa", s.alexa_only || 0, "alexa_only"],
      ["Ausgeblendet", s.hidden || 0, "hidden"]
    ];
    const currentStatus = filters().status;
    document.getElementById("summary").innerHTML = cards.map(([label, value, status]) => {
      const active = currentStatus === status;
      return `<button type="button" class="summary-card${active ? " active" : ""}" data-summary-filter="${status}" aria-pressed="${active}" aria-label="${value} ${esc(label)} anzeigen"><strong>${value}</strong>${esc(label)}</button>`;
    }).join("");
  }

  function expandSummaryMatches() {
    expandedAreas.clear();
    expandedSimpleDevices.clear();
    visibleAreaCounts.clear();
    if (filters().status === "alexa_only") return;
    const deviceCountsByArea = new Map();
    for (const device of model.devices || []) {
      const entities = (device.entities || []).filter(entity => entityMatchesFilter(entity, device, filters()));
      if (!entities.length) continue;
      const areaKey = device.area_id || device.area_name || "Ohne Bereich";
      expandedAreas.add(areaKey);
      if (filters().status !== "ha_devices") expandedSimpleDevices.add(device.device_id);
      deviceCountsByArea.set(areaKey, (deviceCountsByArea.get(areaKey) || 0) + 1);
    }
    for (const [areaKey, count] of deviceCountsByArea) visibleAreaCounts.set(areaKey, count);
  }

  function renderFilters() {
    const areaSelect = document.getElementById("area-filter");
    const currentArea = areaSelect.value;
    areaSelect.innerHTML = '<option value="">Alle Bereiche</option>' + (model.areas || []).map(area => `<option value="${attr(area.area_id)}">${esc(area.name)}</option>`).join("");
    areaSelect.value = currentArea;
    const domains = [...new Set((model.devices || []).flatMap(device => device.entities.map(entity => entity.domain)))].sort();
    const domainSelect = document.getElementById("domain-filter");
    const currentDomain = domainSelect.value;
    domainSelect.innerHTML = '<option value="">Alle Domains</option>' + domains.map(domain => `<option value="${attr(domain)}">${esc(domain)}</option>`).join("");
    domainSelect.value = currentDomain;
    if (draftRestoreFilters) {
      areaSelect.value = String(draftRestoreFilters.area || "");
      domainSelect.value = String(draftRestoreFilters.domain || "");
      draftRestoreFilters = null;
    }
    document.getElementById("group-list").innerHTML = (model.groups || []).map(group => `<option value="${attr(group.name)}"></option>`).join("");
    document.getElementById("btn-unhide-visible").classList.toggle("hidden", document.getElementById("status-filter").value !== "hidden");
  }

  function alexaMatchHtml(match, entity) {
    const groupText = (match.groups || []).length ? ` • Gruppen: ${(match.groups || []).join(", ")}` : "";
    const online = match.online === true ? "erreichbar" : match.online === false ? "nicht erreichbar" : "Status von Alexa nicht geliefert";
    return `<div class="alexa-match"><div class="alexa-line"><div><div class="alexa-name">${esc(match.name)}</div><div class="alexa-meta">${esc(match.source)} • ${esc(online)}${esc(groupText)}<br>${esc(match.serial)}</div></div><div class="alexa-actions"><button class="button secondary small" data-action="details-alexa" data-key="${attr(match.key)}">Weitere Infos</button><button class="button secondary small" data-action="rename-alexa" data-key="${attr(match.key)}">Umbenennen</button><button class="button danger small" data-action="delete-alexa" data-key="${attr(match.key)}">Löschen</button></div></div>${entity.export.alexa_group ? `<button class="button secondary small" data-action="assign-group" data-entity="${attr(entity.entity_id)}" data-key="${attr(match.key)}">Gruppe „${esc(entity.export.alexa_group)}“ zuweisen</button>` : ""}</div>`;
  }

  function entityHtml(entity, device) {
    const exportData = entity.export;
    const matches = entity.alexa?.matches || [];
    const categories = (model.display_categories || []).map(category => `<option value="${attr(category)}" ${exportData.display_category_mode === "custom" && exportData.display_category === category ? "selected" : ""}>${esc(category)}</option>`).join("");
    return `<article class="entity status-${attr(entity.status)} ${entity.hidden ? "hidden-item" : ""}" data-entity="${attr(entity.entity_id)}"><div class="entity-top"><input class="export-toggle" type="checkbox" data-entity="${attr(entity.entity_id)}" ${exportData.enabled ? "checked" : ""} title="Für Alexa exportieren"><div><div class="entity-name">${esc(entity.name || entity.entity_id)}</div><div class="entity-id">${esc(entity.entity_id)}</div><div class="badges">${statusBadge(entity.status)}${entity.native?.enabled ? '<span class="badge alexa">Nativ v6</span>' : ""}${matches.length ? `<span class="badge alexa">${matches.length} Alexa-Endpunkt${matches.length === 1 ? "" : "e"}</span>` : ""}${isTechnical(entity) ? '<span class="badge">technisch</span>' : ""}${entity.hidden ? '<span class="badge hidden-badge">ausgeblendet</span>' : ""}</div></div><button class="button secondary small" data-action="${entity.hidden_directly ? "show-entity" : "hide-entity"}" data-entity="${attr(entity.entity_id)}">${entity.hidden_directly ? "Einblenden" : "Ausblenden"}</button></div><div class="fields"><div class="field"><label>Alexa-Name</label><div class="entity-name-editor"><input class="export-name" data-entity="${attr(entity.entity_id)}" value="${attr(exportData.name)}" placeholder="${attr(suggestedName(entity, device))}"><button class="button secondary small save-entity-name" data-action="save-entity-name" data-entity="${attr(entity.entity_id)}">Speichern</button></div></div><div class="field"><label>Kategorie</label><select class="export-category" data-entity="${attr(entity.entity_id)}"><option value="" ${exportData.display_category_mode === "custom" ? "" : "selected"}>Automatisch (${esc(suggestedCategory(entity, device))})</option>${categories}</select></div><div class="field full"><label>Alexa-Gruppe</label><input class="export-group" data-entity="${attr(entity.entity_id)}" value="${attr(exportData.alexa_group)}" list="group-list" placeholder="${attr(device.area_name || "")}"></div></div><div class="entity-actions"><button class="button secondary small" data-action="fill-entity" data-entity="${attr(entity.entity_id)}">Vorschlag übernehmen</button></div>${matches.map(match => alexaMatchHtml(match, entity)).join("")}</article>`;
  }

  function deviceHtml(device, entities) {
    const expanded = expandedDevices.has(device.device_id);
    return `<section class="device status-${attr(device.status)} ${device.hidden ? "hidden-item" : ""}" data-device-section="${attr(device.device_id)}"><div class="device-head"><button class="collapse-toggle" data-action="toggle-device" data-device="${attr(device.device_id)}" aria-expanded="${expanded}">${expanded ? "▾" : "▸"}</button><div class="device-title"><div class="device-name">${esc(device.name)}</div><div class="device-meta">${esc(device.area_name || "Kein Bereich")}${device.floor_name ? ` • ${esc(device.floor_name)}` : ""}${device.manufacturer ? ` • ${esc(device.manufacturer)}` : ""}${device.model ? ` • ${esc(device.model)}` : ""}</div></div><div class="device-actions"><button class="button primary small" data-action="prepare-device" data-device="${attr(device.device_id)}">Sinnvoll aktivieren</button><button class="button secondary small" data-action="configure-device-group" data-device="${attr(device.device_id)}" title="Entitäten zu einem Alexa-Gesamtgerät gruppieren oder wieder trennen">Alexa-Gerät konfigurieren</button><button class="button secondary small" data-action="${device.hidden ? "show-device" : "hide-device"}" data-device="${attr(device.device_id)}">${device.hidden ? "Einblenden" : "Gerät ausblenden"}</button></div></div>${expanded ? `<div class="entity-grid">${entities.map(entity => entityHtml(entity, device)).join("")}</div>` : ""}</section>`;
  }

  function deviceSummaryElement(device) {
    const section = document.createElement("section");
    const safeStatus = String(device.status || "").replace(/[^a-z0-9_-]/gi, "");
    section.className = `device status-${safeStatus}${device.hidden ? " hidden-item" : ""}`;
    section.dataset.deviceSection = String(device.device_id || "");

    const head = document.createElement("div");
    head.className = "device-head";
    const toggle = document.createElement("button");
    toggle.className = "collapse-toggle";
    toggle.dataset.action = "toggle-device";
    toggle.dataset.device = String(device.device_id || "");
    toggle.setAttribute("aria-expanded", "false");
    toggle.textContent = "▸";

    const title = document.createElement("div");
    title.className = "device-title";
    const name = document.createElement("div");
    name.className = "device-name";
    name.textContent = String(device.name || device.device_id || "Unbekanntes Gerät");
    const meta = document.createElement("div");
    meta.className = "device-meta";
    meta.textContent = [device.area_name || "Kein Bereich", device.floor_name, device.manufacturer, device.model].filter(Boolean).map(String).join(" • ");
    title.append(name, meta);

    const actions = document.createElement("div");
    actions.className = "device-actions";
    const prepare = document.createElement("button");
    prepare.className = "button primary small";
    prepare.dataset.action = "prepare-device";
    prepare.dataset.device = String(device.device_id || "");
    prepare.textContent = "Automatisch exportieren";
    const visibility = document.createElement("button");
    visibility.className = "button secondary small";
    visibility.dataset.action = device.hidden ? "show-device" : "hide-device";
    visibility.dataset.device = String(device.device_id || "");
    visibility.textContent = device.hidden ? "Einblenden" : "Gerät ausblenden";
    const grouping = document.createElement("button");
    grouping.className = "button secondary small";
    grouping.dataset.action = "configure-device-group";
    grouping.dataset.device = String(device.device_id || "");
    grouping.textContent = "Vorschau / anpassen";
    grouping.title = "Alexa-Gruppierung ansehen oder Mehrfachausgänge anpassen";
    actions.append(prepare, grouping, visibility);
    head.append(toggle, title, actions);
    section.append(head);
    return section;
  }

  function areaItems(areaKey) {
    const filter = filters();
    const items = [];
    for (const device of model.devices || []) {
      const key = device.area_id || device.area_name || "Ohne Bereich";
      if (key !== areaKey) continue;
      const entities = (device.entities || []).filter(entity => entityMatchesFilter(entity, device, filter));
      if (entities.length) items.push({device, entities});
    }
    return items;
  }

  function renderArea(button, areaKey) {
    const section = button.closest("section.area");
    const container = section?.querySelector(".area-devices");
    if (!container) return;

    const expanded = expandedAreas.has(areaKey);
    button.textContent = expanded ? "▾" : "▸";
    button.setAttribute("aria-expanded", String(expanded));
    container.replaceChildren();
    if (!expanded) {
      scheduleEditDraftPersistence();
      return;
    }
    const items = renderedAreaItems.get(areaKey) || [];
    const visibleCount = Math.min(visibleAreaCounts.get(areaKey) || AREA_PAGE_SIZE, items.length);
    const list = document.createElement("div");
    list.className = "simple-device-list";
    for (const item of items.slice(0, visibleCount)) {
      const row = document.createElement("div");
      row.className = "simple-device-row";
      const deviceId = String(item.device.device_id || "");
      const isOpen = expandedSimpleDevices.has(deviceId);
      const isEditing = globalEditMode;
      const isWaiting = pendingGlobalEdit;
      row.dataset.deviceRow = deviceId;
      const info = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = String(item.device.name || item.device.device_id || "Unbekanntes Gerät");
      const detail = document.createElement("span");
      detail.className = "muted";
      const endpointIds = new Set(item.entities.flatMap(entity => entity.native?.endpoint_ids || []));
      detail.textContent = `${item.entities.length} HA-Entität${item.entities.length === 1 ? "" : "en"} · ${endpointIds.size} Alexa-Gerät${endpointIds.size === 1 ? "" : "e"} aktuell`;
      const preview = document.createElement("span");
      preview.className = "device-preview muted";
      preview.textContent = devicePreviewText(item.device);
      info.append(name, detail, preview);
      const actions = document.createElement("div");
      actions.className = "device-actions";
      const control = document.createElement("button");
      control.className = "button secondary small";
      control.dataset.action = "toggle-simple-device";
      control.dataset.device = deviceId;
      control.textContent = isOpen ? "Entitäten schließen" : "Entitäten anzeigen";
      control.disabled = isWaiting;
      control.setAttribute("aria-expanded", String(isOpen));
      if (!isEditing || !isOpen) actions.append(control);
      row.append(info, actions);
      if (isOpen) renderSimpleEntityList(row, item.device, isEditing);
      list.append(row);
    }
    container.append(list);
    if (visibleCount < items.length) {
      const more = document.createElement("button");
      more.className = "button secondary area-more";
      more.dataset.action = "more-area";
      more.dataset.area = areaKey;
      more.textContent = `Weitere ${Math.min(AREA_PAGE_SIZE, items.length - visibleCount)} Geräte anzeigen`;
      container.append(more);
    }
    scheduleEditDraftPersistence();
  }

  function renderSimpleEntityList(row, device, isEditing) {
    const list = document.createElement("div");
    list.className = `simple-entity-list${isEditing ? " editing" : ""}`;
    for (const entity of device.entities || []) {
      const entityRow = document.createElement("div");
      entityRow.className = "simple-entity-row";
      const settings = entityConfig(entity.entity_id);
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "export-toggle";
      checkbox.dataset.entity = String(entity.entity_id || "");
      checkbox.checked = Boolean(settings.enabled ?? entity.export?.enabled);
      checkbox.disabled = !isEditing;
      checkbox.setAttribute("aria-label", `${entity.name || entity.entity_id} für Alexa exportieren`);
      const text = document.createElement("label");
      text.className = "simple-entity-identity";
      text.htmlFor = `export-${String(entity.entity_id || "").replace(/[^a-zA-Z0-9_-]/g, "-")}`;
      checkbox.id = text.htmlFor;
      text.textContent = `${entity.name || entity.entity_id} (${entity.entity_id})`;
      const nameField = document.createElement("div");
      nameField.className = "simple-alexa-name";
      const nameCaption = document.createElement("label");
      nameCaption.textContent = "Name bei Alexa";
      const nameInput = document.createElement("input");
      nameInput.className = "export-name";
      nameInput.dataset.entity = String(entity.entity_id || "");
      nameInput.id = `alexa-name-${String(entity.entity_id || "").replace(/[^a-zA-Z0-9_-]/g, "-")}`;
      nameCaption.htmlFor = nameInput.id;
      nameInput.value = String(settings.name || entity.export?.name || "");
      nameInput.placeholder = suggestedName(entity, device);
      nameInput.disabled = !isEditing;
      nameInput.setAttribute("aria-label", `Alexa-Name für ${entity.name || entity.entity_id}`);
      const suggestion = document.createElement("button");
      suggestion.type = "button";
      suggestion.className = "button secondary small simple-name-suggestion";
      suggestion.dataset.action = "suggest-simple-name";
      suggestion.dataset.entity = String(entity.entity_id || "");
      suggestion.dataset.suggestion = suggestedName(entity, device);
      suggestion.textContent = "Vorschlag";
      suggestion.disabled = !isEditing;
      nameField.append(nameCaption, nameInput, suggestion);
      entityRow.append(checkbox, text, nameField);
      list.append(entityRow);
    }
    row.append(list);
  }

  function alexaOnlyHtml(item) {
    const key = attr(item.key);
    return `<article class="alexa-card ${item.status === "orphaned" ? "orphaned" : ""} ${item.hidden ? "hidden-item" : ""}"><label class="alexa-select"><input type="checkbox" data-alexa-select="${key}" aria-label="${attr(item.name)} zur Lösch-Auswahl hinzufügen" ${selectedAlexaKeys.has(item.key) ? "checked" : ""}> Auswählen</label><div class="alexa-name">${esc(item.name)}</div><div class="badges">${statusBadge(item.status)}${item.hidden ? '<span class="badge hidden-badge">ausgeblendet</span>' : ""}</div><div class="alexa-meta">${esc(item.source)}${item.family ? ` • ${esc(item.family)}` : ""}${item.skill ? ` • ${esc(item.skill)}` : ""}<br>${esc(item.serial)}${item.groups?.length ? `<br>Gruppen: ${esc(item.groups.join(", "))}` : ""}</div><div class="alexa-actions"><button class="button secondary small" data-action="details-alexa" data-key="${key}">Weitere Infos</button><button class="button secondary small" data-action="${item.hidden ? "show-alexa" : "hide-alexa"}" data-key="${key}">${item.hidden ? "Einblenden" : "Ausblenden"}</button><button class="button secondary small" data-action="rename-alexa" data-key="${key}">Umbenennen</button><button class="button danger small" data-action="delete-alexa" data-key="${key}">Löschen</button></div></article>`;
  }

  function updateAlexaSelectionUi(visibleItems) {
    const label = document.getElementById("alexa-selection-count");
    const deleteButton = document.getElementById("btn-delete-selected-alexa");
    const selectVisible = document.getElementById("select-visible-alexa");
    if (!label || !deleteButton || !selectVisible) return;
    label.textContent = `${selectedAlexaKeys.size} ausgewählt`;
    deleteButton.disabled = selectedAlexaKeys.size === 0;
    selectVisible.checked = visibleItems.length > 0 && visibleItems.every(item => selectedAlexaKeys.has(item.key));
    selectVisible.indeterminate = visibleItems.some(item => selectedAlexaKeys.has(item.key)) && !selectVisible.checked;
  }

  async function pollAlexaDeleteJob() {
    try {
      const job = await request("/api/devices/delete-job");
      if (job.running) {
        message(`Löschvorgang läuft: ${job.done || 0}/${job.total || 0}${job.current ? ` — ${job.current}` : ""}`, "warn");
        alexaDeletePollTimer = setTimeout(pollAlexaDeleteJob, 1500);
        return;
      }
      clearTimeout(alexaDeletePollTimer);
      alexaDeletePollTimer = null;
      const deletedSerials = new Set((job.deleted || []).map(item => item.serial));
      for (const item of model?.alexa_only || []) if (deletedSerials.has(item.serial)) selectedAlexaKeys.delete(item.key);
      const failures = job.failed || [];
      await load(false);
      message(
        failures.length
          ? `${job.ok || 0} Gerät(e) gelöscht; ${failures.length} konnten nicht gelöscht werden. Fehlgeschlagene Geräte bleiben in der Auswahl.`
          : `${job.ok || 0} Gerät(e) aus Alexa gelöscht${job.aborted ? " (abgebrochen)" : ""}.`,
        failures.length ? "err" : "ok"
      );
      render();
    } catch (error) {
      clearTimeout(alexaDeletePollTimer);
      alexaDeletePollTimer = null;
      message(`Fortschritt des Löschvorgangs konnte nicht gelesen werden: ${error.message}`, "err");
    }
  }

  async function deleteSelectedAlexa() {
    const targets = (model?.alexa_only || []).filter(item => selectedAlexaKeys.has(item.key));
    if (!targets.length) return message("Bitte zuerst Alexa-Geräte auswählen.", "warn");
    const names = targets.slice(0, 12).map(item => `• ${item.name}`).join("\n");
    const more = targets.length > 12 ? `\n• … und ${targets.length - 12} weitere` : "";
    if (!confirm(`${targets.length} ausgewählte Gerät(e) dauerhaft aus Alexa löschen?\n\n${names}${more}\n\nDiese Aktion kann nicht rückgängig gemacht werden.`)) return;
    const button = document.getElementById("btn-delete-selected-alexa");
    setBusy(button, true, "Löschauftrag…");
    try {
      await request("/api/devices/delete-job", {
        method: "POST",
        body: JSON.stringify({devices: targets.map(item => ({
          serial: item.serial,
          source: item.source,
          appliance_id: item.appliance_id || "",
          name: item.name
        }))})
      });
      message(`Löschauftrag für ${targets.length} Gerät(e) gestartet.`, "warn");
      await pollAlexaDeleteJob();
    } catch (error) {
      message(`Löschauftrag konnte nicht gestartet werden: ${error.message}`, "err");
    } finally {
      setBusy(button, false);
    }
  }

  function entityLocation(entityId) {
    for (const device of model?.devices || []) {
      const entity = (device.entities || []).find(item => item.entity_id === entityId);
      if (entity) return {device, entity};
    }
    return null;
  }

  function renderVirtualGroups() {
    const section = document.getElementById("virtual-groups-section");
    const container = document.getElementById("virtual-group-list");
    if (!section || !container) return;
    const groups = new Map((config?.virtual_groups || []).map(group => [group.group_id, group]));
    for (const [groupId, draft] of pendingVirtualGroups) {
      if (draft === null) groups.delete(groupId);
      else groups.set(groupId, {
        group_id: groupId, name: draft.name || "Unbenanntes Alexa-Gesamtgerät",
        members: draft.entity_ids || [], pending: true, complete: draft.complete !== false,
      });
    }
    section.classList.toggle("hidden", groups.size === 0);
    container.innerHTML = [...groups.values()].map(group => {
      const memberNames = (group.members || []).map(entityId => {
        const location = entityLocation(entityId);
        const capName = group.capabilities?.find(cap => cap.entity_id === entityId)?.capability_names?.[0];
        return group.member_names?.[entityId] || capName || location?.entity.name || entityId;
      });
      const places = new Set((group.members || []).map(entityId => entityLocation(entityId)?.device?.name).filter(Boolean));
      const summary = `${group.members?.length || 0} Entity${group.members?.length === 1 ? "" : "s"} aus ${places.size || "unbekannten"} HA-Gerät${places.size === 1 ? "" : "en"}${memberNames.length ? ` · ${memberNames.slice(0, 4).join(", ")}${memberNames.length > 4 ? `, +${memberNames.length - 4}` : ""}` : ""}`;
      const draftLabel = group.pending ? (group.complete ? " · ungespeichert" : " · offener Entwurf") : "";
      const actions = globalEditMode
        ? `<button class="button secondary small" data-virtual-action="edit" data-group-id="${attr(group.group_id)}">${group.complete === false ? "Entwurf öffnen" : "Gruppe öffnen"}</button><button class="button danger small" data-virtual-action="remove" data-group-id="${attr(group.group_id)}">In Entwurf auflösen</button>`
        : "";
      return `<article class="virtual-group-card"><div><strong>${esc(group.name)}${esc(draftLabel)}</strong><span class="muted">${esc(summary)}</span></div><div class="device-actions">${actions}</div></article>`;
    }).join("");
  }

  function renderVirtualGroupEntities(spec) {
    const container = document.getElementById("virtual-group-entities");
    if (!container) return;
    const selected = new Set(spec.entity_ids || []);
    const memberNames = spec.names || {};
    const profiles = spec.profiles || {};
    const existing = (config?.virtual_groups || []).find(group => group.group_id === spec.group_id);
    const rows = [];
    for (const device of model?.devices || []) {
      for (const entity of device.entities || []) {
        const keepExisting = existing?.members?.includes(entity.entity_id) || selected.has(entity.entity_id);
        const options = virtualProfileOptions(entity, keepExisting);
        if (!options.length) continue;
        let profile = profiles[entity.entity_id];
        if (!profile) {
          profile = keepExisting ? {mode: "preserve"}
            : capabilityOptions(entity).length ? {mode: "standard"} : {mode: "read_only_range"};
        }
        const supportedModes = new Set(options.map(option => option.id));
        if (!supportedModes.has(profile.mode)) profile = {mode: options[0].id};
        const defaultName = existing?.capabilities?.find(cap => cap.entity_id === entity.entity_id)?.capability_names?.[0]
          || entityConfig(entity.entity_id).name || entity.name || entity.entity_id;
        const name = memberNames[entity.entity_id] || defaultName;
        const unit = profile.unit || defaultAlexaRangeUnit(entity);
        const percent = unit === "Alexa.Unit.Percent";
        const minimum = profile.minimum ?? entity.minimum ?? 0;
        const maximum = profile.maximum ?? entity.maximum ?? (percent ? 100 : 10000);
        const precision = profile.precision ?? entity.step ?? 1;
        const profileOptions = options.map(option => `<option value="${attr(option.id)}" ${profile.mode === option.id ? "selected" : ""}>${esc(option.label)}</option>`).join("");
        const numericSettings = canUseReadOnlyRange(entity) ? `<div data-vrange-fields class="${profile.mode === "read_only_range" ? "" : "hidden"}"><div class="virtual-range-fields">
          <label>Alexa-Einheit<input data-vrange-unit value="${attr(unit)}" placeholder="Alexa.Unit.Liters"></label>
          <label>Funktionskennung<input data-vrange-instance value="${attr(profile.instance || ("value_" + entity.entity_id.split(".").pop().replace(/[^A-Za-z0-9_]/g, "_")))}" maxlength="64"></label>
          <label>Minimum<input type="number" data-vrange-min value="${attr(minimum)}" step="any"></label>
          <label>Maximum<input type="number" data-vrange-max value="${attr(maximum)}" step="any"></label>
          <label>Schrittweite / Präzision<input type="number" data-vrange-precision value="${attr(precision)}" min="0.000001" step="any"></label>
          <span class="virtual-range-help">Nur lesender Alexa-RangeController. Die Einheit muss zum HA-Wert passen; Prozent und Liter werden automatisch vorgeschlagen.</span>
        </div></div>` : profile.mode === "preserve"
          ? '<span class="virtual-range-help">Die gespeicherte Alexa-Funktion und Einheit bleiben unverändert.</span>' : "";
        const deviceName = device.name || device.device_id || "HA-Gerät";
        const place = [device.area_name, deviceName].filter(Boolean).join(" · ");
        rows.push(`<article class="virtual-group-entity" data-virtual-entity-row="${attr(entity.entity_id)}">
          <label class="virtual-group-identity"><input type="checkbox" data-vgroup-entity="${attr(entity.entity_id)}" ${selected.has(entity.entity_id) ? "checked" : ""}>
            <span><strong>${esc(entity.name || entity.entity_id)}</strong><small>${esc(entity.entity_id)} · ${esc(place)}${entity.unit_of_measurement ? ` · ${esc(entity.unit_of_measurement)}` : ""}</small></span></label>
          <div class="virtual-member-settings"><label class="virtual-member-name">Name dieser Funktion<input data-vgroup-name="${attr(entity.entity_id)}" value="${attr(name)}" maxlength="128"></label>
            <select class="virtual-profile-select" data-vgroup-profile="${attr(entity.entity_id)}" aria-label="Alexa-Funktion für ${attr(entity.name || entity.entity_id)}">${profileOptions}</select>${numericSettings}</div>
        </article>`);
      }
    }
    container.innerHTML = rows.length ? rows.join("") : '<div class="empty">Keine unterstützten oder numerischen Entities gefunden.</div>';
    filterVirtualGroupEntities();
  }

  function filterVirtualGroupEntities() {
    const query = document.getElementById("virtual-group-search")?.value.trim().toLocaleLowerCase() || "";
    for (const row of document.querySelectorAll("[data-virtual-entity-row]")) {
      row.classList.toggle("hidden", Boolean(query && !row.textContent.toLocaleLowerCase().includes(query)));
    }
  }

  function virtualGroupDialogSpec(complete = false) {
    const dialog = document.getElementById("virtual-group-dialog");
    const entityIds = [...dialog.querySelectorAll("input[data-vgroup-entity]:checked")].map(input => input.dataset.vgroupEntity);
    const names = {};
    const profiles = {};
    for (const entityId of entityIds) {
      names[entityId] = String(dialog.querySelector(`input[data-vgroup-name="${CSS.escape(entityId)}"]`)?.value || "").trim();
      const mode = dialog.querySelector(`select[data-vgroup-profile="${CSS.escape(entityId)}"]`)?.value || "standard";
      if (mode === "read_only_range") {
        profiles[entityId] = {
          mode,
          unit: String(dialog.querySelector(`[data-vgroup-entity="${CSS.escape(entityId)}"]`)?.closest(".virtual-group-entity")?.querySelector("[data-vrange-unit]")?.value || "").trim(),
          instance: String(dialog.querySelector(`[data-vgroup-entity="${CSS.escape(entityId)}"]`)?.closest(".virtual-group-entity")?.querySelector("[data-vrange-instance]")?.value || "").trim(),
          minimum: Number(dialog.querySelector(`[data-vgroup-entity="${CSS.escape(entityId)}"]`)?.closest(".virtual-group-entity")?.querySelector("[data-vrange-min]")?.value),
          maximum: Number(dialog.querySelector(`[data-vgroup-entity="${CSS.escape(entityId)}"]`)?.closest(".virtual-group-entity")?.querySelector("[data-vrange-max]")?.value),
          precision: Number(dialog.querySelector(`[data-vgroup-entity="${CSS.escape(entityId)}"]`)?.closest(".virtual-group-entity")?.querySelector("[data-vrange-precision]")?.value),
        };
      } else profiles[entityId] = {mode};
    }
    return {
      group_id: dialog.dataset.groupId,
      name: String(document.getElementById("virtual-group-name").value || "").trim(),
      entity_ids: entityIds,
      names,
      profiles,
      display_category: "OTHER",
      complete,
    };
  }

  function persistVirtualGroupDialog(complete = false) {
    if (!activeVirtualGroupId) return null;
    const spec = virtualGroupDialogSpec(complete);
    pendingVirtualGroups.set(activeVirtualGroupId, spec);
    persistEditDraft();
    updateVirtualGroupPreview(spec);
    renderVirtualGroups();
    return spec;
  }

  function updateVirtualGroupPreview(spec = virtualGroupDialogSpec(false)) {
    const preview = document.getElementById("virtual-group-preview");
    if (!preview) return;
    if (!spec.entity_ids.length) {
      preview.textContent = "Wähle mindestens eine Entity. Unterstützte Funktionen werden automatisch vorgeschlagen; Zahlenwerte lassen sich als lesende Slider hinzufügen.";
      return;
    }
    const lines = spec.entity_ids.map(entityId => {
      const location = entityLocation(entityId);
      const entity = location?.entity;
      if (!entity) return `• ${spec.names[entityId] || entityId}: nicht mehr in HA gefunden`;
      const labels = virtualCapabilityLabels(entity, spec.profiles[entityId]);
      const label = labels.join(" + ") || "keine Alexa-Funktion";
      const profile = spec.profiles[entityId];
      const bounds = profile?.mode === "read_only_range" ? ` (${profile.minimum}–${profile.maximum} ${profile.unit || "Einheit fehlt"})` : "";
      return `• ${spec.names[entityId] || entity.name || entityId}: ${label}${bounds}`;
    });
    preview.textContent = `1 Alexa-Gesamtgerät „${spec.name || "Name festlegen"}“ mit ${spec.entity_ids.length} Entity(s)\n${lines.join("\n")}`;
  }

  function openVirtualGroupDialog(groupId = null) {
    if (!globalEditMode) return message("Bitte zuerst den zentralen Bearbeitungsmodus starten.", "warn");
    const existing = groupId ? (config?.virtual_groups || []).find(group => group.group_id === groupId) : null;
    let spec = groupId ? pendingVirtualGroups.get(groupId) : null;
    if (spec === null) return message("Diese Gruppe ist bereits zur Auflösung vorgemerkt.", "warn");
    if (!spec && existing) {
      spec = {group_id: groupId, name: existing.name, entity_ids: [...(existing.members || [])],
        names: {}, profiles: Object.fromEntries((existing.members || []).map(entityId => [entityId, {mode: "preserve"}])),
        display_category: existing.display_category || "OTHER", complete: false};
      for (const entityId of spec.entity_ids) {
        spec.names[entityId] = existing.member_names?.[entityId]
          || existing.capabilities?.find(cap => cap.entity_id === entityId)?.capability_names?.[0]
          || entityLocation(entityId)?.entity?.name || entityId;
      }
    }
    if (!spec) {
      const randomId = window.crypto?.randomUUID?.().replace(/-/g, "") || `${Date.now()}${Math.random().toString(36).slice(2)}`;
      spec = {group_id: `virtual:${randomId}`, name: "", entity_ids: [], names: {}, profiles: {}, display_category: "OTHER", complete: false};
    }
    activeVirtualGroupId = spec.group_id;
    document.getElementById("virtual-group-title").textContent = existing ? `Alexa-Gesamtgerät bearbeiten: ${existing.name}` : "Virtuelles Alexa-Gesamtgerät erstellen";
    document.getElementById("virtual-group-name").value = spec.name || "";
    document.getElementById("virtual-group-search").value = "";
    document.getElementById("virtual-group-dialog").dataset.groupId = spec.group_id;
    pendingVirtualGroups.set(spec.group_id, {...spec, complete: false});
    renderVirtualGroupEntities(spec);
    updateVirtualGroupPreview(spec);
    document.getElementById("virtual-group-dialog").showModal();
    persistEditDraft();
  }

  function stageVirtualGroupFromDialog() {
    const spec = virtualGroupDialogSpec(true);
    if (!spec.entity_ids.length) return message("Wähle mindestens eine Entity für das Alexa-Gesamtgerät.", "warn");
    if (!spec.name || spec.name.length > 128) return message("Der Name muss 1 bis 128 Zeichen enthalten.", "warn");
    for (const entityId of spec.entity_ids) {
      const profile = spec.profiles[entityId];
      if (!spec.names[entityId]) return message(`Bitte einen Funktionsnamen für ${entityId} angeben.`, "warn");
      if (profile.mode === "read_only_range"
          && (!profile.unit || !profile.instance || !Number.isFinite(profile.minimum)
            || !Number.isFinite(profile.maximum) || !Number.isFinite(profile.precision)
            || profile.minimum >= profile.maximum || profile.precision <= 0)) {
        return message(`Bitte Einheit, Funktionskennung und gültigen Wertebereich für ${entityId} ergänzen.`, "warn");
      }
    }
    spec.complete = true;
    pendingVirtualGroups.set(spec.group_id, spec);
    activeVirtualGroupId = null;
    document.getElementById("virtual-group-dialog").close();
    persistEditDraft();
    renderVirtualGroups();
    updateSyncEditStatus();
    message(`„${spec.name}“ ist im zentralen Entwurf vorgemerkt und wird erst mit „Fertig – alles speichern“ angelegt.`, "warn");
  }

  function stageVirtualGroupRemoval(groupId) {
    if (!globalEditMode) return;
    const persisted = (config?.virtual_groups || []).some(group => group.group_id === groupId);
    if (persisted) pendingVirtualGroups.set(groupId, null);
    else pendingVirtualGroups.delete(groupId);
    if (activeVirtualGroupId === groupId) activeVirtualGroupId = null;
    persistEditDraft();
    renderVirtualGroups();
    message(persisted
      ? "Das virtuelle Alexa-Gerät wird beim zentralen Speichern aufgelöst; seine Entities bleiben als einzelne Endpunkte erhalten."
      : "Der neue Alexa-Gruppenentwurf wurde aus der Liste entfernt; es wurde noch nichts gespeichert.", "warn");
  }

  function render() {
    if (!model) return;
    renderSummary(); renderFilters();
    const filter = filters();
    const groups = new Map();
    for (const device of model.devices || []) {
      const entities = (device.entities || []).filter(entity => entityMatchesFilter(entity, device, filter));
      if (!entities.length) continue;
      const area = device.area_name || "Ohne Bereich";
      if (!groups.has(area)) groups.set(area, []);
      groups.get(area).push({device, entities});
    }
    const html = [];
    renderedAreaItems.clear();
    if (filter.status !== "alexa_only") {
      for (const [area, items] of [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0], "de"))) {
        const areaKey = items[0]?.device?.area_id || area;
        renderedAreaItems.set(areaKey, items);
        const expanded = expandedAreas.has(areaKey);
        html.push(`<section class="area"><div class="area-title"><button class="collapse-toggle" data-action="toggle-area" data-area="${attr(areaKey)}" aria-expanded="${expanded}">${expanded ? "▾" : "▸"}</button><h2>${esc(area)}</h2><span class="muted">${items.length} Geräte</span></div>`);
        html.push('<div class="area-devices">');
        html.push("</div></section>");
      }
    }
    const alexaOnly = (model.alexa_only || []).filter(item => alexaOnlyMatchesFilter(item, filter));
    if (alexaOnly.length) {
      html.push('<h2 class="alexa-only-title">Alexa-Geräte ohne Home-Assistant-Zuordnung</h2>');
      html.push('<div class="alexa-selection-toolbar"><label><input id="select-visible-alexa" type="checkbox"> Alle sichtbaren auswählen</label><span id="alexa-selection-count">0 ausgewählt</span><button id="btn-delete-selected-alexa" class="button danger" data-action="delete-selected-alexa" disabled>Ausgewählte löschen</button></div>');
      html.push('<div class="alexa-only-grid">');
      html.push(...alexaOnly.map(alexaOnlyHtml)); html.push("</div>");
    }
    document.getElementById("content").innerHTML = html.length ? html.join("") : '<div class="empty">Keine Geräte entsprechen dem aktuellen Filter.</div>';
    for (const areaKey of expandedAreas) {
      const button = document.querySelector(`button[data-action="toggle-area"][data-area="${CSS.escape(areaKey)}"]`);
      if (button) renderArea(button, areaKey);
    }
    document.getElementById("btn-login").classList.toggle("hidden", model.alexa_connected);
    document.getElementById("btn-logout").classList.toggle("hidden", !model.alexa_connected);
    document.getElementById("v5-disabled").classList.toggle("hidden", config.native_enabled);
    updateAlexaSelectionUi(alexaOnly);
    renderVirtualGroups();
    updateSyncEditStatus();
    if (globalEditMode || pendingGlobalEdit) persistEditDraft();
  }

  async function load(force = false) {
    if (hasEditorSession()) {
      return;
    }
    const button = document.getElementById("btn-refresh");
    if (force) {
      clearTimeout(overviewPollTimer);
      overviewPollCount = 0;
      setBusy(button, true, "Lade…");
    }
    clearMessage();
    try {
      model = await request(`/api/device-overview${force ? "?refresh=1" : ""}`);
      if (!model || !model.configuration || typeof model.configuration.native_enabled !== "boolean") {
        throw new Error("Die Geräteübersicht-API liefert keine v6-Konfiguration. Add-on und Oberfläche haben unterschiedliche Versionen; Add-on aktualisieren und Seite neu laden.");
      }
      config = model.configuration;
      if (!globalEditMode && !pendingGlobalEdit && restoreEditDraft()) {
        updateSyncEditStatus();
        try {
          await acquireSyncPause();
          pendingGlobalEdit = false;
          globalEditMode = true;
          syncEntityModelFromConfig();
          message("Offener Entwurf und geöffnete Listen wurden wiederhergestellt. Der Alexa-Abgleich ist pausiert.", "warn");
        } catch (error) {
          pendingGlobalEdit = false;
          globalEditMode = false;
          message(`Der Entwurf ist erhalten, aber der Alexa-Abgleich konnte nicht pausiert werden. Klicke „Entwurf fortsetzen“ und versuche es erneut: ${error.message}`, "err");
        }
      }
      const availableAlexaKeys = new Set((model.alexa_only || []).map(item => item.key));
      for (const key of selectedAlexaKeys) if (!availableAlexaKeys.has(key)) selectedAlexaKeys.delete(key);
      render();
      if (draftRestoreScrollY !== null) {
        const scrollY = draftRestoreScrollY;
        draftRestoreScrollY = null;
        requestAnimationFrame(() => window.scrollTo(0, scrollY));
      }
      if (globalEditMode && draftRestoreActiveVirtualGroupId) {
        const groupId = draftRestoreActiveVirtualGroupId;
        draftRestoreActiveVirtualGroupId = null;
        requestAnimationFrame(() => openVirtualGroupDialog(groupId));
      }
      if (model.source_cache_loading || model.source_cache_refreshing) {
        if (overviewPollCount < 40) {
          overviewPollCount += 1;
          message(
            model.source_cache_loading
              ? "Geräteliste wird im Hintergrund geladen. Diese Ansicht aktualisiert sich automatisch."
              : "Der Cache wird im Hintergrund aktualisiert. Diese Ansicht übernimmt die neuen Daten automatisch.",
            "warn"
          );
          overviewPollTimer = setTimeout(() => load(false), 2000);
        } else {
          message("Der Hintergrundabruf dauert ungewöhnlich lange. Prüfe die Alexa-Verbindung oder nutze „Aktualisieren“.", "warn");
        }
      } else {
        clearTimeout(overviewPollTimer);
        overviewPollCount = 0;
        if (model.warnings?.length) message(model.warnings.join("\n"), "warn");
      }
    } catch (error) {
      clearTimeout(overviewPollTimer);
      document.getElementById("content").innerHTML = `<div class="empty">${esc(error.message)}</div>`;
      message(`Geräteübersicht konnte nicht geladen werden: ${error.message}`, "err");
    } finally {
      if (force) setBusy(button, false);
    }
  }

  function applyVisibilityLocally(kind, ids, hidden) {
    const wanted = new Set(Array.isArray(ids) ? ids : [ids]);
    config.ui ||= {};
    const key = kind === "device" ? "hidden_devices" : kind === "entity" ? "hidden_entities" : "hidden_alexa";
    const current = new Set(config.ui[key] || []);
    for (const id of wanted) hidden ? current.add(id) : current.delete(id);
    config.ui[key] = [...current].sort();
    if (kind === "device") for (const device of model.devices || []) if (wanted.has(device.device_id)) { device.hidden = hidden; for (const entity of device.entities || []) entity.hidden = hidden || entity.hidden_directly; }
    if (kind === "entity") for (const device of model.devices || []) for (const entity of device.entities || []) if (wanted.has(entity.entity_id)) { entity.hidden_directly = hidden; entity.hidden = hidden || device.hidden; }
    if (kind === "alexa") for (const item of model.alexa_only || []) if (wanted.has(item.key)) item.hidden = hidden;
  }

  async function changeVisibility(kind, ids, hidden) {
    const values = Array.isArray(ids) ? ids : [ids];
    applyVisibilityLocally(kind, values, hidden);
    render();
    try {
      const result = await request("/api/device-overview/visibility", {method: "POST", body: JSON.stringify({kind, ids: values, hidden})});
      if (result.configuration?.ui) config.ui = result.configuration.ui;
    } catch (error) {
      applyVisibilityLocally(kind, values, !hidden);
      render();
      throw error;
    }
  }

  async function renameAlexa(key) {
    const item = findAlexa(key); if (!item) return;
    const newName = prompt("Neuer Alexa-Name:", item.name);
    if (!newName || newName.trim() === item.name) return;
    const result = await request("/api/devices/rename", {method: "POST", body: JSON.stringify({devices: [{serial: item.serial, source: item.source, appliance_id: item.appliance_id, device_type: item.device_type, name: item.name, new_name: newName.trim()}]})});
    const failed = (result.results || []).find(entry => !entry.ok);
    if (failed) throw new Error(failed.error || "Umbenennen fehlgeschlagen");
    message(`„${item.name}“ wurde in „${newName.trim()}“ umbenannt.`); await load(true);
  }

  async function showAlexaDetails(key) {
    const item = findAlexa(key);
    if (!item) throw new Error("Alexa-Gerät nicht mehr in der aktuellen Übersicht.");
    const dialog = document.getElementById("alexa-details-dialog");
    const output = document.getElementById("alexa-details-json");
    const status = document.getElementById("alexa-details-status");
    const connectedVia = document.getElementById("alexa-details-connected-via");
    const description = document.getElementById("alexa-details-description");
    const model = document.getElementById("alexa-details-model");
    const type = document.getElementById("alexa-details-type");
    document.getElementById("alexa-details-title").textContent = `Weitere Infos: ${item.name}`;
    status.textContent = "Frage erweiterte Gerätedetails aktuell bei Alexa ab…";
    connectedVia.textContent = "Wird abgefragt…";
    description.textContent = "—";
    model.textContent = "—";
    type.textContent = "—";
    output.value = "";
    if (!dialog.open) dialog.showModal();
    try {
      const details = await request("/api/device-overview/alexa-details", {
        method: "POST", body: JSON.stringify({key})
      });
      const api = details.alexa_api || {};
      const live = api.device || {};
      const timestamp = api.fetched_at
        ? new Date(api.fetched_at * 1000).toLocaleString()
        : null;
      if (api.status === "matched") {
        connectedVia.textContent = live.connected_via || "Von Alexa nicht angegeben";
        description.textContent = live.description || "Von Alexa nicht angegeben";
        model.textContent = [live.manufacturer, live.model].filter(Boolean).join(" · ") || "Von Alexa nicht angegeben";
        const deviceTypes = Array.isArray(live.device_types) ? live.device_types : [];
        type.textContent = [live.custom_device_type, ...deviceTypes].filter(Boolean).join(" · ") || "Von Alexa nicht angegeben";
        status.textContent = `Erweiterte Daten direkt von Alexa • ${timestamp || "Zeitpunkt unbekannt"}${live.connected_via_source ? ` • Quelle „Verbunden über“: ${live.connected_via_source}` : ""}`;
      } else if (api.status === "not_found") {
        connectedVia.textContent = "Gerät in der aktuellen Alexa-Abfrage nicht gefunden";
        status.textContent = "Alexa hat für dieses Gerät keinen passenden Datensatz zurückgegeben. Angezeigt werden zusätzlich die Daten des letzten Bestandsabrufs.";
      } else {
        connectedVia.textContent = "Alexa hat keine Angabe geliefert";
        status.textContent = `${api.error || "Erweiterte Alexa-Daten konnten nicht geladen werden."} Die Daten des letzten Bestandsabrufs bleiben unten verfügbar.`;
      }
      output.value = JSON.stringify({alexa_api: api, letzter_bestandsabruf: details.device}, null, 2);
      const inventoryTimestamp = details.cache_updated_at
        ? new Date(details.cache_updated_at * 1000).toLocaleString()
        : "Zeitpunkt unbekannt";
      status.textContent += ` • Bestandsabruf: ${inventoryTimestamp}${details.warning_sources?.length ? ` • Warnungen: ${details.warning_sources.join(", ")}` : ""}`;
    } catch (error) {
      status.textContent = `Gerätedetails konnten nicht geladen werden: ${error.message}`;
      output.value = "";
    }
  }

  async function deleteAlexa(key) {
    const item = findAlexa(key); if (!item) return;
    if (!confirm(`Alexa-Gerät „${item.name}“ wirklich löschen?`)) return;
    const result = await request("/api/devices/delete", {method: "POST", body: JSON.stringify({devices: [{serial: item.serial, source: item.source, appliance_id: item.appliance_id, name: item.name}]})});
    const failed = (result.results || []).find(entry => !entry.ok);
    if (failed) throw new Error(failed.error || "Löschen fehlgeschlagen");
    message(`„${item.name}“ wurde aus Alexa entfernt.`); await load(true);
  }

  async function assignGroup(entityId, key) {
    const item = findAlexa(key);
    const groupName = entityConfig(entityId).alexa_group?.trim();
    if (!item || !groupName) throw new Error("Alexa-Gruppe fehlt.");
    const settings = config.group_sync || {};
    await request("/api/alexa-groups/assign", {method: "POST", body: JSON.stringify({device_id: item.appliance_id || item.serial, group_name: groupName, create_missing: settings.create_missing !== false, remove_from_other_groups: Boolean(settings.remove_from_other_groups)})});
    message(`„${item.name}“ wurde der Alexa-Gruppe „${groupName}“ zugeordnet.`); await load(true);
  }

  async function autoExportDevices(deviceIds, button = null) {
    if (!deviceIds.length) return message("Keine sichtbaren Home-Assistant-Geräte zum Exportieren gefunden.", "warn");
    if (!globalEditMode) await startGlobalEditMode();
    if (!globalEditMode) return;
    for (const deviceId of deviceIds) stagedAutoGroupDeviceIds.add(String(deviceId));
    persistEditDraft();
    updateSyncEditStatus();
    message(`${deviceIds.length} Gerät${deviceIds.length === 1 ? "" : "e"} für das automatische Standardprofil vorgemerkt. „Fertig“ speichert sie zusammen mit dem restlichen Entwurf.`, "warn");
  }

  async function prepareDevice(deviceId, button = null) {
    const device = (model.devices || []).find(item => item.device_id === deviceId);
    if (!device) return;
    await autoExportDevices([deviceId], button);
  }

  async function disableDeviceExport(deviceId) {
    const device = (model.devices || []).find(item => item.device_id === deviceId); if (!device) return;
    for (const entity of device.entities) { entityConfig(entity.entity_id).enabled = false; entity.export.enabled = false; }
    await saveConfig(); await load(false); message(`v6-Export für „${device.name}“ deaktiviert. Der Alexa-Abgleich entfernt bisher veröffentlichte Endpunkte.`, "warn");
  }

  function renderSimpleDeviceRowFrom(button) {
    const section = button.closest("section.area");
    const areaToggle = section?.querySelector('button[data-action="toggle-area"]');
    if (areaToggle) renderArea(areaToggle, areaToggle.dataset.area);
  }

  function toggleSimpleDevice(button, deviceId) {
    if (expandedSimpleDevices.has(deviceId)) expandedSimpleDevices.delete(deviceId);
    else expandedSimpleDevices.add(deviceId);
    renderSimpleDeviceRowFrom(button);
    scheduleEditDraftPersistence();
  }

  function expandVisibleDeviceLists() {
    for (const [areaKey, items] of renderedAreaItems) {
      const visibleCount = Math.min(visibleAreaCounts.get(areaKey) || AREA_PAGE_SIZE, items.length);
      expandedAreas.add(areaKey);
      visibleAreaCounts.set(areaKey, visibleCount);
      for (const {device} of items.slice(0, visibleCount)) expandedSimpleDevices.add(String(device.device_id));
    }
  }

  async function startGlobalEditMode() {
    if (globalEditMode || pendingGlobalEdit) return;
    const resumeSavedDraft = hasSavedEditDraft();
    if (resumeSavedDraft) {
      if (!restoreEditDraft()) throw new Error("Der gespeicherte Entwurf konnte nicht gelesen werden.");
    } else {
      editBaseEntities = {revision: config.native_revision, entities: JSON.parse(JSON.stringify(config.entities || {}))};
      pendingGlobalEdit = true;
      editPauseClientId();
    }
    clearTimeout(overviewPollTimer);
    updateSyncEditStatus();
    persistEditDraft();
    try {
      await acquireSyncPause();
      pendingGlobalEdit = false;
      globalEditMode = true;
      if (!resumeSavedDraft) expandVisibleDeviceLists();
      syncEntityModelFromConfig();
      persistEditDraft();
      updateSyncEditStatus();
      render();
    } catch (error) {
      pendingGlobalEdit = false;
      globalEditMode = false;
      updateSyncEditStatus();
      render();
      message(`Bearbeitungsmodus konnte nicht gestartet werden. Der Entwurf bleibt erhalten: ${error.message}`, "err");
    }
  }

  async function finishGlobalEditMode(button) {
    if (!globalEditMode) return;
    if (activeVirtualGroupId || [...pendingVirtualGroups.values()].some(draft => draft && draft.complete === false)) {
      return message("Bitte den offenen Entitäten-Gruppenentwurf zuerst fertigstellen oder schließen und danach erneut öffnen. Der Entwurf bleibt erhalten.", "warn");
    }
    setBusy(button, true, "Speichere alles…");
    try {
      await saveConfig();
      let grouped = null;
      if (stagedAutoGroupDeviceIds.size) {
        grouped = await request("/api/native-export/auto-group", {
          method: "POST",
          body: JSON.stringify({native_revision: config.native_revision, device_ids: [...stagedAutoGroupDeviceIds]}),
        });
        if (grouped.configuration) {
          config = grouped.configuration;
          model.configuration = config;
          syncEntityModelFromConfig();
        }
      }
      let virtualChanges = 0;
      for (const [groupId, draft] of pendingVirtualGroups) {
        const body = draft === null
          ? {native_revision: config.native_revision, group_id: groupId, remove: true}
          : {native_revision: config.native_revision, group_id: groupId, name: draft.name,
             entity_ids: draft.entity_ids, names: draft.names, profiles: draft.profiles,
             display_category: draft.display_category};
        const result = await request("/api/native-export/virtual-group", {
          method: "POST", body: JSON.stringify(body),
        });
        if (result.configuration) {
          config = result.configuration;
          model.configuration = config;
          syncEntityModelFromConfig();
        }
        virtualChanges += 1;
      }
      await releaseSyncPause();
      localStorage.removeItem(EDIT_DRAFT_KEY);
      clearTimeout(draftPersistenceTimer);
      pendingVirtualGroups.clear();
      activeVirtualGroupId = null;
      globalEditMode = false;
      pendingGlobalEdit = false;
      editBaseEntities = null;
      render();
      await load(false);
      const configured = grouped?.configured?.length || 0;
      const skipped = grouped?.skipped?.length || 0;
      message(`Alle Änderungen wurden gemeinsam gespeichert${grouped ? `; ${configured} Standardgerät${configured === 1 ? "" : "e"} eingerichtet${skipped ? `, ${skipped} ausgelassen` : ""}` : ""}${virtualChanges ? `; ${virtualChanges} virtuelles Alexa-Gesamtgerät(er) übernommen` : ""}. Der Alexa-Abgleich läuft weiter.`, skipped ? "warn" : "ok");
    } catch (error) {
      message(`Änderungen konnten nicht vollständig abgeschlossen werden. Der Entwurf bleibt erhalten und kann erneut gespeichert werden: ${error.message}`, "err");
    } finally {
      setBusy(button, false);
      updateSyncEditStatus();
    }
  }

  async function discardGlobalEditDraft() {
    if (!hasSavedEditDraft() && !globalEditMode && !pendingGlobalEdit) return;
    if (!confirm("Den ungespeicherten Alexa-Entwurf verwerfen?")) return;
    try {
      if (syncPauseClientId) await releaseSyncPause();
    } catch (error) {
      message(`Der Alexa-Abgleich konnte nicht freigegeben werden. Der Entwurf bleibt erhalten: ${error.message}`, "err");
      return;
    }
    localStorage.removeItem(EDIT_DRAFT_KEY);
    clearTimeout(draftPersistenceTimer);
    pendingVirtualGroups.clear();
    activeVirtualGroupId = null;
    globalEditMode = false;
    pendingGlobalEdit = false;
    editBaseEntities = null;
    await load(false);
    message("Ungespeicherter Entwurf verworfen.", "warn");
  }

  async function fillEntity(entityId) {
    for (const device of model.devices || []) {
      const entity = device.entities.find(item => item.entity_id === entityId); if (!entity) continue;
      const settings = entityConfig(entityId);
      settings.name = suggestedName(entity, device); settings.display_category = suggestedCategory(entity, device); settings.alexa_group ||= device.area_name || ""; settings.enabled = true;
      await saveConfig(); await load(false); return;
    }
  }

  async function restart() {
    const button = document.getElementById("btn-restart"); setBusy(button, true, "Starte…");
    try { const result = await request("/api/ha-export/restart", {method: "POST", body: "{}"}); message(result.note || "Home Assistant Core wird neu gestartet."); }
    catch (error) { message(`Neustart fehlgeschlagen: ${error.message}`, "err"); }
    finally { setBusy(button, false); }
  }

  async function eventSync() {
    if (hasEditorSession()) return message("Beende zuerst die Gerätebearbeitung, bevor du synchronisierst.", "warn");
    const button = document.getElementById("btn-event-sync"); setBusy(button, true, "Synchronisiere…");
    try {
      // A name edit may still be saving after its input blur. Persist all queued
      // edits before reconciliation reads the native configuration from disk.
      await saveConfig();
      const result = await request("/api/native-export/sync", {method: "POST", body: JSON.stringify({force: true})});
      if (result.queued) {
        const grouped = result.normalized_groups || [];
        const merged = grouped.reduce((total, group) => total + Math.max(0, (group.old_endpoint_count || 0) - (group.endpoint_count || 0)), 0);
        const note = grouped.length
          ? `\n${grouped.length} Gerät${grouped.length === 1 ? "" : "e"} nach Standard gruppiert; ${merged} überzählige Alexa-Endpunkt${merged === 1 ? "" : "e"} werden bereinigt.`
          : "\nKeine bisher ungruppierten Standardgeräte gefunden.";
        message(`${result.message}${note}`, grouped.length ? "warn" : "ok");
        return;
      }
      message(`Alexa Event Gateway erfolgreich.\nUpdates: ${result.official?.add_or_update_count || 0}\nNative Löschungen: ${result.official?.delete_count || 0}\nAlte v5-Geräte gelöscht: ${result.lifecycle?.legacy_deleted || 0}\nVerbleibende v5-Geräte: ${result.lifecycle?.legacy_remaining ?? "ungeprüft"}`); await load(true);
    } catch (error) {
      const fallback = error.body?.fallback;
      message(`Event-Gateway-Abgleich fehlgeschlagen: ${error.message}` + (fallback ? `\nWeb-Fallback entfernt: ${(fallback.deleted_removed || []).length}` : ""), "err");
      await load(false);
    } finally { setBusy(button, false); }
  }

  async function groupSync() {
    if (hasEditorSession()) return message("Beende zuerst die Gerätebearbeitung, bevor du Gruppen synchronisierst.", "warn");
    const button = document.getElementById("btn-group-sync"); setBusy(button, true, "Ordne zu…");
    try {
      await saveConfig();
      const result = await request("/api/ha-export/group-sync", {method: "POST", body: JSON.stringify({configuration: config})});
      message(`Alexa-Gruppen: ${result.successful || 0} erfolgreich, ${result.failed || 0} fehlgeschlagen.`, result.failed ? "warn" : "ok"); await load(true);
    } catch (error) { message(`Gruppenabgleich fehlgeschlagen: ${error.message}`, "err"); }
    finally { setBusy(button, false); }
  }

  function renderDeviceGroupPreview() {
    const dialog = document.getElementById("device-group-dialog");
    const preview = document.getElementById("device-group-preview");
    if (!dialog || !preview) return;
    const mode = dialog.querySelector('input[name="device-group-mode"]:checked')?.value || "combined";
    const selected = [...dialog.querySelectorAll("input[data-group-entity]:checked")];
    const name = document.getElementById("device-group-name").value.trim() || "Home-Assistant-Gerät";
    const controls = selected.flatMap(input => {
      const entityId = input.dataset.groupEntity;
      const device = (model.devices || []).find(item => String(item.device_id) === String(dialog.dataset.deviceId));
      const entity = device?.entities.find(item => item.entity_id === entityId);
      if (!entity) return [];
      const profile = [...dialog.querySelectorAll("select[data-group-profile]")]
        .find(item => item.dataset.groupProfile === entityId)?.value || "standard";
      const functions = profile === "custom"
        ? [...dialog.querySelectorAll("input[data-group-capability]:checked")]
          .filter(item => item.dataset.groupCapability === entityId).map(item => item.value)
        : capabilityOptions(entity).filter(item => item.id !== "Alexa.PlaybackController").map(item => item.id);
      const memberName = [...dialog.querySelectorAll("input[data-group-name]")]
        .find(item => item.dataset.groupName === entityId)?.value.trim()
        || entity.name || entity.entity_id;
      return functions.map(id => {
        const option = capabilityOptions(entity).find(item => item.id === id);
        return {name: memberName, function: option?.label || id};
      });
    });
    if (!controls.length) {
      preview.textContent = "Wähle mindestens eine unterstützte Funktion aus.";
      return;
    }
    const lines = mode === "combined"
      ? [`1 Alexa-Gerät: „${name}“`, ...controls.map(control => `• ${control.name}: ${control.function}`)]
      : [`${selected.length} Alexa-Gerät${selected.length === 1 ? "" : "e"}:`,
         ...[...new Set(controls.map(control => `${control.name}: ${control.function}`)).values()].map(value => `• ${value}`)];
    preview.textContent = lines.join("\n");
  }

  function openDeviceGroup(deviceId) {
    const device = (model.devices || []).find(item => String(item.device_id) === String(deviceId));
    if (!device) throw new Error("Home-Assistant-Gerät wurde nicht gefunden.");
    const entities = device.entities || [];
    const activeIds = entities.filter(entity => entity.export?.enabled).map(entity => entity.entity_id);
    const explicitMode = entities.map(entity => entity.export?.group_mode)
      .find(mode => mode === "combined" || mode === "separate");
    const suggestion = device.grouping_suggestion || {};
    const selectedIds = new Set(explicitMode
      ? activeIds
      : Array.isArray(suggestion.entity_ids) ? suggestion.entity_ids : activeIds);
    const thermostatDefault = !explicitMode && suggestion.entity_ids?.some(id => id.startsWith("climate."))
      && entities.some(entity => entity.domain === "sensor" && entity.device_class === "temperature");
    const combined = explicitMode ? explicitMode === "combined" : suggestion.mode !== "separate";
    const currentGroupName = entities.find(entity => entity.export?.logical_device_name)?.export.logical_device_name;
    document.getElementById("device-group-dialog").dataset.deviceId = String(deviceId);
    document.getElementById("device-group-title").textContent = `Alexa-Gerät konfigurieren: ${device.name}`;
    document.getElementById("device-group-name").value = currentGroupName || suggestion.name || device.name || "";
    document.querySelector('input[name="device-group-mode"][value="combined"]').checked = combined;
    document.querySelector('input[name="device-group-mode"][value="separate"]').checked = !combined;
    document.getElementById("device-group-entities").innerHTML = entities.map(entity => {
      const settings = entityConfig(entity.entity_id);
      const enabled = selectedIds.has(entity.entity_id);
      const label = settings.name || entity.name || entity.entity_id;
      const options = capabilityOptions(entity);
      const profileMode = entity.export?.capability_mode === "custom" ? "custom" : "standard";
      const standard = options.filter(option => option.id !== "Alexa.PlaybackController").map(option => option.id);
      const chosen = profileMode === "custom" ? (entity.export?.capabilities || []) : standard;
      const capabilities = options.length
        ? options.map(option => `<label class="check"><input type="checkbox" data-group-capability="${attr(entity.entity_id)}" value="${attr(option.id)}" ${chosen.includes(option.id) ? "checked" : ""}>${esc(option.label)}</label>`).join("")
        : '<span class="muted">Keine unterstützten Alexa-Funktionen für diese Entität.</span>';
      const customCategory = entity.export?.display_category_mode === "custom";
      const displayCategory = customCategory ? entity.export?.display_category : suggestedCategory(entity, device);
      const relayCategory = entity.domain === "switch"
        ? `<label>Relais-Rolle<select data-group-category="${attr(entity.entity_id)}" data-category-mode="${customCategory ? "custom" : "standard"}">${[["LIGHT", "Lichtschalter"], ["SMARTPLUG", "Steckdose"], ["SWITCH", "Schalter / Heizventil"]].map(([value, text]) => `<option value="${value}" ${displayCategory === value ? "selected" : ""}>${text}</option>`).join("")}</select></label>`
        : "";
      const thermostatHelper = thermostatDefault && entity.domain === "sensor" && entity.device_class === "temperature";
      const note = thermostatHelper
        ? "Standard: Ist- und Wunschtemperatur kommen über das Thermostat. Dieses Sensor-Entity wird daher nicht als weiteres Alexa-Gerät angelegt. Für einen zusätzlichen Sensor bitte auswählen; für ein eigenes Alexa-Gerät oben „einzelne Geräte“ wählen."
        : roleNote(entity);
      return `<div class="device-group-entity"><label class="device-group-selection"><input type="checkbox" data-group-entity="${attr(entity.entity_id)}" ${enabled ? "checked" : ""} ${options.length ? "" : "disabled"}><span><strong>${esc(entity.name || entity.entity_id)}</strong><small>${esc(entity.entity_id)}</small></span></label><div class="device-group-member-name">Alexa-Funktionsname<input data-group-name="${attr(entity.entity_id)}" value="${attr(label)}" maxlength="128" autocomplete="off">${relayCategory}<label>Funktionsprofil<select data-group-profile="${attr(entity.entity_id)}"><option value="standard" ${profileMode === "standard" ? "selected" : ""}>Standard (empfohlen)</option><option value="custom" ${profileMode === "custom" ? "selected" : ""}>Eigene Funktionen</option></select></label><div class="device-group-capabilities ${profileMode === "custom" ? "" : "hidden"}" data-group-capabilities="${attr(entity.entity_id)}">${capabilities}</div>${note ? `<small class="device-group-role-note">${esc(note)}</small>` : ""}</div></div>`;
    }).join("");
    document.getElementById("device-group-name-field").classList.toggle("hidden", !combined);
    renderDeviceGroupPreview();
    document.getElementById("device-group-dialog").showModal();
  }

  async function saveDeviceGroup() {
    const dialog = document.getElementById("device-group-dialog");
    const button = document.getElementById("btn-save-device-group");
    const entityIds = [...dialog.querySelectorAll("input[data-group-entity]:checked")]
      .map(input => input.dataset.groupEntity);
    if (!entityIds.length) return message("Wähle mindestens eine Entität aus.", "warn");
    const mode = dialog.querySelector('input[name="device-group-mode"]:checked')?.value;
    const memberNameInputs = [...dialog.querySelectorAll("input[data-group-name]")];
    const names = Object.fromEntries(entityIds.map(entityId => [entityId,
      String(memberNameInputs.find(input => input.dataset.groupName === entityId)?.value || "").trim()]));
    const profiles = Object.fromEntries(entityIds.map(entityId => {
      const profile = [...dialog.querySelectorAll("select[data-group-profile]")]
        .find(input => input.dataset.groupProfile === entityId)?.value || "standard";
      const capabilities = [...dialog.querySelectorAll("input[data-group-capability]:checked")]
        .filter(input => input.dataset.groupCapability === entityId).map(input => input.value);
      const displayCategory = [...dialog.querySelectorAll("select[data-group-category]")]
        .find(input => input.dataset.groupCategory === entityId)?.value;
      const displayCategoryMode = [...dialog.querySelectorAll("select[data-group-category]")]
        .find(input => input.dataset.groupCategory === entityId)?.dataset.categoryMode || "standard";
      return [entityId, {mode: profile, capabilities, display_category: displayCategory,
                         display_category_mode: displayCategoryMode}];
    }));
    const groupName = document.getElementById("device-group-name").value.trim();
    if (mode === "combined" && !groupName) return message("Gib einen Namen für das Alexa-Gesamtgerät ein.", "warn");
    setBusy(button, true, "Speichere…");
    try {
      await saveConfig();
      const result = await request("/api/native-export/group", {
        method: "POST",
        body: JSON.stringify({
          native_revision: config.native_revision,
          device_id: dialog.dataset.deviceId,
          entity_ids: entityIds,
          mode,
          name: groupName,
          names,
          profiles,
        }),
      });
      dialog.close();
      await load(false);
      message(mode === "combined"
        ? `Alexa-Gesamtgerät „${groupName}“ gespeichert. Die ausgewählten Funktionen werden unter einem Alexa-Gerät angeboten; abgewählte Entitäten sind aus dem Export entfernt.`
        : "Ausgewählte Entitäten werden wieder als einzelne Alexa-Geräte exportiert.", "warn");
    } catch (error) {
      message(`Alexa-Gerätegruppierung fehlgeschlagen: ${error.message}`, "err");
    } finally {
      setBusy(button, false);
    }
  }

  async function previewYaml() {
    try {
      const result = await request("/api/ha-export/preview", {method: "POST", body: JSON.stringify(config)});
      yamlRevision = config.native_revision;
      document.getElementById("yaml-output").value = result.yaml || ""; document.getElementById("yaml-dialog").showModal();
    } catch (error) { message(`YAML-Vorschau fehlgeschlagen: ${error.message}`, "err"); }
  }

  function openSettings() {
    document.getElementById("native-enabled").checked = config.native_enabled;
    const event = config.event_gateway || {}, groups = config.group_sync || {};
    document.getElementById("event-enabled").checked = Boolean(event.enabled);
    document.getElementById("event-endpoint").value = event.endpoint || "https://api.eu.amazonalexa.com/v3/events";
    document.getElementById("event-client-id-secret").value = event.client_id_secret || "alexa_skill_client_id";
    document.getElementById("event-client-secret-secret").value = event.client_secret_secret || "alexa_skill_client_secret";
    document.getElementById("event-fallback").checked = event.fallback_web_cleanup !== false;
    document.getElementById("group-enabled").checked = groups.enabled !== false;
    document.getElementById("group-create").checked = groups.create_missing !== false;
    document.getElementById("group-remove-other").checked = Boolean(groups.remove_from_other_groups);
    document.getElementById("locale").value = config.locale || "de-DE";
    document.getElementById("settings-dialog").showModal();
  }

  async function saveSettings(event) {
    event.preventDefault();
    const button = document.getElementById("btn-save-settings");
    setBusy(button, true, "Speichere…");
    let saved = false;
    try {
      config.event_gateway = {enabled: document.getElementById("event-enabled").checked, endpoint: document.getElementById("event-endpoint").value, client_id_secret: document.getElementById("event-client-id-secret").value.trim(), client_secret_secret: document.getElementById("event-client-secret-secret").value.trim(), fallback_web_cleanup: document.getElementById("event-fallback").checked};
      config.group_sync = {enabled: document.getElementById("group-enabled").checked, create_missing: document.getElementById("group-create").checked, remove_from_other_groups: document.getElementById("group-remove-other").checked};
      config.native_enabled = document.getElementById("native-enabled").checked;
      config.locale = document.getElementById("locale").value.trim() || "de-DE";
      await saveConfig();
      saved = true;
      document.getElementById("settings-dialog").close();
      const result = await request("/api/native-export/setup", {method: "POST", body: "{}"});
      message(result.note || "Einstellungen gespeichert.", result.restart_required ? "warn" : "ok");
    } catch (error) {
      const checkDetail = error.body?.check?.message && !error.message.includes(error.body.check.message)
        ? `\nHome Assistant: ${error.body.check.message}` : "";
      message(`${saved ? "Einstellungen gespeichert, aber der Alexa-Abgleich konnte nicht eingerichtet werden" : "Einstellungen konnten nicht gespeichert werden"}: ${error.message}${checkDetail}`, "err");
    } finally { setBusy(button, false); }
  }

  async function logout() {
    if (!confirm("Alexa-Web-Session wirklich löschen?")) return;
    await request("/api/logout", {method: "POST", body: "{}"}); await load(false);
  }

  async function handleAction(button) {
    const action = button.dataset.action;
    try {
      if (action === "toggle-area") {
        const id = button.dataset.area;
        if (expandedAreas.has(id)) { expandedAreas.delete(id); visibleAreaCounts.delete(id); }
        else { expandedAreas.add(id); visibleAreaCounts.set(id, AREA_PAGE_SIZE); }
        renderArea(button, id);
      }
      else if (action === "more-area") {
        const id = button.dataset.area;
        const count = Math.min((visibleAreaCounts.get(id) || AREA_PAGE_SIZE) + AREA_PAGE_SIZE,
          renderedAreaItems.get(id)?.length || 0);
        visibleAreaCounts.set(id, count);
        if (globalEditMode) {
          for (const {device} of (renderedAreaItems.get(id) || []).slice(0, count)) {
            expandedSimpleDevices.add(String(device.device_id));
          }
        }
        const areaToggle = button.closest("section.area")?.querySelector('button[data-action="toggle-area"]');
        if (areaToggle) renderArea(areaToggle, id);
      }
      else if (action === "toggle-device") { const id = button.dataset.device; expandedDevices.has(id) ? expandedDevices.delete(id) : expandedDevices.add(id); render(); }
      else if (action === "hide-device") await changeVisibility("device", button.dataset.device, true);
      else if (action === "show-device") await changeVisibility("device", button.dataset.device, false);
      else if (action === "hide-entity") await changeVisibility("entity", button.dataset.entity, true);
      else if (action === "show-entity") await changeVisibility("entity", button.dataset.entity, false);
      else if (action === "hide-alexa") await changeVisibility("alexa", button.dataset.key, true);
      else if (action === "show-alexa") await changeVisibility("alexa", button.dataset.key, false);
      else if (action === "rename-alexa") await renameAlexa(button.dataset.key);
      else if (action === "details-alexa") await showAlexaDetails(button.dataset.key);
      else if (action === "delete-alexa") await deleteAlexa(button.dataset.key);
      else if (action === "delete-selected-alexa") await deleteSelectedAlexa();
      else if (action === "assign-group") await assignGroup(button.dataset.entity, button.dataset.key);
      else if (action === "prepare-device") await prepareDevice(button.dataset.device, button);
      else if (action === "configure-device-group") openDeviceGroup(button.dataset.device);
      else if (action === "disable-device-export") await disableDeviceExport(button.dataset.device);
      else if (action === "toggle-simple-device") toggleSimpleDevice(button, button.dataset.device);
      else if (action === "suggest-simple-name") {
        const entityId = button.dataset.entity;
        const value = button.dataset.suggestion || "";
        entityConfig(entityId).name = value;
        const input = button.closest(".simple-alexa-name")?.querySelector(".export-name");
        if (input) input.value = value;
        syncEntityModelFromConfig();
        persistEditDraft();
        message(`Alexa-Name für ${entityId} wurde in den Entwurf übernommen.`);
      }
      else if (action === "fill-entity") await fillEntity(button.dataset.entity);
    } catch (error) { message(error.message, "err"); }
  }

  document.getElementById("content").addEventListener("click", event => {
    const button = event.target.closest("button[data-action]"); if (button) handleAction(button);
  });
  document.getElementById("content").addEventListener("change", event => {
    const target = event.target;
    if (target.matches("input[data-alexa-select]")) {
      if (target.checked) selectedAlexaKeys.add(target.dataset.alexaSelect);
      else selectedAlexaKeys.delete(target.dataset.alexaSelect);
      const visible = (model?.alexa_only || []).filter(item => alexaOnlyMatchesFilter(item, filters()));
      updateAlexaSelectionUi(visible);
      return;
    }
    if (target.id === "select-visible-alexa") {
      const visible = (model?.alexa_only || []).filter(item => alexaOnlyMatchesFilter(item, filters()));
      for (const item of visible) target.checked ? selectedAlexaKeys.add(item.key) : selectedAlexaKeys.delete(item.key);
      render();
    }
  });
  document.addEventListener("pointerover", event => {
    const element = event.target.closest("button, a.button");
    if (element) showButtonTooltip(element);
  });
  document.addEventListener("pointerout", event => {
    const element = event.target.closest("button, a.button");
    if (element && !element.contains(event.relatedTarget)) hideButtonTooltip(element);
  });
  document.addEventListener("focusin", event => {
    const element = event.target.closest("button, a.button");
    if (element) showButtonTooltip(element);
  });
  document.addEventListener("focusout", event => {
    const element = event.target.closest("button, a.button");
    if (element) hideButtonTooltip(element);
  });
  document.getElementById("content").addEventListener("change", async event => {
    const target = event.target, entityId = target.dataset.entity; if (!entityId) return;
    const settings = entityConfig(entityId);
    if (target.classList.contains("export-toggle")) {
      if (!globalEditMode) return;
      settings.enabled = target.checked;
      for (const device of model.devices || []) {
        const entity = (device.entities || []).find(item => item.entity_id === entityId);
        if (entity?.export) entity.export.enabled = target.checked;
      }
      if (target.checked) {
        const device = model.devices.find(item => item.entities.some(entity => entity.entity_id === entityId));
        const entity = device?.entities.find(item => item.entity_id === entityId);
        if (device && entity) {
          settings.name ||= suggestedName(entity, device);
          settings.display_category ||= suggestedCategory(entity, device);
          const nameInput = target.closest(".simple-entity-row")?.querySelector(".export-name");
          if (nameInput && !nameInput.value) nameInput.value = settings.name;
        }
      }
      syncEntityModelFromConfig();
      persistEditDraft();
      message(`${entityId} wurde im Entwurf ${target.checked ? "für Alexa ausgewählt" : "abgewählt"}. Klicke „Fertig – alles speichern“, um die Auswahl zu übernehmen.`, "warn");
    } else if (target.classList.contains("export-category")) {
      if (!globalEditMode) return;
      settings.display_category = target.value;
      settings.display_category_mode = target.value ? "custom" : "standard";
      scheduleSave();
    }
    else if (target.classList.contains("export-name")) {
      if (!globalEditMode) return;
      settings.name = target.value;
      syncEntityModelFromConfig();
      persistEditDraft();
    }
  });
  document.getElementById("content").addEventListener("input", event => {
    const target = event.target, entityId = target.dataset.entity; if (!entityId) return;
    if (!globalEditMode) return;
    const settings = entityConfig(entityId);
    if (target.classList.contains("export-name")) settings.name = target.value;
    if (target.classList.contains("export-group")) settings.alexa_group = target.value;
    syncEntityModelFromConfig();
    scheduleSave();
  });

  for (const id of ["search", "status-filter", "area-filter", "domain-filter"]) document.getElementById(id).addEventListener(id === "search" ? "input" : "change", () => {
    if (id === "status-filter") includeHiddenSummaryMatches = false;
    render();
  });
  document.getElementById("summary").addEventListener("click", event => {
    const card = event.target.closest("[data-summary-filter]");
    if (!card) return;
    document.getElementById("status-filter").value = card.dataset.summaryFilter;
    document.getElementById("search").value = "";
    document.getElementById("area-filter").value = "";
    document.getElementById("domain-filter").value = "";
    includeHiddenSummaryMatches = true;
    expandSummaryMatches();
    render();
    document.getElementById("content").scrollIntoView({behavior: "smooth", block: "start"});
  });
  document.getElementById("btn-refresh").addEventListener("click", () => load(true));
  document.getElementById("btn-create-virtual-group").addEventListener("click", () => openVirtualGroupDialog());
  document.getElementById("virtual-group-list").addEventListener("click", event => {
    const button = event.target.closest("button[data-virtual-action]");
    if (!button) return;
    const groupId = button.dataset.groupId;
    if (button.dataset.virtualAction === "edit") openVirtualGroupDialog(groupId);
    else if (button.dataset.virtualAction === "remove") stageVirtualGroupRemoval(groupId);
  });
  document.getElementById("btn-stage-virtual-group").addEventListener("click", stageVirtualGroupFromDialog);
  document.getElementById("btn-close-virtual-group").addEventListener("click", () => {
    persistVirtualGroupDialog(false);
    activeVirtualGroupId = null;
    persistEditDraft();
    document.getElementById("virtual-group-dialog").close();
    renderVirtualGroups();
  });
  document.getElementById("virtual-group-dialog").addEventListener("input", event => {
    if (event.target.id === "virtual-group-search") return filterVirtualGroupEntities();
    persistVirtualGroupDialog(false);
  });
  document.getElementById("virtual-group-dialog").addEventListener("change", event => {
    const row = event.target.closest(".virtual-group-entity");
    if (event.target.matches("select[data-vgroup-profile]")) {
      row?.querySelector("[data-vrange-fields]")?.classList.toggle("hidden", event.target.value !== "read_only_range");
    }
    persistVirtualGroupDialog(false);
  });
  document.getElementById("virtual-group-dialog").addEventListener("close", () => {
    if (!activeVirtualGroupId) return;
    persistVirtualGroupDialog(false);
    activeVirtualGroupId = null;
    persistEditDraft();
  });
  document.getElementById("btn-start-edit").addEventListener("click", () => startGlobalEditMode());
  document.getElementById("btn-finish-edit").addEventListener("click", event => finishGlobalEditMode(event.currentTarget));
  document.getElementById("btn-discard-edit").addEventListener("click", () => discardGlobalEditDraft());
  document.getElementById("btn-restart").addEventListener("click", restart);
  document.getElementById("btn-event-sync").addEventListener("click", eventSync);
  document.getElementById("btn-group-sync").addEventListener("click", groupSync);
  document.getElementById("btn-preview").addEventListener("click", previewYaml);
  document.getElementById("btn-settings").addEventListener("click", openSettings);
  document.getElementById("btn-save-settings").addEventListener("click", saveSettings);
  document.getElementById("btn-save-yaml").addEventListener("click", async () => {
    try {
      await request("/api/native-export/yaml", {method: "POST", body: JSON.stringify({native_revision: yamlRevision, yaml: document.getElementById("yaml-output").value})});
      document.getElementById("yaml-dialog").close(); await load(false); message("v6-Konfiguration gespeichert.");
    } catch (error) { message(error.message, "err"); }
  });
  document.getElementById("btn-save-device-group").addEventListener("click", saveDeviceGroup);
  document.getElementById("btn-close-device-group").addEventListener("click", () => document.getElementById("device-group-dialog").close());
  document.getElementById("device-group-entities").addEventListener("change", event => {
    const category = event.target.closest("select[data-group-category]");
    if (category) category.dataset.categoryMode = "custom";
    const select = event.target.closest("select[data-group-profile]");
    if (select) {
      const choices = [...document.querySelectorAll("[data-group-capabilities]")]
        .find(element => element.dataset.groupCapabilities === select.dataset.groupProfile);
      choices?.classList.toggle("hidden", select.value !== "custom");
    }
    renderDeviceGroupPreview();
  });
  document.querySelectorAll('input[name="device-group-mode"]').forEach(input => input.addEventListener("change", () => {
    document.getElementById("device-group-name-field").classList.toggle("hidden", input.value !== "combined");
    renderDeviceGroupPreview();
  }));
  document.getElementById("device-group-dialog").addEventListener("input", event => {
    if (event.target.matches("#device-group-name, input[data-group-name]")) renderDeviceGroupPreview();
  });
  document.getElementById("btn-close-yaml").addEventListener("click", () => document.getElementById("yaml-dialog").close());
  document.getElementById("btn-close-alexa-details").addEventListener("click", () => document.getElementById("alexa-details-dialog").close());
  document.getElementById("btn-logout").addEventListener("click", () => logout().catch(error => message(error.message, "err")));

  document.getElementById("btn-enable-useful").addEventListener("click", async () => {
    const filter = filters();
    const deviceIds = (model.devices || []).filter(device =>
      (device.entities || []).some(entity => entityMatchesFilter(entity, device, filter))
    ).map(device => device.device_id);
    await autoExportDevices(deviceIds, document.getElementById("btn-enable-useful"));
  });
  document.getElementById("btn-hide-technical").addEventListener("click", async () => {
    const filter = filters(), ids = [];
    for (const device of model.devices || []) for (const entity of device.entities || []) if (entityMatchesFilter(entity, device, filter) && isTechnical(entity)) ids.push(entity.entity_id);
    if (!ids.length) return message("Keine technischen sichtbaren Entitäten gefunden.", "warn");
    await changeVisibility("entity", ids, true);
  });
  document.getElementById("btn-unhide-visible").addEventListener("click", async () => {
    const query = filters().query, deviceIds = [], entityIds = [], alexaIds = [];
    for (const device of model.devices || []) {
      if (device.hidden && (!query || `${device.name} ${device.area_name || ""}`.toLowerCase().includes(query))) deviceIds.push(device.device_id);
      for (const entity of device.entities || []) if (entity.hidden_directly && (!query || `${device.name} ${entity.name} ${entity.entity_id}`.toLowerCase().includes(query))) entityIds.push(entity.entity_id);
    }
    for (const item of model.alexa_only || []) if (item.hidden && (!query || `${item.name} ${item.serial}`.toLowerCase().includes(query))) alexaIds.push(item.key);
    if (deviceIds.length) await changeVisibility("device", deviceIds, false);
    if (entityIds.length) await changeVisibility("entity", entityIds, false);
    if (alexaIds.length) await changeVisibility("alexa", alexaIds, false);
  });

  let reconciliationRunning = false;
  setInterval(async () => {
    if (document.hidden) return;
    try {
      const status = await request("/api/native-export/lifecycle");
      lifecyclePausedElsewhere = Boolean(status.sync_paused) && !hasEditorSession();
      updateSyncEditStatus();
      if (status.running) reconciliationRunning = true;
      else if (reconciliationRunning) {
        if (hasEditorSession()) {
          reconciliationRunning = false;
          return;
        }
        if (document.activeElement?.matches("input, select, textarea") || document.getElementById("settings-dialog").open || document.getElementById("yaml-dialog").open || document.getElementById("device-group-dialog").open) return;
        reconciliationRunning = false;
        const errors = [status.publish_error, status.legacy_error, status.background_error].filter(Boolean);
        const completed = `Alexa-Abgleich abgeschlossen. Alte v5-Geräte gelöscht: ${status.legacy_deleted || 0}. Abgewählte v6-Geräte gelöscht: ${status.unselected_native_deleted || 0}. Noch unerwünscht: ${status.selection_remaining ?? "ungeprüft"}. Bestand wird neu geladen.`;
        message(errors.length ? errors.join("\n") : completed, errors.length ? "err" : "ok");
        await load(false);
      }
    } catch (_) {}
  }, 5000);
  load(false);
})();
