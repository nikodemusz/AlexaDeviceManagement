(() => {
  const BASE = document.documentElement.dataset.ingressPath || "";
  let model = null;
  let config = null;
  let saveTimer = null;
  let savePromise = Promise.resolve();
  const expandedAreas = new Set();
  const expandedDevices = new Set();

  const STATUS_TEXT = {
    synced: "Synchronisiert",
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
    return technicalDomains.includes(entity.domain) || words.some(word => text.includes(word));
  }
  function isUseful(entity) {
    return !isTechnical(entity) && ["light", "switch", "cover", "climate", "lock", "camera", "scene", "script", "fan", "input_boolean", "media_player"].includes(entity.domain);
  }
  function suggestedCategory(entity) {
    if (entity.category_suggestion && entity.category_suggestion !== "OTHER") return entity.category_suggestion;
    if (entity.domain === "light") return "LIGHT";
    if (entity.domain === "cover") return entity.device_class === "garage" ? "GARAGE_DOOR" : "INTERIOR_BLIND";
    if (entity.domain === "climate") return "THERMOSTAT";
    if (entity.domain === "lock") return "LOCK";
    if (entity.domain === "camera") return "CAMERA";
    if (["scene", "script"].includes(entity.domain)) return "SCENE_TRIGGER";
    if (entity.domain === "switch" && entity.device_class === "outlet") return "SMARTPLUG";
    return "SWITCH";
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

  function scheduleSave() { clearTimeout(saveTimer); saveTimer = setTimeout(saveConfig, 500); }
  function saveConfig() {
    clearTimeout(saveTimer);
    if (!config) return Promise.resolve();
    const snapshot = JSON.parse(JSON.stringify(config));
    savePromise = savePromise.then(async () => {
      try {
        const result = await request("/api/ha-export/autosave", {method: "POST", body: JSON.stringify(snapshot)});
        config = result.configuration || config;
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
      domain: document.getElementById("domain-filter").value
    };
  }

  function entityMatchesFilter(entity, device, filter) {
    const hidden = entity.hidden || device.hidden;
    if (filter.status === "hidden") { if (!hidden) return false; }
    else if (hidden) return false;
    if (filter.area && device.area_id !== filter.area) return false;
    if (filter.domain && entity.domain !== filter.domain) return false;
    if (filter.status === "selected" && !entity.export.enabled) return false;
    if (filter.status === "synced" && entity.status !== "synced") return false;
    if (filter.status === "pending" && entity.status !== "pending") return false;
    if (filter.status === "only_alexa" && entity.status !== "only_alexa") return false;
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
    else if (item.hidden) return false;
    if (!["all", "alexa_only", "problems", "hidden"].includes(filter.status)) return false;
    if (filter.status === "problems" && !["orphaned", "unmatched"].includes(item.status)) return false;
    if (filter.query) {
      const haystack = `${item.name} ${item.serial} ${item.family} ${item.skill} ${item.room} ${(item.groups || []).join(" ")}`.toLowerCase();
      if (!haystack.includes(filter.query)) return false;
    }
    return true;
  }

  function renderSummary() {
    const s = model.summary || {};
    const cards = [["HA-Geräte", s.ha_devices || 0], ["HA-Entitäten", s.ha_entities || 0], ["Für Alexa", s.selected || 0], ["Synchronisiert", s.synced || 0], ["Ausstehend", s.pending || 0], ["Noch in Alexa", s.only_alexa || 0], ["Duplikate", s.duplicates || 0], ["Nur Alexa", s.alexa_only || 0], ["Ausgeblendet", s.hidden || 0]];
    document.getElementById("summary").innerHTML = cards.map(([label, value]) => `<div class="summary-card"><strong>${value}</strong>${esc(label)}</div>`).join("");
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
    document.getElementById("group-list").innerHTML = (model.groups || []).map(group => `<option value="${attr(group.name)}"></option>`).join("");
    document.getElementById("btn-unhide-visible").classList.toggle("hidden", document.getElementById("status-filter").value !== "hidden");
  }

  function alexaMatchHtml(match, entity) {
    const groupText = (match.groups || []).length ? ` • Gruppen: ${(match.groups || []).join(", ")}` : "";
    const online = match.online ? "erreichbar" : "nicht erreichbar";
    return `<div class="alexa-match"><div class="alexa-line"><div><div class="alexa-name">${esc(match.name)}</div><div class="alexa-meta">${esc(match.source)} • ${esc(online)}${esc(groupText)}<br>${esc(match.serial)}</div></div><div class="alexa-actions"><button class="button secondary small" data-action="rename-alexa" data-key="${attr(match.key)}">Umbenennen</button><button class="button danger small" data-action="delete-alexa" data-key="${attr(match.key)}">Löschen</button></div></div>${entity.export.alexa_group ? `<button class="button secondary small" data-action="assign-group" data-entity="${attr(entity.entity_id)}" data-key="${attr(match.key)}">Gruppe „${esc(entity.export.alexa_group)}“ zuweisen</button>` : ""}</div>`;
  }

  function entityHtml(entity, device) {
    const exportData = entity.export;
    const matches = entity.alexa?.matches || [];
    const categories = (model.display_categories || []).map(category => `<option value="${attr(category)}" ${exportData.display_category === category ? "selected" : ""}>${esc(category)}</option>`).join("");
    return `<article class="entity status-${attr(entity.status)} ${entity.hidden ? "hidden-item" : ""}" data-entity="${attr(entity.entity_id)}"><div class="entity-top"><input class="export-toggle" type="checkbox" data-entity="${attr(entity.entity_id)}" ${exportData.enabled ? "checked" : ""} title="Für Alexa exportieren"><div><div class="entity-name">${esc(entity.name || entity.entity_id)}</div><div class="entity-id">${esc(entity.entity_id)}</div><div class="badges">${statusBadge(entity.status)}${matches.length ? `<span class="badge alexa">${matches.length} Alexa-Endpunkt${matches.length === 1 ? "" : "e"}</span>` : ""}${isTechnical(entity) ? '<span class="badge">technisch</span>' : ""}${entity.hidden ? '<span class="badge hidden-badge">ausgeblendet</span>' : ""}</div></div><button class="button secondary small" data-action="${entity.hidden_directly ? "show-entity" : "hide-entity"}" data-entity="${attr(entity.entity_id)}">${entity.hidden_directly ? "Einblenden" : "Ausblenden"}</button></div><div class="fields"><div class="field"><label>Alexa-Name</label><input class="export-name" data-entity="${attr(entity.entity_id)}" value="${attr(exportData.name)}" placeholder="${attr(suggestedName(entity, device))}"></div><div class="field"><label>Kategorie</label><select class="export-category" data-entity="${attr(entity.entity_id)}"><option value="">Automatisch</option>${categories}</select></div><div class="field full"><label>Alexa-Gruppe</label><input class="export-group" data-entity="${attr(entity.entity_id)}" value="${attr(exportData.alexa_group)}" list="group-list" placeholder="${attr(device.area_name || "")}"></div></div><div class="entity-actions"><button class="button secondary small" data-action="fill-entity" data-entity="${attr(entity.entity_id)}">Vorschlag übernehmen</button></div>${matches.map(match => alexaMatchHtml(match, entity)).join("")}</article>`;
  }

  function deviceHtml(device, entities) {
    const expanded = expandedDevices.has(device.device_id);
    return `<section class="device status-${attr(device.status)} ${device.hidden ? "hidden-item" : ""}" data-device-section="${attr(device.device_id)}"><div class="device-head"><button class="collapse-toggle" data-action="toggle-device" data-device="${attr(device.device_id)}" aria-expanded="${expanded}">${expanded ? "▾" : "▸"}</button><div class="device-title"><div class="device-name">${esc(device.name)}</div><div class="device-meta">${esc(device.area_name || "Kein Bereich")}${device.floor_name ? ` • ${esc(device.floor_name)}` : ""}${device.manufacturer ? ` • ${esc(device.manufacturer)}` : ""}${device.model ? ` • ${esc(device.model)}` : ""}</div></div><div class="device-actions"><button class="button primary small" data-action="prepare-device" data-device="${attr(device.device_id)}">Sinnvoll aktivieren</button><button class="button secondary small" data-action="${device.hidden ? "show-device" : "hide-device"}" data-device="${attr(device.device_id)}">${device.hidden ? "Einblenden" : "Gerät ausblenden"}</button></div></div>${expanded ? `<div class="entity-grid">${entities.map(entity => entityHtml(entity, device)).join("")}</div>` : ""}</section>`;
  }

  function alexaOnlyHtml(item) {
    return `<article class="alexa-card ${item.status === "orphaned" ? "orphaned" : ""} ${item.hidden ? "hidden-item" : ""}"><div class="alexa-name">${esc(item.name)}</div><div class="badges">${statusBadge(item.status)}${item.hidden ? '<span class="badge hidden-badge">ausgeblendet</span>' : ""}</div><div class="alexa-meta">${esc(item.source)}${item.family ? ` • ${esc(item.family)}` : ""}${item.skill ? ` • ${esc(item.skill)}` : ""}<br>${esc(item.serial)}${item.groups?.length ? `<br>Gruppen: ${esc(item.groups.join(", "))}` : ""}</div><div class="alexa-actions"><button class="button secondary small" data-action="${item.hidden ? "show-alexa" : "hide-alexa"}" data-key="${attr(item.key)}">${item.hidden ? "Einblenden" : "Ausblenden"}</button><button class="button secondary small" data-action="rename-alexa" data-key="${attr(item.key)}">Umbenennen</button><button class="button danger small" data-action="delete-alexa" data-key="${attr(item.key)}">Löschen</button></div></article>`;
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
    if (filter.status !== "alexa_only") {
      for (const [area, items] of [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0], "de"))) {
        const areaKey = items[0]?.device?.area_id || area;
        const expanded = expandedAreas.has(areaKey);
        html.push(`<section class="area"><div class="area-title"><button class="collapse-toggle" data-action="toggle-area" data-area="${attr(areaKey)}" aria-expanded="${expanded}">${expanded ? "▾" : "▸"}</button><h2>${esc(area)}</h2><span class="muted">${items.length} Geräte</span></div>`);
        if (expanded) for (const item of items) html.push(deviceHtml(item.device, item.entities));
        html.push("</section>");
      }
    }
    const alexaOnly = (model.alexa_only || []).filter(item => alexaOnlyMatchesFilter(item, filter));
    if (alexaOnly.length) {
      html.push('<h2 class="alexa-only-title">Alexa-Geräte ohne Home-Assistant-Zuordnung</h2><div class="alexa-only-grid">');
      html.push(...alexaOnly.map(alexaOnlyHtml)); html.push("</div>");
    }
    document.getElementById("content").innerHTML = html.length ? html.join("") : '<div class="empty">Keine Geräte entsprechen dem aktuellen Filter.</div>';
    document.getElementById("btn-login").classList.toggle("hidden", model.alexa_connected);
    document.getElementById("btn-logout").classList.toggle("hidden", !model.alexa_connected);
  }

  async function load(force = false) {
    const button = document.getElementById("btn-refresh");
    setBusy(button, true, "Lade…"); clearMessage();
    try {
      model = await request(`/api/device-overview${force ? "?refresh=1" : ""}`);
      config = model.configuration; render();
      if (model.warnings?.length) message(model.warnings.join("\n"), "warn");
    } catch (error) {
      document.getElementById("content").innerHTML = `<div class="empty">${esc(error.message)}</div>`;
      message(`Geräteübersicht konnte nicht geladen werden: ${error.message}`, "err");
    } finally { setBusy(button, false); }
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
      if (result.configuration) config = result.configuration;
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

  async function prepareDevice(deviceId) {
    const device = (model.devices || []).find(item => item.device_id === deviceId); if (!device) return;
    const candidate = device.entities.find(isUseful) || device.entities.find(entity => !isTechnical(entity));
    if (!candidate) return message("Für dieses Gerät wurde keine sinnvolle Alexa-Entität gefunden.", "err");
    for (const entity of device.entities) entityConfig(entity.entity_id).enabled = false;
    const settings = entityConfig(candidate.entity_id);
    settings.enabled = true; settings.name ||= suggestedName(candidate, device); settings.display_category ||= suggestedCategory(candidate);
    await saveConfig(); message(`${candidate.entity_id} wurde für Alexa vorbereitet.`); await load(false);
  }

  async function fillEntity(entityId) {
    for (const device of model.devices || []) {
      const entity = device.entities.find(item => item.entity_id === entityId); if (!entity) continue;
      const settings = entityConfig(entityId);
      settings.name = suggestedName(entity, device); settings.display_category = suggestedCategory(entity); settings.alexa_group ||= device.area_name || ""; settings.enabled = true;
      await saveConfig(); await load(false); return;
    }
  }

  async function deploy() {
    const button = document.getElementById("btn-deploy"); setBusy(button, true, "Rolle aus…");
    try {
      await saveConfig();
      const result = await request("/api/ha-export/deploy", {method: "POST", body: JSON.stringify(config)});
      const event = result.alexa_event_sync;
      message(`Konfiguration ausgerollt: ${result.selected_count ?? result.selected ?? 0} Entitäten.` + (event?.pending ? `\nEvent Gateway vorgemerkt: ${(event.pending_add_or_update || []).length} Updates, ${(event.pending_delete || []).length} Löschungen.` : ""));
      await load(false);
    } catch (error) { message(`Deployment fehlgeschlagen: ${error.message}`, "err"); }
    finally { setBusy(button, false); }
  }

  async function restart() {
    const button = document.getElementById("btn-restart"); setBusy(button, true, "Starte…");
    try { const result = await request("/api/ha-export/restart", {method: "POST", body: "{}"}); message(result.note || "Home Assistant Core wird neu gestartet."); }
    catch (error) { message(`Neustart fehlgeschlagen: ${error.message}`, "err"); }
    finally { setBusy(button, false); }
  }

  async function eventSync() {
    const button = document.getElementById("btn-event-sync"); setBusy(button, true, "Synchronisiere…");
    try {
      const result = await request("/api/ha-export/event-sync", {method: "POST", body: JSON.stringify({force: true})});
      message(`Alexa Event Gateway erfolgreich.\nUpdates: ${result.official?.add_or_update_count || 0}\nLöschungen: ${result.official?.delete_count || 0}`); await load(true);
    } catch (error) {
      const fallback = error.body?.fallback;
      message(`Event-Gateway-Abgleich fehlgeschlagen: ${error.message}` + (fallback ? `\nWeb-Fallback entfernt: ${(fallback.deleted_removed || []).length}` : ""), "err");
      await load(false);
    } finally { setBusy(button, false); }
  }

  async function groupSync() {
    const button = document.getElementById("btn-group-sync"); setBusy(button, true, "Ordne zu…");
    try {
      await saveConfig();
      const result = await request("/api/ha-export/group-sync", {method: "POST", body: JSON.stringify({configuration: config})});
      message(`Alexa-Gruppen: ${result.successful || 0} erfolgreich, ${result.failed || 0} fehlgeschlagen.`, result.failed ? "warn" : "ok"); await load(true);
    } catch (error) { message(`Gruppenabgleich fehlgeschlagen: ${error.message}`, "err"); }
    finally { setBusy(button, false); }
  }

  async function previewYaml() {
    try {
      const result = await request("/api/ha-export/preview", {method: "POST", body: JSON.stringify(config)});
      document.getElementById("yaml-output").textContent = result.yaml || ""; document.getElementById("yaml-dialog").showModal();
    } catch (error) { message(`YAML-Vorschau fehlgeschlagen: ${error.message}`, "err"); }
  }

  function openSettings() {
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
    config.event_gateway = {enabled: document.getElementById("event-enabled").checked, endpoint: document.getElementById("event-endpoint").value, client_id_secret: document.getElementById("event-client-id-secret").value.trim(), client_secret_secret: document.getElementById("event-client-secret-secret").value.trim(), fallback_web_cleanup: document.getElementById("event-fallback").checked};
    config.group_sync = {enabled: document.getElementById("group-enabled").checked, create_missing: document.getElementById("group-create").checked, remove_from_other_groups: document.getElementById("group-remove-other").checked};
    config.locale = document.getElementById("locale").value.trim() || "de-DE";
    await saveConfig(); document.getElementById("settings-dialog").close(); message("Einstellungen gespeichert.");
  }

  async function logout() {
    if (!confirm("Alexa-Web-Session wirklich löschen?")) return;
    await request("/api/logout", {method: "POST", body: "{}"}); await load(false);
  }

  async function handleAction(button) {
    const action = button.dataset.action;
    try {
      if (action === "toggle-area") { const id = button.dataset.area; expandedAreas.has(id) ? expandedAreas.delete(id) : expandedAreas.add(id); render(); }
      else if (action === "toggle-device") { const id = button.dataset.device; expandedDevices.has(id) ? expandedDevices.delete(id) : expandedDevices.add(id); render(); }
      else if (action === "hide-device") await changeVisibility("device", button.dataset.device, true);
      else if (action === "show-device") await changeVisibility("device", button.dataset.device, false);
      else if (action === "hide-entity") await changeVisibility("entity", button.dataset.entity, true);
      else if (action === "show-entity") await changeVisibility("entity", button.dataset.entity, false);
      else if (action === "hide-alexa") await changeVisibility("alexa", button.dataset.key, true);
      else if (action === "show-alexa") await changeVisibility("alexa", button.dataset.key, false);
      else if (action === "rename-alexa") await renameAlexa(button.dataset.key);
      else if (action === "delete-alexa") await deleteAlexa(button.dataset.key);
      else if (action === "assign-group") await assignGroup(button.dataset.entity, button.dataset.key);
      else if (action === "prepare-device") await prepareDevice(button.dataset.device);
      else if (action === "fill-entity") await fillEntity(button.dataset.entity);
    } catch (error) { message(error.message, "err"); }
  }

  document.getElementById("content").addEventListener("click", event => {
    const button = event.target.closest("button[data-action]"); if (button) handleAction(button);
  });
  document.getElementById("content").addEventListener("change", async event => {
    const target = event.target, entityId = target.dataset.entity; if (!entityId) return;
    const settings = entityConfig(entityId);
    if (target.classList.contains("export-toggle")) {
      settings.enabled = target.checked;
      if (target.checked) {
        const device = model.devices.find(item => item.entities.some(entity => entity.entity_id === entityId));
        const entity = device?.entities.find(item => item.entity_id === entityId);
        if (device && entity) { settings.name ||= suggestedName(entity, device); settings.display_category ||= suggestedCategory(entity); }
      }
      await saveConfig(); await load(false);
    } else if (target.classList.contains("export-category")) { settings.display_category = target.value; scheduleSave(); }
  });
  document.getElementById("content").addEventListener("input", event => {
    const target = event.target, entityId = target.dataset.entity; if (!entityId) return;
    const settings = entityConfig(entityId);
    if (target.classList.contains("export-name")) settings.name = target.value;
    if (target.classList.contains("export-group")) settings.alexa_group = target.value;
    scheduleSave();
  });

  for (const id of ["search", "status-filter", "area-filter", "domain-filter"]) document.getElementById(id).addEventListener(id === "search" ? "input" : "change", render);
  document.getElementById("btn-refresh").addEventListener("click", () => load(true));
  document.getElementById("btn-deploy").addEventListener("click", deploy);
  document.getElementById("btn-restart").addEventListener("click", restart);
  document.getElementById("btn-event-sync").addEventListener("click", eventSync);
  document.getElementById("btn-group-sync").addEventListener("click", groupSync);
  document.getElementById("btn-preview").addEventListener("click", previewYaml);
  document.getElementById("btn-settings").addEventListener("click", openSettings);
  document.getElementById("btn-save-settings").addEventListener("click", saveSettings);
  document.getElementById("btn-close-yaml").addEventListener("click", () => document.getElementById("yaml-dialog").close());
  document.getElementById("btn-logout").addEventListener("click", () => logout().catch(error => message(error.message, "err")));

  document.getElementById("btn-enable-useful").addEventListener("click", async () => {
    const filter = filters();
    for (const device of model.devices || []) for (const entity of device.entities || []) if (entityMatchesFilter(entity, device, filter) && isUseful(entity)) {
      const settings = entityConfig(entity.entity_id); settings.enabled = true; settings.name ||= suggestedName(entity, device); settings.display_category ||= suggestedCategory(entity);
    }
    await saveConfig(); await load(false);
  });
  document.getElementById("btn-disable-visible").addEventListener("click", async () => {
    const filter = filters();
    for (const device of model.devices || []) for (const entity of device.entities || []) if (entityMatchesFilter(entity, device, filter)) entityConfig(entity.entity_id).enabled = false;
    await saveConfig(); await load(false);
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

  load(false);
})();
