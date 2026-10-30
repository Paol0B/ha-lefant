// lefant-vacuum-card - control card for the Lefant integration.
//
// Map with selectable rooms, cleaning actions, suction/water/passes and robot
// settings. Map layers, rooms and the ids of the robot entities come from the
// `lefant/map` websocket command, so the card needs only the vacuum entity.

const STATUS = {
  standby: "In attesa",
  smart: "Pulizia in corso",
  zone_clean: "Pulizia zona",
  part_clean: "Pulizia stanze",
  cleaning: "Pulizia in corso",
  paused: "In pausa",
  goto_pos: "Verso il punto",
  pos_arrived: "Punto raggiunto",
  pos_unarrive: "Punto non raggiungibile",
  goto_charge: "Rientro alla base",
  charging: "In carica",
  charge_done: "Carica completa",
  sleep: "A riposo",
  relocating: "Si sta localizzando",
  relocating_recharge: "Cerca la base",
  recharing_paused: "Rientro in pausa",
  fastmaping: "Mappatura",
  fastmaping_paused: "Mappatura in pausa",
  dust_collection: "Svuota la polvere",
  wash_mop: "Lava il mop",
  goto_wash: "Va a lavare il mop",
  wash_paused: "Lavaggio in pausa",
  drying: "Asciuga il mop",
  continuity_clear_charging: "Ricarica, poi riprende",
  relocating_pause: "Localizzazione in pausa",
};

const ERRORS = {
  side_brush: "Spazzola laterale",
  main_brush: "Spazzola principale",
  left_wheel: "Ruota sinistra",
  right_wheel: "Ruota destra",
  dust_bin: "Contenitore polvere",
  cliff_sensor: "Sensore anticaduta",
  bumper: "Paraurti",
  other: "Guasto",
};

const SUCTION = [
  ["closed", "Spenta", "mdi:fan-off"],
  ["gentle", "Silenziosa", "mdi:fan-speed-1"],
  ["normal", "Standard", "mdi:fan-speed-2"],
  ["strong", "Forte", "mdi:fan-speed-3"],
  ["superStrong", "Max", "mdi:fan-plus"],
];

const WATER = [
  ["closed", "Spenta", "mdi:water-off"],
  ["low", "Bassa", "mdi:water-outline"],
  ["middle", "Media", "mdi:water"],
  ["high", "Alta", "mdi:waves"],
];

const SETTINGS = [
  ["14", "Spinta sui tappeti", "Aumenta l'aspirazione quando rileva un tappeto", "mdi:rug"],
  ["172", "Rilevamento tappeti", "Riconosce i tappeti durante la pulizia", "mdi:texture-box"],
  ["15", "Riprendi dopo la ricarica", "Se la batteria si scarica, ricarica e finisce il lavoro", "mdi:battery-sync"],
];

// base station alerts (DP 158): the robot raises them when the part is out of the base
const BASE = [
  ["base_clean_water", "Acqua pulita", "mdi:water"],
  ["base_dirty_water", "Acqua sporca", "mdi:water-opacity"],
  ["base_dust_bag", "Sacchetto polvere", "mdi:delete-outline"],
];
const BASE_STATUS = new Set(["dust_collection", "wash_mop", "goto_wash", "wash_paused", "drying"]);

// usage counted by the integration since the last "Sostituito", the robot does not report wear
const PARTS = [
  ["main_brush", "Spazzola principale", "mdi:brush"],
  ["side_brush", "Spazzola laterale", "mdi:brush"],
  ["filter", "Filtro", "mdi:air-filter"],
  ["mop", "Panni del mop", "mdi:waves"],
  ["dust_bag", "Sacchetto della base", "mdi:delete-outline"],
];

// no greens: the selection uses the primary color, green in the Forge theme
const ROOM_COLORS = ["#7aa7e8", "#e3b56a", "#a99be6", "#ec9aa9", "#69bfdc", "#f3a76b", "#8f9fc4", "#d79ad8"];

// no-go area modes of the robot protocol
const AREA_MODES = [[0, "Vietata"], [1, "No aspirazione"], [2, "No mop"]];
const AREA_COLORS = { 0: "#e5484d", 1: "#f59e0b", 2: "#3b82f6" };
const PIXEL_M = 0.05; // one map unit is 5 cm

// errors of the lefant/* websocket commands, from coordinator.py
const EDIT_ERRORS = [
  ["the robot did not confirm", "Il robot non ha confermato la modifica."],
  ["the robot refused to split", "Il robot ha rifiutato la divisione: traccia la linea da muro a muro, attraverso tutta la stanza."],
  ["the robot refused to merge", "Il robot ha rifiutato l'unione: le due stanze devono toccarsi."],
  ["the map can be edited only", "La mappa si modifica solo quando il robot non sta pulendo."],
  ["the robot is not reachable", "Il robot non e' raggiungibile."],
  ["too many barriers", "Troppe barriere e zone vietate: eliminane qualcuna."],
  ["no map yet", "Manca la mappa: serve prima una pulizia completa."],
];
const editError = (e) => {
  const text = e?.message || String(e);
  return EDIT_ERRORS.find(([en]) => text.startsWith(en))?.[1] || text;
};

const rectOf = (a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1])];
// corners in the order the robot reports them: top-left, top-right, bottom-right, bottom-left
const rectPoints = (x, y, w, h) => [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
  .map((p) => p.map((v) => Math.round(v * 10) / 10));

// what the robot is doing during a cleaning: [icon, text, detail]
const PHASE = {
  smart: ["mdi:robot-vacuum", "Sta pulendo", ""],
  cleaning: ["mdi:robot-vacuum", "Sta pulendo", ""],
  part_clean: ["mdi:robot-vacuum", "Sta pulendo", ""],
  zone_clean: ["mdi:robot-vacuum", "Sta pulendo la zona", ""],
  goto_pos: ["mdi:map-marker-path", "Va al punto scelto", ""],
  pos_arrived: ["mdi:map-marker-check-outline", "Punto raggiunto", ""],
  relocating: ["mdi:crosshairs-question", "Cerca la sua posizione sulla mappa", ""],
  fastmaping: ["mdi:map-search-outline", "Disegna la mappa", ""],
  goto_wash: ["mdi:home-import-outline", "Torna alla base a lavare il mop", "Poi riprende da dove era rimasto."],
  wash_mop: ["mdi:water-sync", "Alla base, lava il mop", "Dura circa 2 minuti, poi riprende."],
  charging: ["mdi:home-outline", "Alla base, sta per ripartire", ""],
  charge_done: ["mdi:home-outline", "Alla base, sta per ripartire", ""],
  continuity_clear_charging: ["mdi:battery-charging", "Si ricarica, poi riprende", ""],
  dust_collection: ["mdi:delete-empty-outline", "Svuota la polvere nella base", ""],
  paused: ["mdi:pause-circle-outline", "In pausa", "Premi Riprendi per continuare."],
  goto_charge: ["mdi:home-import-outline", "Torna alla base", ""],
};

const CLEANING = new Set(["smart", "zone_clean", "part_clean", "cleaning", "goto_pos", "pos_arrived",
  "relocating", "fastmaping", "wash_mop", "goto_wash"]);
const PAUSED = new Set(["paused", "recharing_paused", "fastmaping_paused", "wash_paused", "relocating_pause"]);
const RETURNING = new Set(["goto_charge", "relocating_recharge"]);

const MAP_REFRESH_MS = 10 * 60 * 1000;

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function storageGet(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : JSON.parse(v);
  } catch (e) {
    return fallback;
  }
}

function storageSet(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (e) {
    /* private mode */
  }
}

function relTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const days = Math.round((new Date().setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / 86400000);
  const hm = d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
  if (days === 0) return `oggi alle ${hm}`;
  if (days === 1) return `ieri alle ${hm}`;
  return `${d.toLocaleDateString("it-IT", { weekday: "short", day: "numeric", month: "short" })} alle ${hm}`;
}

class LefantVacuumCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity || !config.entity.startsWith("vacuum.")) {
      throw new Error("Serve entity: vacuum.<robot>");
    }
    this._config = config;
    this._selected = [];
    this._passes = 1;
    this._busy = null;
    this._message = null;
    this._data = null;
    this._showRoute = storageGet("lefant-card-route", false);
    this._sig = "";
    this._ed = null; // map editor state, null when not editing
    this._edv = 0; // bumped on every editor change, part of the render signature
    this._view = null; // zoomed viewBox [x, y, w, h], null = whole house
    this._fitBox = null;
    this._ptrs = new Map();
    this._drag = null;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) this._init();
    const mapState = this._data?.entities?.map ? hass.states[this._data.entities.map]?.state : null;
    if (!this._data || (mapState && mapState !== this._mapState) || Date.now() - (this._fetched || 0) > MAP_REFRESH_MS) {
      this._mapState = mapState;
      this._fetch();
    }
    this._render();
  }

  getCardSize() {
    return 12;
  }

  getGridOptions() {
    return { columns: "full", min_columns: 6 };
  }

  _init() {
    this.attachShadow({ mode: "open" });
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this._observe();
  }

  connectedCallback() {
    if (this.shadowRoot && !this._resize) this._observe();
  }

  disconnectedCallback() {
    this._resize?.disconnect();
    this._resize = null;
  }

  // side-by-side layout only when the card itself is wide, not the window
  _observe() {
    this._resize = new ResizeObserver((entries) => {
      const wide = entries[0].contentRect.width >= 760;
      if (wide !== this._wide) {
        this._wide = wide;
        this._sig = "";
        this._render();
      } else {
        this._fitMap();
      }
    });
    this._resize.observe(this);
  }

  async _fetch() {
    if (this._fetching) return;
    this._fetching = true;
    try {
      this._data = await this._hass.callWS({ type: "lefant/map", entity_id: this._config.entity });
      this._error = null;
      const known = new Set(this._data.rooms.map((r) => r.id));
      this._selected = this._selected.filter((id) => known.has(id));
    } catch (e) {
      this._error = e.message || String(e);
    } finally {
      this._fetched = Date.now();
      this._fetching = false;
      this._sig = "";
      this._render();
    }
  }

  _state(key) {
    const id = key === "vacuum" ? this._config.entity : this._data?.entities?.[key];
    return id ? this._hass.states[id] : undefined;
  }

  async _call(label, domain, service, data) {
    this._busy = label;
    this._message = null;
    this._sig = "";
    this._render();
    try {
      await this._hass.callService(domain, service, data);
    } catch (e) {
      this._message = `${label}: ${e.message || e}`;
    } finally {
      this._busy = null;
      this._sig = "";
      this._render();
    }
  }

  _onClick(ev) {
    const el = ev.composedPath().find((n) => n.dataset && n.dataset.action);
    if (!el || el.hasAttribute("disabled")) return;
    const { action, value } = el.dataset;
    if (this._suppressClick) {
      this._suppressClick = false;
      if (action === "room") return;
    }
    if (this._ed && (action === "room" || action.startsWith("ed-"))) {
      this._onEditClick(action, value);
      return;
    }
    const vacuum = { entity_id: this._config.entity };
    switch (action) {
      case "edit":
        this._editStart();
        break;
      case "room": {
        const id = Number(value);
        this._selected = this._selected.includes(id) ? this._selected.filter((r) => r !== id) : [...this._selected, id];
        this._sig = "";
        this._render();
        break;
      }
      case "all":
        this._selected = this._selected.length ? [] : this._data.rooms.map((r) => r.id);
        this._sig = "";
        this._render();
        break;
      case "route":
        this._showRoute = !this._showRoute;
        storageSet("lefant-card-route", this._showRoute);
        this._sig = "";
        this._render();
        break;
      case "passes":
        this._passes = Number(value);
        this._sig = "";
        this._render();
        break;
      case "start":
        if (this._selected.length) {
          this._cleanRooms(this._selected, this._passes).then(() => {
            if (!this._message) this._selected = [];
            this._sig = "";
            this._render();
          });
        } else {
          this._call("Avvio", "vacuum", "start", vacuum);
        }
        break;
      case "resume":
        this._call("Ripresa", "vacuum", "start", vacuum);
        break;
      case "pause":
        this._call("Pausa", "vacuum", "pause", vacuum);
        break;
      case "stop":
        this._call("Stop", "vacuum", "stop", vacuum);
        break;
      case "dock":
        this._call("Rientro", "vacuum", "return_to_base", vacuum);
        break;
      case "locate":
        this._call("Trova robot", "vacuum", "locate", vacuum);
        break;
      case "suction":
        this._call("Aspirazione", "vacuum", "set_fan_speed", { ...vacuum, fan_speed: value });
        break;
      case "water":
        this._call("Acqua", "select", "select_option", { entity_id: this._data.entities["10"], option: value });
        break;
      case "setting": {
        const st = this._state(value);
        if (!st) return;
        this._call("Impostazione", "switch", st.state === "on" ? "turn_off" : "turn_on", { entity_id: st.entity_id });
        break;
      }
      case "replaced": {
        if (this._confirmPart !== value) {
          this._confirmPart = value;
          clearTimeout(this._confirmTimer);
          this._confirmTimer = setTimeout(() => {
            this._confirmPart = null;
            this._render();
          }, 5000);
          this._render();
          break;
        }
        this._confirmPart = null;
        const id = this._resetEntity(value);
        if (id) this._call("Sostituito", "button", "press", { entity_id: id });
        break;
      }
      case "more": {
        const id = value === "vacuum" ? this._config.entity : this._data?.entities?.[value];
        if (id) this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId: id } }));
        break;
      }
    }
  }

  _signature() {
    const keys = ["vacuum", ...this._watchKeys()];
    const parts = keys.map((k) => {
      const s = this._state(k);
      return s ? `${s.state}|${s.attributes.fan_speed ?? ""}|${s.attributes.status ?? ""}|${JSON.stringify(s.attributes.cleaning_job ?? "")}` : "-";
    });
    return [parts.join(","), this._selected.join("."), this._passes, this._busy, this._message, this._error,
      this._showRoute, this._wide, this._data ? this._fetched : 0, this._edv, this._view?.join(","), this._confirmPart].join("#");
  }

  _render() {
    if (!this.shadowRoot || !this._hass || !this._config) return;
    // a full render would drop the pointer capture of a drag in progress
    if (this._drag) return;
    const sig = this._signature();
    if (sig === this._sig) return;
    this._sig = sig;
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card class="${this._wide ? "wide" : ""}">${this._body()}</ha-card>`;
    this._bindMap();
    this._fitMap();
    // getBBox needs layout: the card is often rendered before it is attached
    requestAnimationFrame(() => this._fitMap());
  }

  // frame rooms and labels only: isolated wall pixels far from the house would shrink the map
  _fitMap() {
    const svg = this.shadowRoot.querySelector(".map svg");
    if (!svg) return;
    if (!this._fitBox || this._fitBox.fetched !== this._fetched) {
      try {
        const boxes = [...svg.querySelectorAll(".fit, .fit-labels")].map((g) => g.getBBox()).filter((b) => b.width > 0);
        if (!boxes.length) return;
        const x = Math.min(...boxes.map((b) => b.x));
        const y = Math.min(...boxes.map((b) => b.y));
        const w = Math.max(...boxes.map((b) => b.x + b.width)) - x;
        const h = Math.max(...boxes.map((b) => b.y + b.height)) - y;
        const pad = 6;
        this._fitBox = { box: [x - pad, y - pad, w + 2 * pad, h + 2 * pad], fetched: this._fetched };
      } catch (e) {
        return; // not rendered yet: keep the full map
      }
    }
    svg.setAttribute("viewBox", (this._view || this._fitBox.box).join(" "));
    this._refreshOverlay();
  }

  _body() {
    const vac = this._state("vacuum");
    if (!vac) return `<div class="empty">Entita' ${esc(this._config.entity)} non trovata</div>`;
    // the card asks again at every state change while it has no data
    if (this._error && !this._data && vac.state === "unavailable") {
      return `<div class="empty">Il robot non e' ancora collegato a Home Assistant: dopo un riavvio servono un paio di minuti. La scheda si aggiorna da sola.</div>`;
    }
    if (this._error && !this._data) return `<div class="empty">Mappa non disponibile: ${esc(this._error)}</div>`;
    return `
      ${this._header(vac)}
      <div class="main">
        <div class="map-col">${this._mapPanel()}</div>
        <div class="side">
          ${this._ed ? this._editSide() : `
          ${this._actions(vac)}
          ${this._roomsPanel()}
          ${this._modes(vac)}
          ${this._progress(vac)}
          ${this._lastCleaning()}
          ${this._base(vac)}
          ${this._maintenance()}
          ${this._settings()}`}
        </div>
      </div>`;
  }

  _header(vac) {
    const status = this._status(vac);
    const unavailable = vac.state === "unavailable";
    const battery = this._state("battery");
    const bat = battery && !isNaN(Number(battery.state)) ? Number(battery.state) : null;
    const batIcon = bat === null ? "mdi:battery-unknown"
      : `mdi:battery${this._docked() ? "-charging" : ""}${bat >= 95 ? "" : `-${Math.max(10, Math.round(bat / 10) * 10)}`}`;
    const chips = this._chips(vac);
    return `
      <div class="header">
        <div class="robot ${CLEANING.has(status) ? "active" : ""}" data-action="more" data-value="vacuum"><ha-icon icon="mdi:robot-vacuum"></ha-icon></div>
        <div class="title">
          <div class="name">${esc(this._config.title || vac.attributes.friendly_name || "Robot")}</div>
          <div class="status">${unavailable ? "Non raggiungibile" : esc(this._statusText(vac, status))}</div>
        </div>
        <div class="battery" data-action="more" data-value="battery"><ha-icon icon="${batIcon}"></ha-icon>${bat === null ? "-" : `${bat}%`}</div>
      </div>
      ${chips.length ? `<div class="chips">${chips.join("")}</div>` : ""}
      ${this._message ? `<div class="message">${esc(this._message)}</div>` : ""}`;
  }

  // --- robot specific hooks, overridden by the Roborock card ------------------

  _status(vac) {
    return vac?.attributes.status;
  }

  _statusText(vac, status) {
    if (this._jobInfo(vac) && PHASE[status]) return `Pulizia in corso: ${PHASE[status][1].toLowerCase()}`;
    return STATUS[status] || status || vac.state;
  }

  // the running cleaning: what it covers, start, mop washes, room the robot is in; null when idle
  _jobInfo(vac) {
    const job = vac?.attributes.cleaning_job;
    if (!job) return null;
    const names = Object.fromEntries((this._data?.rooms || []).map((r) => [r.id, r.name]));
    const scope = job.scope === "rooms" ? `Stanze: ${job.rooms.map((id) => names[id] || `Stanza ${id}`).join(", ")}`
      : job.scope === "house" ? "Tutta la casa" : "Stanze scelte dall'app Lefant o da una programmazione";
    return { scope, started: job.started, washes: job.mop_washes, where: null,
      hint: "Il robot non comunica in quale stanza si trova in questo momento." };
  }

  _docked() {
    return this._state("125")?.state === "on";
  }

  _watchKeys() {
    return ["battery", "status", "error", "cleaning_time", "cleaning_area", "171", "125", "114", "10", "14", "172", "15", "last_cleaning_end",
      ...BASE.map(([key]) => key), ...PARTS.map(([part]) => (part === "dust_bag" ? "dust_bag_emptyings" : `${part}_usage`))];
  }

  _resetEntity(part) {
    return this._data?.entities?.[`reset_${part}`];
  }

  _cleanRooms(rooms, repeats) {
    return this._call("Avvio", "vacuum", "send_command", {
      entity_id: this._config.entity,
      command: "clean_rooms",
      params: { rooms, repeats },
    });
  }

  _mapNote() {
    return `Mappa salvata dall'ultima pulizia completa${this._data.map_edited ? ", con le modifiche in anteprima" : ""}. Tocca le stanze da pulire.`;
  }

  _chips(vac) {
    const error = this._state("error");
    const chips = [];
    if (this._docked()) chips.push(`<span class="chip"><ha-icon icon="mdi:home-import-outline"></ha-icon>Sulla base</span>`);
    const mop = this._state("171");
    if (mop) chips.push(`<span class="chip ${mop.state === "on" ? "" : "warn"}"><ha-icon icon="${mop.state === "on" ? "mdi:water" : "mdi:water-off"}"></ha-icon>${mop.state === "on" ? "Mop montato" : "Mop assente"}</span>`);
    const baseAlerts = BASE.filter(([key]) => this._state(key)?.state === "on").map(([, label]) => label.toLowerCase());
    if (baseAlerts.length) chips.push(`<span class="chip warn"><ha-icon icon="mdi:home-alert-outline"></ha-icon>Base: ${esc(baseAlerts.join(", "))}</span>`);
    if (error && error.state !== "none" && error.state !== "unavailable" && error.state !== "unknown") {
      chips.push(`<span class="chip bad" data-action="more" data-value="error"><ha-icon icon="mdi:alert-circle"></ha-icon>${esc(ERRORS[error.state] || error.state)}</span>`);
    }
    return chips;
  }

  _mapPanel() {
    const map = this._data?.map;
    const rooms = this._data?.rooms || [];
    if (!map) {
      return `<div class="map empty-map"><ha-icon icon="mdi:floor-plan"></ha-icon><div>La mappa compare dopo la prima pulizia completa salvata sul cloud.</div></div>`;
    }
    const ed = this._ed;
    const picked = ed ? ed.pick : this._selected;
    const sel = new Set(picked);
    const roomPaths = rooms.filter((r) => r.path).map((r) => {
      const order = picked.indexOf(r.id);
      const color = ROOM_COLORS[r.id % ROOM_COLORS.length];
      return `<path class="room ${order >= 0 ? "selected" : ""}" data-action="room" data-value="${r.id}" d="${r.path}" style="--room:${color}"><title>${esc(r.name)}</title></path>`;
    }).join("");
    const labels = rooms.filter((r) => r.label).map((r) => {
      const order = ed ? -1 : this._selected.indexOf(r.id);
      const [x, y] = r.label;
      const badge = order >= 0
        ? `<circle cx="${x}" cy="${y - 13}" r="6.5" class="badge"/><text x="${x}" y="${y - 10.6}" class="badge-text">${order + 1}</text>`
        : "";
      return `<g class="label" data-action="room" data-value="${r.id}">${badge}<text x="${x}" y="${y}" class="room-name">${esc(r.name)}</text><text x="${x}" y="${y + 9}" class="room-area">${r.area} m²</text></g>`;
    }).join("");
    const [dx, dy] = map.dock;
    const vb = this._view || this._fitBox?.box || [-6, -20, map.width + 12, map.height + 26];
    const tools = ed ? this._editBar() : `
        <div class="map-tools">
          ${this._canEdit() ? `<button class="tool" data-action="edit"><ha-icon icon="mdi:pencil-ruler"></ha-icon>${this._editLabel()}</button>` : ""}
          <button class="tool" data-action="all">${sel.size ? "Deseleziona" : "Seleziona tutte"}</button>
          <button class="tool ${this._showRoute ? "on" : ""}" data-action="route"><ha-icon icon="mdi:vector-polyline"></ha-icon>Percorso</button>
        </div>`;
    const note = ed ? this._editContext()
      : `<div class="map-note">${esc(this._mapNote())}</div>`;
    return `
      <div class="map ${!ed && sel.size ? "has-selection" : ""} ${ed ? `editing tool-${ed.tool}` : ""}">
        ${ed ? tools : ""}
        <div class="canvas">
          <svg viewBox="${vb.join(" ")}" preserveAspectRatio="xMidYMid meet">
            <g class="fit">
              <path class="floor" d="${map.floor}"/>
              ${roomPaths}
            </g>
            <path class="walls" d="${map.walls}"/>
            ${this._showRoute && map.route && !ed ? `<path class="route" d="${map.route}"/>` : ""}
            <g class="dock"><circle cx="${dx}" cy="${dy}" r="6"/><path d="M${dx - 3} ${dy + 2.5}v-3l3-2.5 3 2.5v3z"/></g>
            ${map.robot ? `<g class="bot"><circle cx="${map.robot[0]}" cy="${map.robot[1]}" r="5"/><circle cx="${map.robot[0]}" cy="${map.robot[1]}" r="2"/></g>` : ""}
            <g class="fit-labels">${labels}</g>
            <g class="overlay"></g>
          </svg>
          ${ed ? `<div class="zoom">
            <button class="tool" data-action="ed-zoom" data-value="in" title="Ingrandisci"><ha-icon icon="mdi:plus"></ha-icon></button>
            <button class="tool" data-action="ed-zoom" data-value="out" title="Riduci"><ha-icon icon="mdi:minus"></ha-icon></button>
            <button class="tool" data-action="ed-zoom" data-value="fit" title="Tutta la casa"><ha-icon icon="mdi:fit-to-page-outline"></ha-icon></button>
          </div>` : ""}
        </div>
        ${ed ? "" : tools}
        ${note}
      </div>`;
  }

  _canEdit() {
    const status = this._status(this._state("vacuum"));
    return this._data?.editable && this._hass.user?.is_admin && !CLEANING.has(status) && !PAUSED.has(status) && !RETURNING.has(status);
  }

  // --- map editor ---------------------------------------------------------

  _editStart() {
    this._ed = {
      tool: this._editTools()[0],
      areas: JSON.parse(JSON.stringify(this._data.areas || [])),
      walls: JSON.parse(JSON.stringify(this._data.walls || [])),
      sel: null,
      zoneMode: 0,
      pick: [],
      line: null,
      busy: false,
      msg: null,
      confirm: null,
    };
    this._bump();
  }

  _bump() {
    this._edv += 1;
    this._sig = "";
    this._render();
  }

  _dirty() {
    const ed = this._ed;
    return {
      walls: JSON.stringify(ed.walls) !== JSON.stringify(this._data.walls || []),
      areas: JSON.stringify(ed.areas) !== JSON.stringify(this._data.areas || []),
    };
  }

  _editBar() {
    const ed = this._ed;
    const tool = (id, icon, label) =>
      `<button class="etool ${ed.tool === id ? "on" : ""}" data-action="ed-tool" data-value="${id}" ${ed.busy ? "disabled" : ""}><ha-icon icon="${icon}"></ha-icon><span>${label}</span></button>`;
    const tools = {
      move: ["mdi:cursor-default-click-outline", "Seleziona"],
      wall: ["mdi:wall", "Barriera"],
      zone: ["mdi:selection-ellipse-remove", "Zona vietata"],
      split: ["mdi:call-split", "Dividi"],
      merge: ["mdi:call-merge", "Unisci"],
      rename: ["mdi:form-textbox", "Rinomina"],
    };
    return `<div class="edit-bar">${this._editTools().map((id) => tool(id, ...tools[id])).join("")}</div>`;
  }

  _editTools() {
    return ["move", "wall", "zone", "split", "merge", "rename"];
  }

  _editLabel() {
    return "Modifica";
  }

  _editContext() {
    const ed = this._ed;
    const names = Object.fromEntries((this._data.rooms || []).map((r) => [r.id, r.name]));
    const busy = ed.busy ? "disabled" : "";
    let hint = "";
    let actions = "";
    const modes = () => `<span class="seg small">${AREA_MODES.map(([m, label]) =>
      `<button class="${ed.zoneMode === m ? "on" : ""}" data-action="ed-zone-mode" data-value="${m}">${label}</button>`).join("")}</span>`;
    switch (ed.tool) {
      case "move":
        if (ed.sel) {
          hint = ed.sel.kind === "area" ? "Trascina la zona o i suoi angoli." : "Trascina la barriera o le sue estremita'.";
          actions = `${ed.sel.kind === "area" ? modes() : ""}<button class="ebtn danger" data-action="ed-delete" ${busy}><ha-icon icon="mdi:delete-outline"></ha-icon>Elimina</button>`;
        } else {
          hint = "Tocca una barriera o una zona per spostarla, ridimensionarla o eliminarla. Con lo zoom, trascina per spostare la vista.";
        }
        break;
      case "wall":
        hint = "Trascina sulla mappa per tracciare una barriera: il robot non la attraversa.";
        break;
      case "zone":
        hint = "Trascina per disegnare un rettangolo. Scegli prima cosa vietare.";
        actions = modes();
        break;
      case "split":
        if (!ed.pick.length) hint = "Tocca la stanza da dividere.";
        else if (!ed.line) hint = `Traccia una linea che attraversa tutta la stanza ${esc(names[ed.pick[0]])}, da muro a muro.`;
        else {
          hint = `Dividere ${esc(names[ed.pick[0]])} lungo la linea?`;
          actions = `<button class="ebtn primary" data-action="ed-split" ${busy}><ha-icon icon="mdi:call-split"></ha-icon>Dividi</button><button class="ebtn" data-action="ed-pick-clear" ${busy}>Annulla</button>`;
        }
        break;
      case "merge":
        if (ed.pick.length < 2) hint = `Tocca due stanze vicine da unire${ed.pick.length ? `: ${esc(names[ed.pick[0]])} e...` : "."}`;
        else {
          hint = `Unire ${esc(names[ed.pick[0]])} e ${esc(names[ed.pick[1]])} in una stanza sola?`;
          actions = `<button class="ebtn primary" data-action="ed-merge" ${busy}><ha-icon icon="mdi:call-merge"></ha-icon>Unisci</button><button class="ebtn" data-action="ed-pick-clear" ${busy}>Annulla</button>`;
        }
        break;
      case "rename":
        if (!ed.pick.length) hint = "Tocca la stanza da rinominare.";
        else {
          hint = "";
          actions = `<input class="rename" maxlength="40" value="${esc(names[ed.pick[0]])}" aria-label="Nome della stanza"><button class="ebtn primary" data-action="ed-rename" ${busy}><ha-icon icon="mdi:check"></ha-icon>Salva</button><button class="ebtn" data-action="ed-pick-clear" ${busy}>Annulla</button>`;
        }
        break;
    }
    return `
      <div class="edit-context">
        ${hint ? `<div class="hint">${hint}</div>` : ""}
        ${actions ? `<div class="edit-actions">${actions}</div>` : ""}
        ${ed.msg ? `<div class="edit-msg ${ed.msg.error ? "bad" : ""}">${esc(ed.msg.text)}</div>` : ""}
      </div>`;
  }

  _editSide() {
    const ed = this._ed;
    const dirty = this._dirty();
    const changed = dirty.walls || dirty.areas;
    const busy = ed.busy ? "disabled" : "";
    const modeName = Object.fromEntries(AREA_MODES);
    const items = [
      ...ed.walls.map((w, i) => {
        const len = Math.hypot(w[1][0] - w[0][0], w[1][1] - w[0][1]) * PIXEL_M;
        return `<div class="item ${ed.sel?.kind === "wall" && ed.sel.i === i ? "on" : ""}"><span class="swatch wall"></span><button class="link" data-action="ed-select" data-value="wall:${i}">Barriera ${i + 1}<span class="muted">${len.toFixed(1)} m</span></button><button class="icon-btn" data-action="ed-delete-item" data-value="wall:${i}" ${busy} title="Elimina"><ha-icon icon="mdi:delete-outline"></ha-icon></button></div>`;
      }),
      ...ed.areas.map((a, i) => {
        const xs = a.points.map((p) => p[0]);
        const ys = a.points.map((p) => p[1]);
        const size = `${((Math.max(...xs) - Math.min(...xs)) * PIXEL_M).toFixed(1)} × ${((Math.max(...ys) - Math.min(...ys)) * PIXEL_M).toFixed(1)} m`;
        return `<div class="item ${ed.sel?.kind === "area" && ed.sel.i === i ? "on" : ""}"><span class="swatch" style="--zone:${AREA_COLORS[a.mode]}"></span><button class="link" data-action="ed-select" data-value="area:${i}">Zona ${i + 1}: ${modeName[a.mode]}<span class="muted">${size}</span></button><button class="icon-btn" data-action="ed-delete-item" data-value="area:${i}" ${busy} title="Elimina"><ha-icon icon="mdi:delete-outline"></ha-icon></button></div>`;
      }),
    ];
    return `
      <div class="panel">
        <div class="panel-title">Modifica mappa<button class="ebtn" data-action="ed-exit" ${busy}><ha-icon icon="mdi:close"></ha-icon>Chiudi</button></div>
        <div class="legend">
          <span><span class="swatch wall"></span>Barriera</span>
          ${AREA_MODES.map(([m, label]) => `<span><span class="swatch" style="--zone:${AREA_COLORS[m]}"></span>${label}</span>`).join("")}
        </div>
        ${items.length ? `<div class="items">${items.join("")}</div>` : `<div class="muted">Nessuna barriera o zona vietata.</div>`}
        <div class="save-row">
          <button class="ebtn primary" data-action="ed-save" ${changed && !ed.busy ? "" : "disabled"}>${ed.busy ? `<span class="spinner"></span>` : `<ha-icon icon="mdi:content-save-outline"></ha-icon>`}Salva sul robot</button>
          <button class="ebtn" data-action="ed-discard" ${changed && !ed.busy ? "" : "disabled"}>Annulla modifiche</button>
        </div>
        <div class="muted">Barriere e zone si salvano insieme con "Salva sul robot". Divisione, unione e nomi delle stanze si applicano subito.
        ${this._data.map_edited ? "La mappa mostra le stanze modificate in anteprima: quella esatta arriva con la prossima pulizia completa." : ""}</div>
      </div>`;
  }

  _onEditClick(action, value) {
    const ed = this._ed;
    if (ed.busy && action !== "ed-zoom") return;
    switch (action) {
      case "room": {
        const id = Number(value);
        if (ed.tool === "split" || ed.tool === "rename") {
          ed.pick = [id];
          ed.line = null;
        } else if (ed.tool === "merge") {
          ed.pick = ed.pick.includes(id) ? ed.pick.filter((r) => r !== id) : [...ed.pick, id].slice(-2);
        } else {
          ed.sel = null;
        }
        ed.msg = null;
        break;
      }
      case "ed-tool":
        ed.tool = value;
        ed.pick = [];
        ed.line = null;
        ed.sel = value === "move" ? ed.sel : null;
        ed.msg = null;
        break;
      case "ed-zone-mode": {
        ed.zoneMode = Number(value);
        if (ed.tool === "move" && ed.sel?.kind === "area") ed.areas[ed.sel.i].mode = ed.zoneMode;
        break;
      }
      case "ed-select": {
        const [kind, i] = value.split(":");
        ed.tool = "move";
        ed.sel = { kind, i: Number(i) };
        if (kind === "area") ed.zoneMode = ed.areas[Number(i)].mode;
        break;
      }
      case "ed-delete":
      case "ed-delete-item": {
        const target = action === "ed-delete" ? ed.sel : { kind: value.split(":")[0], i: Number(value.split(":")[1]) };
        if (!target) return;
        (target.kind === "area" ? ed.areas : ed.walls).splice(target.i, 1);
        ed.sel = null;
        break;
      }
      case "ed-discard":
        ed.areas = JSON.parse(JSON.stringify(this._data.areas || []));
        ed.walls = JSON.parse(JSON.stringify(this._data.walls || []));
        ed.sel = null;
        ed.msg = null;
        break;
      case "ed-exit":
        if (this._dirty().walls || this._dirty().areas) {
          if (ed.confirm !== "exit") {
            ed.confirm = "exit";
            ed.msg = { text: "Ci sono modifiche non salvate: tocca di nuovo Chiudi per scartarle.", error: true };
            break;
          }
        }
        this._ed = null;
        this._view = null;
        break;
      case "ed-pick-clear":
        ed.pick = [];
        ed.line = null;
        break;
      case "ed-save":
        this._editSave();
        return;
      case "ed-split":
        this._roomOp({ type: "lefant/split_room", room_id: ed.pick[0], line: ed.line }, "Stanza divisa.");
        return;
      case "ed-merge":
        this._roomOp({ type: "lefant/merge_rooms", room_ids: ed.pick }, "Stanze unite.");
        return;
      case "ed-rename": {
        const input = this.shadowRoot.querySelector("input.rename");
        this._roomOp({ type: "lefant/rename_room", room_id: ed.pick[0], name: input ? input.value : "" }, "Nome salvato.");
        return;
      }
      case "ed-zoom":
        this._zoom(value === "in" ? 0.7 : value === "out" ? 1 / 0.7 : null);
        return;
    }
    if (action !== "ed-exit" && ed) ed.confirm = null;
    this._bump();
  }

  async _editCall(msg) {
    return this._hass.callWS({ entity_id: this._config.entity, ...msg });
  }

  async _editSave() {
    const ed = this._ed;
    ed.busy = true;
    ed.msg = null;
    this._bump();
    try {
      // barriers and no-go areas travel in the same robot command
      this._data = await this._editCall({ type: "lefant/set_zones", areas: ed.areas, walls: ed.walls });
      ed.areas = JSON.parse(JSON.stringify(this._data.areas || []));
      ed.walls = JSON.parse(JSON.stringify(this._data.walls || []));
      ed.sel = null;
      ed.msg = { text: "Salvato: il robot ha confermato barriere e zone." };
    } catch (e) {
      ed.msg = { text: `Non salvato. ${editError(e)}`, error: true };
    } finally {
      ed.busy = false;
      this._fetched = Date.now();
      this._bump();
    }
  }

  async _roomOp(msg, okText) {
    const ed = this._ed;
    ed.busy = true;
    ed.msg = null;
    this._bump();
    try {
      this._data = await this._editCall(msg);
      ed.pick = [];
      ed.line = null;
      ed.msg = { text: okText };
      this._fitBox = null;
    } catch (e) {
      ed.msg = { text: editError(e), error: true };
    } finally {
      ed.busy = false;
      this._fetched = Date.now();
      this._bump();
    }
  }

  // barriers, no-go areas, handles and the shape being drawn; redrawn alone while dragging
  _overlay() {
    const ed = this._ed;
    const areas = ed ? ed.areas : this._data?.areas || [];
    const walls = ed ? ed.walls : this._data?.walls || [];
    const r = this._handleRadius();
    const pts = (p) => p.map((q) => q.join(",")).join(" ");
    let out = areas.map((a, i) => {
      const on = ed?.sel?.kind === "area" && ed.sel.i === i;
      return `<polygon class="zone ${on ? "on" : ""}" data-kind="area" data-i="${i}" points="${pts(a.points)}" style="--zone:${AREA_COLORS[a.mode] || AREA_COLORS[0]}"/>`;
    }).join("");
    out += walls.map((w, i) => {
      const on = ed?.sel?.kind === "wall" && ed.sel.i === i;
      const [[x1, y1], [x2, y2]] = w;
      return `<line class="vwall-hit" data-kind="wall" data-i="${i}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/><line class="vwall ${on ? "on" : ""}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`;
    }).join("");
    if (ed?.sel) {
      const shape = ed.sel.kind === "area" ? ed.areas[ed.sel.i]?.points : ed.walls[ed.sel.i];
      (shape || []).forEach(([x, y], h) => {
        out += `<circle class="handle" data-kind="handle" data-h="${h}" cx="${x}" cy="${y}" r="${r}"/>`;
      });
    }
    if (ed?.line) {
      const [[x1, y1], [x2, y2]] = ed.line;
      out += `<line class="split-line" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`;
    }
    const d = this._drag;
    if (d && (d.type === "draw-wall" || d.type === "draw-split")) {
      const [[x1, y1], [x2, y2]] = [d.a, d.b];
      const len = Math.hypot(x2 - x1, y2 - y1) * PIXEL_M;
      out += `<line class="${d.type === "draw-wall" ? "vwall draft" : "split-line"}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`;
      out += `<text class="measure" style="font-size:${r * 1.4}px" x="${x2}" y="${y2 - r * 1.6}">${len.toFixed(1)} m</text>`;
    } else if (d && d.type === "draw-zone") {
      const [x, y, w, h] = rectOf(d.a, d.b);
      out += `<rect class="zone draft" x="${x}" y="${y}" width="${w}" height="${h}" style="--zone:${AREA_COLORS[this._ed.zoneMode]}"/>`;
      out += `<text class="measure" style="font-size:${r * 1.4}px" x="${x + w / 2}" y="${y - r}">${(w * PIXEL_M).toFixed(1)} × ${(h * PIXEL_M).toFixed(1)} m</text>`;
    }
    return out;
  }

  _refreshOverlay() {
    const g = this.shadowRoot?.querySelector(".map svg .overlay");
    if (g) g.innerHTML = this._overlay();
  }

  _handleRadius() {
    const svg = this.shadowRoot?.querySelector(".map svg");
    const vb = this._view || this._fitBox?.box;
    const width = svg?.getBoundingClientRect().width;
    return vb && width ? (9 * vb[2]) / width : 4;
  }

  _bindMap() {
    const svg = this.shadowRoot.querySelector(".map svg");
    if (!svg || !this._ed) return;
    svg.addEventListener("pointerdown", (ev) => this._onDown(ev, svg));
    svg.addEventListener("pointermove", (ev) => this._onMove(ev, svg));
    svg.addEventListener("pointerup", (ev) => this._onUp(ev, svg));
    svg.addEventListener("pointercancel", (ev) => this._onUp(ev, svg));
    svg.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      this._zoom(ev.deltaY < 0 ? 0.85 : 1 / 0.85, this._toMap(ev, svg));
    }, { passive: false });
  }

  _toMap(ev, svg) {
    const p = new DOMPoint(ev.clientX, ev.clientY).matrixTransform(svg.getScreenCTM().inverse());
    return [Math.round(p.x * 10) / 10, Math.round(p.y * 10) / 10];
  }

  _zoom(factor, center) {
    const base = this._fitBox?.box;
    if (!base) return;
    if (factor === null) {
      this._view = null;
    } else {
      const [x, y, w, h] = this._view || base;
      const nw = Math.min(base[2], Math.max(base[2] / 8, w * factor));
      const nh = (nw / w) * h;
      const [cx, cy] = center || [x + w / 2, y + h / 2];
      const nx = cx - ((cx - x) / w) * nw;
      const ny = cy - ((cy - y) / h) * nh;
      this._view = nw >= base[2] ? null : [nx, ny, nw, nh].map((v) => Math.round(v * 10) / 10);
    }
    this._sig = "";
    this._render();
  }

  _onDown(ev, svg) {
    const ed = this._ed;
    if (!ed || ed.busy) return;
    this._ptrs.set(ev.pointerId, [ev.clientX, ev.clientY]);
    if (this._ptrs.size === 2) {
      const [a, b] = [...this._ptrs.values()];
      this._drag = { type: "pinch", dist: Math.hypot(a[0] - b[0], a[1] - b[1]), view: this._view || this._fitBox?.box, moved: true };
      return;
    }
    const p = this._toMap(ev, svg);
    const target = ev.composedPath()[0];
    const kind = target?.dataset?.kind;
    const i = Number(target?.dataset?.i);
    const start = { x: ev.clientX, y: ev.clientY };
    if (ed.tool === "move") {
      if (kind === "handle" && ed.sel) {
        this._drag = { type: "handle", h: Number(target.dataset.h), start, p, orig: this._selShape() };
      } else if (kind === "area" || kind === "wall") {
        ed.sel = { kind, i };
        if (kind === "area") ed.zoneMode = ed.areas[i].mode;
        this._drag = { type: "move", start, p, orig: this._selShape() };
        this._refreshOverlay();
      } else if (this._view) {
        this._drag = { type: "pan", start, view: [...this._view], scale: this._view[2] / svg.getBoundingClientRect().width };
      } else {
        return;
      }
    } else if (ed.tool === "wall") {
      this._drag = { type: "draw-wall", start, a: p, b: p };
    } else if (ed.tool === "zone") {
      this._drag = { type: "draw-zone", start, a: p, b: p };
    } else if (ed.tool === "split" && ed.pick.length) {
      this._drag = { type: "draw-split", start, a: p, b: p };
    } else {
      return;
    }
    svg.setPointerCapture(ev.pointerId);
    ev.preventDefault();
  }

  _selShape() {
    const ed = this._ed;
    const shape = ed.sel.kind === "area" ? ed.areas[ed.sel.i].points : ed.walls[ed.sel.i];
    return JSON.parse(JSON.stringify(shape));
  }

  _onMove(ev, svg) {
    const d = this._drag;
    if (!d) return;
    if (this._ptrs.has(ev.pointerId)) this._ptrs.set(ev.pointerId, [ev.clientX, ev.clientY]);
    if (d.type === "pinch") {
      if (this._ptrs.size < 2 || !d.view) return;
      const [a, b] = [...this._ptrs.values()];
      const dist = Math.hypot(a[0] - b[0], a[1] - b[1]);
      const mid = this._toMap({ clientX: (a[0] + b[0]) / 2, clientY: (a[1] + b[1]) / 2 }, svg);
      this._view = d.view;
      this._zoomNoRender(d.dist / dist, mid, svg);
      return;
    }
    if (!d.moved && Math.hypot(ev.clientX - d.start.x, ev.clientY - d.start.y) < 4) return;
    d.moved = true;
    if (d.type === "pan") {
      const dx = (ev.clientX - d.start.x) * d.scale;
      const dy = (ev.clientY - d.start.y) * d.scale;
      this._view = [d.view[0] - dx, d.view[1] - dy, d.view[2], d.view[3]];
      svg.setAttribute("viewBox", this._view.join(" "));
      return;
    }
    const p = this._toMap(ev, svg);
    const ed = this._ed;
    if (d.type === "draw-wall" || d.type === "draw-split" || d.type === "draw-zone") {
      d.b = p;
    } else if (d.type === "move") {
      const dx = p[0] - d.p[0];
      const dy = p[1] - d.p[1];
      const moved = d.orig.map(([x, y]) => [Math.round((x + dx) * 10) / 10, Math.round((y + dy) * 10) / 10]);
      if (ed.sel.kind === "area") ed.areas[ed.sel.i].points = moved;
      else ed.walls[ed.sel.i] = moved;
    } else if (d.type === "handle") {
      if (ed.sel.kind === "wall") {
        ed.walls[ed.sel.i][d.h] = p;
      } else {
        // keep the rectangle: the opposite corner stays where it is
        const opp = d.orig[(d.h + 2) % 4];
        const [x, y, w, h] = rectOf(opp, p);
        ed.areas[ed.sel.i].points = rectPoints(x, y, w, h);
      }
    }
    this._refreshOverlay();
  }

  _zoomNoRender(factor, center, svg) {
    const base = this._fitBox?.box;
    const [x, y, w, h] = this._view || base;
    const nw = Math.min(base[2], Math.max(base[2] / 8, w * factor));
    const nh = (nw / w) * h;
    const [cx, cy] = center;
    this._view = [cx - ((cx - x) / w) * nw, cy - ((cy - y) / h) * nh, nw, nh];
    svg.setAttribute("viewBox", this._view.join(" "));
  }

  _onUp(ev, svg) {
    this._ptrs.delete(ev.pointerId);
    const d = this._drag;
    if (!d) return;
    if (d.type === "pinch") {
      if (this._ptrs.size) return;
      this._drag = null;
      if (this._view && this._fitBox && this._view[2] >= this._fitBox.box[2]) this._view = null;
      this._sig = "";
      this._render();
      return;
    }
    this._drag = null;
    const ed = this._ed;
    if (d.moved) this._suppressClick = true;
    setTimeout(() => { this._suppressClick = false; }, 400);
    const len = d.a && d.b ? Math.hypot(d.b[0] - d.a[0], d.b[1] - d.a[1]) : 0;
    if (d.type === "draw-wall" && len >= 4) {
      ed.walls.push([d.a, d.b]);
      ed.sel = { kind: "wall", i: ed.walls.length - 1 };
      ed.tool = "move";
    } else if (d.type === "draw-zone") {
      const [x, y, w, h] = rectOf(d.a, d.b);
      if (w >= 4 && h >= 4) {
        ed.areas.push({ mode: ed.zoneMode, points: rectPoints(x, y, w, h) });
        ed.sel = { kind: "area", i: ed.areas.length - 1 };
        ed.tool = "move";
      }
    } else if (d.type === "draw-split" && len >= 4) {
      ed.line = [d.a, d.b];
    }
    if (d.type === "pan") {
      this._sig = "";
      this._render();
      return;
    }
    ed.msg = null;
    ed.confirm = null;
    this._bump();
  }

  _actions(vac) {
    const status = this._status(vac);
    const off = vac.state === "unavailable" || this._busy ? "disabled" : "";
    const busy = (label) => (this._busy === label ? `<span class="spinner"></span>` : "");
    const n = this._selected.length;
    let primary;
    let secondary = [];
    // between two mop washes the robot reports "charging" for a moment: the cleaning is still running
    if (CLEANING.has(status) || (this._jobInfo(vac) && !PAUSED.has(status) && !RETURNING.has(status))) {
      primary = `<button class="primary" data-action="pause" ${off}>${busy("Pausa")}<ha-icon icon="mdi:pause"></ha-icon>Pausa</button>`;
      secondary = ["stop", "dock"];
    } else if (PAUSED.has(status)) {
      primary = `<button class="primary" data-action="resume" ${off}>${busy("Ripresa")}<ha-icon icon="mdi:play"></ha-icon>Riprendi</button>`;
      secondary = ["stop", "dock"];
    } else if (RETURNING.has(status)) {
      primary = `<button class="primary" data-action="pause" ${off}>${busy("Pausa")}<ha-icon icon="mdi:pause"></ha-icon>Ferma il rientro</button>`;
      secondary = ["stop"];
    } else {
      const label = n ? `Pulisci ${n === 1 ? "1 stanza" : `${n} stanze`}` : "Pulisci tutta la casa";
      primary = `<button class="primary" data-action="start" ${off}>${busy("Avvio")}<ha-icon icon="mdi:play"></ha-icon>${label}</button>`;
      secondary = this._docked() ? [] : ["dock"];
    }
    const sec = {
      stop: `<button data-action="stop" ${off}>${busy("Stop")}<ha-icon icon="mdi:stop"></ha-icon>Stop</button>`,
      dock: `<button data-action="dock" ${off}>${busy("Rientro")}<ha-icon icon="mdi:home-import-outline"></ha-icon>Base</button>`,
    };
    return `
      <div class="panel actions">
        ${primary}
        <div class="row">
          ${secondary.map((k) => sec[k]).join("")}
          <button data-action="locate" ${off}>${busy("Trova robot")}<ha-icon icon="mdi:map-marker-radius"></ha-icon>Trova</button>
        </div>
      </div>`;
  }

  _roomsPanel() {
    const rooms = this._data?.rooms || [];
    if (!rooms.length) return "";
    const status = this._status(this._state("vacuum"));
    const idle = !CLEANING.has(status) && !PAUSED.has(status) && !RETURNING.has(status);
    const chips = rooms.map((r) => {
      const order = this._selected.indexOf(r.id);
      return `<button class="room-chip ${order >= 0 ? "on" : ""}" data-action="room" data-value="${r.id}" style="--room:${ROOM_COLORS[r.id % ROOM_COLORS.length]}">
        ${order >= 0 ? `<span class="num">${order + 1}</span>` : `<span class="dot"></span>`}${esc(r.name)}${r.area ? `<span class="muted">${r.area} m²</span>` : ""}</button>`;
    }).join("");
    const passes = this._selected.length && idle
      ? `<div class="sub">Passate <span class="seg small">${[1, 2, 3].map((p) => `<button class="${p === this._passes ? "on" : ""}" data-action="passes" data-value="${p}">${p}×</button>`).join("")}</span></div>`
      : "";
    return `
      <div class="panel">
        <div class="panel-title">Stanze<span class="muted">${this._selected.length ? `${this._selected.length} selezionate, pulite in quest'ordine` : "nessuna selezionata: pulisce tutta la casa"}</span></div>
        <div class="room-chips">${chips}</div>
        ${passes}
      </div>`;
  }

  _modes(vac) {
    const fan = vac.attributes.fan_speed;
    const water = this._state("10")?.state;
    const off = vac.state === "unavailable" || this._busy ? "disabled" : "";
    const seg = (items, current, action) => `<div class="seg">${items.map(([v, label, icon]) =>
      `<button class="${v === current ? "on" : ""}" data-action="${action}" data-value="${v}" ${off}><ha-icon icon="${icon}"></ha-icon><span>${label}</span></button>`).join("")}</div>`;
    let hint = "";
    if (fan === "closed" && water === "closed") hint = "Aspirazione e acqua spente: il robot non pulisce.";
    else if (fan === "closed") hint = "Solo lavaggio.";
    else if (water === "closed" || this._state("171")?.state === "off") hint = "Solo aspirazione.";
    else hint = "Aspira e lava insieme.";
    return `
      <div class="panel">
        <div class="panel-title">Aspirazione</div>
        ${seg(SUCTION, fan, "suction")}
        <div class="panel-title">Acqua del mop</div>
        ${seg(WATER, water, "water")}
        <div class="hint">${hint}</div>
      </div>`;
  }

  _progress(vac) {
    const status = this._status(vac);
    const job = this._jobInfo(vac);
    if (!job && !CLEANING.has(status) && !PAUSED.has(status) && !RETURNING.has(status)) return "";
    let [icon, text, detail] = PHASE[status] || ["mdi:robot-vacuum", this._statusText(vac, status), ""];
    if (!job && RETURNING.has(status)) [icon, text, detail] = ["mdi:home-import-outline", "Pulizia finita: torna alla base", ""];
    if (job?.where && PHASE[status]?.[1] === "Sta pulendo") text = `Sta pulendo: ${job.where}`;
    const t = Number(this._state("cleaning_time")?.state);
    const a = Number(this._state("cleaning_area")?.state);
    const since = job?.started ? `dalle ${new Date(job.started).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}` : "";
    return `
      <div class="panel now">
        <div class="panel-title">${job ? "Pulizia in corso" : "Pulizia"}<span class="muted">${since}</span></div>
        <div class="phase"><ha-icon icon="${icon}"></ha-icon><span class="text"><b>${esc(text)}</b>${detail ? `<span class="muted">${esc(detail)}</span>` : ""}</span></div>
        ${job?.scope ? `<div class="scope"><ha-icon icon="mdi:floor-plan"></ha-icon>${esc(job.scope)}</div>` : ""}
        <div class="stats">
          <div><ha-icon icon="mdi:timer-outline"></ha-icon><b>${isNaN(t) ? "-" : Math.round(t)}</b> min</div>
          <div><ha-icon icon="mdi:texture-box"></ha-icon><b>${isNaN(a) ? "-" : Math.round(a)}</b> m²</div>
          ${job?.washes ? `<div><ha-icon icon="mdi:water-sync"></ha-icon><b>${job.washes}</b> ${job.washes === 1 ? "lavaggio" : "lavaggi"} del mop</div>` : ""}
        </div>
        ${job?.hint ? `<div class="hint">${esc(job.hint)}</div>` : ""}
      </div>`;
  }

  _lastCleaning() {
    const last = this._data?.last_cleaning;
    if (!last) return "";
    const names = Object.fromEntries((this._data.rooms || []).map((r) => [r.id, r.name]));
    const rooms = !last.rooms ? "" : last.rooms.length
      ? last.rooms.map((id) => names[id] || last.names?.[id] || `Stanza ${id}`).join(", ") : "tutta la casa";
    return `
      <div class="panel last" data-action="more" data-value="${this._lastCleaningKey()}">
        <div class="panel-title">Ultima pulizia<span class="muted">${esc(relTime(last.end))}</span></div>
        <div class="stats">
          <div><ha-icon icon="mdi:timer-check-outline"></ha-icon><b>${last.minutes}</b> min</div>
          <div><ha-icon icon="mdi:texture-box"></ha-icon><b>${last.area}</b> m²</div>
        </div>
        ${rooms ? `<div class="muted">${esc(rooms)}</div>` : ""}
        ${this._history()}
      </div>`;
  }

  _history() {
    return "";
  }

  _lastCleaningKey() {
    return "last_cleaning_end";
  }

  _base(vac) {
    const rows = BASE.map(([key, label, icon]) => {
      const st = this._state(key);
      if (!st) return "";
      const known = st.state === "on" || st.state === "off";
      const alert = st.state === "on";
      return `
        <div class="part" data-action="more" data-value="${key}">
          <ha-icon icon="${icon}"></ha-icon>
          <span class="text">${label}</span>
          <span class="pill ${alert ? "warn" : known ? "ok" : ""}">${alert ? "Da controllare" : known ? "OK" : "Non ancora letto"}</span>
        </div>`;
    }).join("");
    if (!rows) return "";
    const status = this._status(vac);
    return `
      <div class="panel">
        <div class="panel-title">Base<span class="muted">${BASE_STATUS.has(status) ? esc(STATUS[status]) : ""}</span></div>
        <div class="parts">${rows}</div>
        <div class="hint">La base avvisa quando un serbatoio o il sacchetto manca. Il detersivo non viene segnalato dal robot.</div>
      </div>`;
  }

  _maintenance() {
    const rows = PARTS.map(([part, label, icon]) => {
      const key = part === "dust_bag" ? "dust_bag_emptyings" : `${part}_usage`;
      const st = this._state(key);
      if (!st || !this._resetEntity(part)) return "";
      let value = Number(st.state);
      let text = "-";
      if (!isNaN(value)) {
        if (part === "dust_bag") {
          text = `${value} ${value === 1 ? "svuotamento" : "svuotamenti"}`;
        } else {
          if (st.attributes.unit_of_measurement === "min") value /= 60;
          text = `${value < 10 ? value.toFixed(1).replace(".", ",") : Math.round(value)} h`;
        }
      }
      const confirm = this._confirmPart === part;
      return `
        <div class="part">
          <ha-icon icon="${icon}"></ha-icon>
          <span class="text" data-action="more" data-value="${key}">${label}<span class="muted">${text}</span></span>
          <button class="ebtn ${confirm ? "primary" : ""}" data-action="replaced" data-value="${part}" ${this._busy ? "disabled" : ""}>${confirm ? "Confermi?" : "Sostituito"}</button>
        </div>`;
    }).join("");
    if (!rows) return "";
    return `
      <div class="panel">
        <div class="panel-title">Manutenzione</div>
        <div class="parts">${rows}</div>
        <div class="hint">Il robot non manda l'usura dei pezzi: Home Assistant conta le ore di pulizia e gli svuotamenti da quando premi Sostituito.</div>
      </div>`;
  }

  _settings() {
    const rows = SETTINGS.map(([key, label, desc, icon]) => {
      const st = this._state(key);
      if (!st) return "";
      const on = st.state === "on";
      const off = st.state === "unavailable" || this._busy ? "disabled" : "";
      return `
        <button class="setting" role="switch" aria-checked="${on}" data-action="setting" data-value="${key}" ${off}>
          <ha-icon icon="${icon}"></ha-icon>
          <span class="text"><span>${label}</span><span class="muted">${desc}</span></span>
          <span class="toggle ${on ? "on" : ""}"><span></span></span>
        </button>`;
    }).join("");
    return rows ? `<div class="panel"><div class="panel-title">Impostazioni</div>${rows}</div>` : "";
  }
}

// --- Roborock -----------------------------------------------------------------
// Same card for the Roborock integration of HA: `lefant/map` reads its map file and
// room list, the entity keys are the unique ids of the Roborock entities without the robot id.

// Roborock states as the closest Lefant state, so the shared panels know what the robot is doing
const RR_STATUS = {
  starting: "cleaning", cleaning: "cleaning", robot_status_mopping: "cleaning", clean_mop_cleaning: "cleaning",
  clean_mop_mopping: "cleaning", spot_cleaning: "part_clean", segment_cleaning: "part_clean", segment_mopping: "part_clean",
  segment_clean_mop_cleaning: "part_clean", segment_clean_mop_mopping: "part_clean", zoned_cleaning: "zone_clean",
  zoned_mopping: "zone_clean", zoned_clean_mop_cleaning: "zone_clean", zoned_clean_mop_mopping: "zone_clean",
  going_to_target: "goto_pos", mapping: "fastmaping", returning_home: "goto_charge", docking: "goto_charge",
  paused: "paused", charging: "charging", charging_complete: "charge_done", idle: "standby",
  emptying_the_bin: "dust_collection", washing_the_mop: "wash_mop", going_to_wash_the_mop: "goto_wash",
};
const RR_ACTIVITY = { cleaning: "cleaning", returning: "goto_charge", paused: "paused", docked: "charging" };

const RR_SUCTION = {
  gentle: ["Delicata", "mdi:fan-speed-1"],
  quiet: ["Silenziosa", "mdi:fan-speed-1"],
  silent: ["Silenziosa", "mdi:fan-speed-1"],
  balanced: ["Bilanciata", "mdi:fan-speed-2"],
  standard: ["Standard", "mdi:fan-speed-2"],
  medium: ["Media", "mdi:fan-speed-2"],
  turbo: ["Turbo", "mdi:fan-speed-3"],
  max: ["Max", "mdi:fan-plus"],
  max_plus: ["Max+", "mdi:fan-plus"],
  off: ["Spenta", "mdi:fan-off"],
};
const RR_WATER = [["off", "Spenta", "mdi:water-off"], ["low", "Bassa", "mdi:water-outline"], ["medium", "Media", "mdi:water"], ["high", "Alta", "mdi:waves"]];
const RR_MODE = [["vacuum", "Solo aspira", "mdi:robot-vacuum"], ["vac_and_mop", "Aspira e lava", "mdi:robot-vacuum-variant"]];
const RR_ROUTE = [["standard", "Standard"], ["deep", "Profondo"], ["deep_plus", "Profondo+"]];
const RR_EMPTY = [["smart", "Smart"], ["light", "Leggero"], ["balanced", "Bilanciato"], ["max", "Massimo"]];
// [part, label, icon, hours of a new part as in the Roborock app, button text]
const RR_PARTS = [
  ["main_brush", "Spazzola principale", "mdi:brush", 300, "Sostituita"],
  ["side_brush", "Spazzola laterale", "mdi:brush", 200, "Sostituita"],
  ["filter", "Filtro", "mdi:air-filter", 150, "Sostituito"],
  ["sensor", "Sensori", "mdi:eye-outline", 30, "Puliti"],
];
const RR_RESET = { main_brush: "main_brush", side_brush: "side_brush", filter: "air_filter", sensor: "sensor" };

class RoborockVacuumCard extends LefantVacuumCard {
  _init() {
    super._init();
    this.shadowRoot.addEventListener("change", (ev) => {
      const el = ev.composedPath().find((n) => n.dataset && n.dataset.change);
      if (el?.dataset.change === "volume" && this._data?.entities?.volume) {
        this._call("Volume", "number", "set_value", { entity_id: this._data.entities.volume, value: Number(el.value) });
      }
    });
  }

  _status(vac) {
    const st = this._state("status")?.state;
    return RR_STATUS[st] || RR_ACTIVITY[vac?.state] || "standby";
  }

  _statusText(vac) {
    const st = this._state("status");
    return st && st.state !== "unknown" && st.state !== "unavailable" ? this._hass.formatEntityState(st) : this._hass.formatEntityState(vac);
  }

  _docked() {
    return this._state("vacuum")?.state === "docked" || this._state("battery_charging")?.state === "on";
  }

  _watchKeys() {
    return ["battery", "status", "vacuum_error", "dock_error", "cleaning_time", "cleaning_area", "battery_charging",
      "water_box_carriage_status", "water_box_status", "water_shortage", "water_box_mode", "cleaning_mode", "mop_mode",
      "dust_collection_mode", "dust_emptying", "selected_map", "dnd_switch", "dnd_start_time", "dnd_end_time", "child_lock",
      "volume", "last_clean_end", "total_cleaning_count", "current_room", ...RR_PARTS.map(([part]) => `${part}_time_left`)];
  }

  _jobInfo(vac) {
    const status = this._status(vac);
    if (!CLEANING.has(status) && !PAUSED.has(status)) return null;
    const room = this._state("current_room");
    const where = room && !["unknown", "unavailable"].includes(room.state) ? this._hass.formatEntityState(room) : null;
    const scope = status === "part_clean" ? "Stanze scelte" : status === "zone_clean" ? "Zona scelta" : "Tutta la casa";
    return { scope, started: null, washes: null, where, hint: null };
  }

  _resetEntity(part) {
    return this._data?.entities?.[`reset_${RR_RESET[part]}_consumable`];
  }

  _cleanRooms(rooms, repeats) {
    return this._call("Avvio", "vacuum", "send_command", {
      entity_id: this._config.entity,
      command: "app_segment_clean",
      params: [{ segments: rooms, repeat: repeats }],
    });
  }

  _canEdit() {
    const status = this._status(this._state("vacuum"));
    return this._data?.renamable && this._hass.user?.is_admin && !CLEANING.has(status) && !PAUSED.has(status) && !RETURNING.has(status);
  }

  _editTools() {
    return ["rename"];
  }

  _editLabel() {
    return "Nomi stanze";
  }

  _editSide() {
    return `
      <div class="panel">
        <div class="panel-title">Nomi delle stanze<button class="ebtn" data-action="ed-exit" ${this._ed.busy ? "disabled" : ""}><ha-icon icon="mdi:close"></ha-icon>Chiudi</button></div>
        <div class="muted">Tocca una stanza sulla mappa e scrivi il nome. I nomi restano in Home Assistant, sul robot non cambia nulla.
        Lascia il campo vuoto per tornare al nome del robot.</div>
      </div>`;
  }

  _mapNote() {
    const when = this._data.map_updated ? `, aggiornata ${relTime(this._data.map_updated)}` : "";
    return `Mappa del robot${when}. Tocca le stanze da pulire.`;
  }

  _chips(vac) {
    const chips = [];
    const on = (key) => this._state(key)?.state === "on";
    const chip = (cls, icon, text, key) => `<span class="chip ${cls}" ${key ? `data-action="more" data-value="${key}"` : ""}><ha-icon icon="${icon}"></ha-icon>${esc(text)}</span>`;
    if (this._docked()) chips.push(chip("", "mdi:home-import-outline", "Sulla base"));
    const mop = this._state("water_box_carriage_status");
    if (mop) chips.push(mop.state === "on" ? chip("", "mdi:water", "Mop montato") : chip("", "mdi:water-off", "Mop non montato"));
    if (this._state("water_box_status")?.state === "off") chips.push(chip("warn", "mdi:cup-off-outline", "Serbatoio acqua assente", "water_box_status"));
    if (on("water_shortage")) chips.push(chip("warn", "mdi:water-alert-outline", "Acqua finita", "water_shortage"));
    const err = this._state("vacuum_error");
    if (err && !["none", "unknown", "unavailable"].includes(err.state)) chips.push(chip("bad", "mdi:alert-circle", this._hass.formatEntityState(err), "vacuum_error"));
    const dock = this._state("dock_error");
    if (dock && !["ok", "unknown", "unavailable"].includes(dock.state)) chips.push(chip("bad", "mdi:home-alert-outline", `Base: ${this._hass.formatEntityState(dock)}`, "dock_error"));
    return chips;
  }

  _onClick(ev) {
    const el = ev.composedPath().find((n) => n.dataset && n.dataset.action);
    if (!el || el.hasAttribute("disabled")) return;
    const { action, value } = el.dataset;
    const ent = this._data?.entities || {};
    switch (action) {
      case "water":
        this._call("Acqua", "select", "select_option", { entity_id: ent.water_box_mode, option: value });
        return;
      case "rr-select": {
        const [key, option] = value.split("|");
        // switching map changes the map the robot cleans with: ask a second tap
        if (key === "selected_map" && this._confirmPart !== value) {
          this._confirmPart = value;
          clearTimeout(this._confirmTimer);
          this._confirmTimer = setTimeout(() => {
            this._confirmPart = null;
            this._render();
          }, 5000);
          this._render();
          return;
        }
        this._confirmPart = null;
        if (ent[key]) this._call("Impostazione", "select", "select_option", { entity_id: ent[key], option });
        return;
      }
      case "rr-empty":
        if (ent.dust_emptying) this._call("Svuotamento", "switch", "turn_on", { entity_id: ent.dust_emptying });
        return;
    }
    super._onClick(ev);
  }

  _modes(vac) {
    const off = vac.state === "unavailable" || this._busy ? "disabled" : "";
    const seg = (items, current, action, prefix = "") => `<div class="seg">${items.map(([v, label, icon]) =>
      `<button class="${v === current ? "on" : ""}" data-action="${action}" data-value="${prefix}${v}" ${off}>${icon ? `<ha-icon icon="${icon}"></ha-icon>` : ""}<span>${label}</span></button>`).join("")}</div>`;
    const fan = vac.attributes.fan_speed;
    const fans = (vac.attributes.fan_speed_list || []).map((v) => [v, ...(RR_SUCTION[v] || [v, "mdi:fan"])]);
    const water = this._state("water_box_mode");
    const mode = this._state("cleaning_mode");
    const route = this._state("mop_mode");
    const mopOn = this._state("water_box_carriage_status")?.state === "on";
    // segmented buttons of a Roborock select entity, only for the options the robot offers
    const select = (key, st, items) => seg(items.filter(([v]) => st.attributes.options?.includes(v)), st.state, "rr-select", `${key}|`);
    let hint = mopOn ? "Mop montato: lava mentre aspira." : "Mop non montato: solo aspirazione.";
    if (mode?.state === "vacuum") hint = "Solo aspirazione, anche con il mop montato.";
    return `
      <div class="panel">
        ${mode && mode.state !== "unavailable" ? `<div class="panel-title">Modalita'</div>${select("cleaning_mode", mode, RR_MODE)}` : ""}
        <div class="panel-title">Aspirazione</div>
        ${seg(fans, fan, "suction")}
        ${water && water.state !== "unavailable" ? `<div class="panel-title">Acqua del mop</div>${seg(RR_WATER.filter(([v]) => water.attributes.options?.includes(v)), water.state, "water")}` : ""}
        ${route && route.state !== "unavailable" ? `<div class="panel-title">Percorso del mop</div>${select("mop_mode", route, RR_ROUTE)}` : ""}
        <div class="hint">${hint}</div>
      </div>`;
  }

  _history() {
    const count = this._state("total_cleaning_count")?.state;
    const hours = Number(this._state("total_cleaning_time")?.state);
    const area = Number(this._state("total_cleaning_area")?.state);
    if (!count || isNaN(hours)) return "";
    return `<div class="muted">In totale ${esc(count)} pulizie, ${Math.round(hours)} h, ${Math.round(area).toLocaleString("it-IT")} m²</div>`;
  }

  _lastCleaningKey() {
    return "last_clean_end";
  }

  _base(vac) {
    const dock = this._state("dock_error");
    const mode = this._state("dust_collection_mode");
    const emptying = this._state("dust_emptying");
    if (!dock && !mode && !emptying) return "";
    const off = vac.state === "unavailable" || this._busy ? "disabled" : "";
    const status = this._status(vac);
    const ok = dock?.state === "ok";
    const rows = [];
    if (dock) {
      rows.push(`
        <div class="part" data-action="more" data-value="dock_error">
          <ha-icon icon="mdi:home-outline"></ha-icon><span class="text">Stato della base</span>
          <span class="pill ${ok ? "ok" : "warn"}">${ok ? "OK" : esc(this._hass.formatEntityState(dock))}</span>
        </div>`);
    }
    for (const [key, label, icon, onText, offText] of [
      ["water_box_status", "Serbatoio acqua", "mdi:cup-water", "Montato", "Assente"],
      ["water_shortage", "Acqua nel serbatoio", "mdi:water", "Finita", "OK"],
    ]) {
      const st = this._state(key);
      if (!st || st.state === "unavailable") continue;
      const bad = key === "water_shortage" ? st.state === "on" : st.state === "off";
      rows.push(`
        <div class="part" data-action="more" data-value="${key}">
          <ha-icon icon="${icon}"></ha-icon><span class="text">${label}</span>
          <span class="pill ${bad ? "warn" : "ok"}">${st.state === "on" ? onText : offText}</span>
        </div>`);
    }
    const busyEmpty = emptying?.state === "on" || status === "dust_collection";
    return `
      <div class="panel">
        <div class="panel-title">Base<span class="muted">${BASE_STATUS.has(status) ? esc(this._statusText(vac)) : ""}</span></div>
        <div class="parts">${rows.join("")}</div>
        ${mode && mode.state !== "unavailable" ? `<div class="sub">Svuotamento</div>${`<div class="seg">${RR_EMPTY.filter(([v]) => mode.attributes.options?.includes(v)).map(([v, label]) =>
          `<button class="${v === mode.state ? "on" : ""}" data-action="rr-select" data-value="dust_collection_mode|${v}" ${off}><span>${label}</span></button>`).join("")}</div>`}` : ""}
        ${emptying ? `<button class="ebtn" data-action="rr-empty" ${off || (busyEmpty ? "disabled" : "")}><ha-icon icon="mdi:delete-empty-outline"></ha-icon>${busyEmpty ? "Svuotamento in corso" : "Svuota ora"}</button>` : ""}
      </div>`;
  }

  _maintenance() {
    const rows = RR_PARTS.map(([part, label, icon, life, done]) => {
      const key = `${part}_time_left`;
      const st = this._state(key);
      if (!st) return "";
      const left = Number(st.state);
      const known = !isNaN(left);
      const pct = known ? Math.max(0, Math.min(100, Math.round((left / life) * 100))) : 0;
      const confirm = this._confirmPart === part;
      const reset = this._resetEntity(part);
      return `
        <div class="part">
          <ha-icon icon="${icon}"></ha-icon>
          <span class="text" data-action="more" data-value="${key}">${label}<span class="muted">${known ? (left > 0 ? `${Math.round(left)} h rimaste` : "Da sostituire") : "-"}</span>
            <span class="bar ${known && pct <= 10 ? "low" : ""}"><span style="width:${pct}%"></span></span></span>
          ${reset ? `<button class="ebtn ${confirm ? "primary" : ""}" data-action="replaced" data-value="${part}" ${this._busy ? "disabled" : ""}>${confirm ? "Confermi?" : done}</button>` : ""}
        </div>`;
    }).join("");
    if (!rows) return "";
    return `
      <div class="panel">
        <div class="panel-title">Manutenzione</div>
        <div class="parts">${rows}</div>
        <div class="hint">Ore rimaste calcolate dal robot. Premi il pulsante dopo aver sostituito o pulito il pezzo.</div>
      </div>`;
  }

  _settings() {
    const off = this._busy ? "disabled" : "";
    const toggle = (key, label, desc, icon) => {
      const st = this._state(key);
      if (!st) return "";
      const on = st.state === "on";
      return `
        <button class="setting" role="switch" aria-checked="${on}" data-action="setting" data-value="${key}" ${st.state === "unavailable" ? "disabled" : off}>
          <ha-icon icon="${icon}"></ha-icon>
          <span class="text"><span>${label}</span><span class="muted">${desc}</span></span>
          <span class="toggle ${on ? "on" : ""}"><span></span></span>
        </button>`;
    };
    const hm = (key) => (this._state(key)?.state || "").slice(0, 5);
    const dnd = hm("dnd_start_time") && hm("dnd_end_time") ? `Dalle ${hm("dnd_start_time")} alle ${hm("dnd_end_time")}, tocca l'orario per cambiarlo` : "Niente pulizie e voce di notte";
    const volume = this._state("volume");
    const maps = this._state("selected_map");
    return `
      <div class="panel">
        <div class="panel-title">Impostazioni</div>
        ${toggle("dnd_switch", "Non disturbare", "Niente pulizie programmate e voce in quelle ore", "mdi:bell-sleep-outline")}
        ${this._state("dnd_start_time") ? `<div class="sub dnd"><span class="muted">${esc(dnd)}</span><span>
          <button class="ebtn" data-action="more" data-value="dnd_start_time">${esc(hm("dnd_start_time"))}</button>
          <button class="ebtn" data-action="more" data-value="dnd_end_time">${esc(hm("dnd_end_time"))}</button></span></div>` : ""}
        ${toggle("child_lock", "Blocco bambini", "Disattiva i tasti sul robot", "mdi:lock-outline")}
        ${volume && volume.state !== "unavailable" ? `
          <label class="setting volume"><ha-icon icon="mdi:volume-high"></ha-icon><span class="text"><span>Volume voce</span></span>
            <input type="range" min="${volume.attributes.min ?? 0}" max="${volume.attributes.max ?? 100}" step="${volume.attributes.step ?? 1}" value="${Number(volume.state)}" data-change="volume" ${off}>
            <span class="muted">${Math.round(Number(volume.state))}%</span></label>` : ""}
        ${maps && maps.state !== "unavailable" && (maps.attributes.options || []).length > 1 ? `
          <div class="sub">Mappa in uso</div>
          <div class="seg">${maps.attributes.options.map((v) => `<button class="${v === maps.state ? "on" : ""}" data-action="rr-select" data-value="selected_map|${esc(v)}" ${off}><span>${this._confirmPart === `selected_map|${v}` ? "Confermi?" : esc(v)}</span></button>`).join("")}</div>
          <div class="hint">Cambia la mappa che il robot usa per pulire: scegli quella del piano dove si trova.</div>` : ""}
      </div>`;
  }
}

const STYLE = `
  :host { display: block; }
  ha-card { padding: 16px; overflow: hidden; }
  .empty { padding: 24px; color: var(--secondary-text-color); }
  .header { display: flex; align-items: center; gap: 12px; }
  .robot { width: 44px; height: 44px; border-radius: 50%; display: grid; place-items: center; cursor: pointer;
    background: color-mix(in srgb, var(--primary-color) 14%, transparent); color: var(--primary-color); flex: none; }
  .robot.active { animation: pulse 1.6s ease-in-out infinite; }
  @keyframes pulse { 50% { box-shadow: 0 0 0 6px color-mix(in srgb, var(--primary-color) 18%, transparent); } }
  .title { flex: 1; min-width: 0; }
  .name { font-size: 18px; font-weight: 600; color: var(--primary-text-color); }
  .status { color: var(--secondary-text-color); font-size: 14px; }
  .battery { display: flex; align-items: center; gap: 4px; font-weight: 600; cursor: pointer; color: var(--primary-text-color); }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .chip { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px 3px 6px; border-radius: 999px; font-size: 12px;
    background: color-mix(in srgb, var(--primary-text-color) 7%, transparent); color: var(--primary-text-color); --mdc-icon-size: 16px; }
  .chip.warn { color: var(--warning-color); background: color-mix(in srgb, var(--warning-color) 14%, transparent); }
  .chip.bad { color: var(--error-color); background: color-mix(in srgb, var(--error-color) 14%, transparent); cursor: pointer; }
  .message { margin-top: 10px; padding: 8px 12px; border-radius: 10px; font-size: 13px; color: var(--error-color);
    background: color-mix(in srgb, var(--error-color) 10%, transparent); }
  .main { display: grid; gap: 16px; margin-top: 14px; grid-template-columns: minmax(0, 1fr); }
  .map-col, .side { min-width: 0; }
  .wide .main { grid-template-columns: minmax(0, 1.6fr) minmax(300px, 1fr); align-items: start; }
  .side { display: grid; gap: 12px; }
  .map { position: relative; border-radius: 14px; background: color-mix(in srgb, var(--primary-text-color) 4%, transparent); padding: 8px; }
  .map svg { width: 100%; height: auto; max-height: 70vh; display: block; touch-action: manipulation; }
  .empty-map { display: grid; place-items: center; gap: 8px; padding: 48px 16px; text-align: center; color: var(--secondary-text-color); --mdc-icon-size: 40px; }
  .floor { fill: color-mix(in srgb, var(--primary-text-color) 12%, transparent); }
  .walls { fill: var(--primary-text-color); opacity: 0.75; pointer-events: none; }
  .room { fill: var(--room); fill-opacity: 0.55; cursor: pointer; transition: fill-opacity .15s; }
  .room:hover { fill-opacity: 0.75; }
  .has-selection .room { fill-opacity: 0.22; }
  .room.selected, .has-selection .room.selected { fill: var(--primary-color); fill-opacity: 0.7; }
  ha-card:not(.wide) .room-name { font-size: 11px; }
  ha-card:not(.wide) .room-area { display: none; }
  .route { fill: none; stroke: var(--primary-color); stroke-width: 0.7; stroke-linejoin: round; opacity: 0.8; pointer-events: none; }
  .dock circle { fill: var(--success-color, #2ea043); stroke: var(--card-background-color, #fff); stroke-width: 1.5; }
  .dock path { fill: #fff; }
  .bot circle { fill: var(--card-background-color, #fff); stroke: var(--primary-color); stroke-width: 2; vector-effect: non-scaling-stroke; }
  .bot circle + circle { fill: var(--primary-color); stroke: none; }
  .label { cursor: pointer; }
  .label text { text-anchor: middle; paint-order: stroke; stroke: var(--card-background-color, #fff); stroke-width: 2.4px; stroke-linejoin: round; }
  .room-name { font-size: 8.5px; font-weight: 600; fill: var(--primary-text-color); }
  .room-area { font-size: 6.5px; fill: var(--secondary-text-color); }
  .badge { fill: var(--primary-color); }
  .label text.badge-text { font-size: 7px; font-weight: 700; fill: var(--text-primary-color, #fff); stroke: none; }
  .map-tools { position: absolute; top: 12px; right: 12px; display: flex; gap: 6px; }
  .map-note { font-size: 12px; color: var(--secondary-text-color); padding: 4px 6px 0; }
  button { font: inherit; color: inherit; border: none; cursor: pointer; background: none; }
  button[disabled] { opacity: 0.45; cursor: default; }
  .tool { display: inline-flex; align-items: center; gap: 4px; padding: 5px 10px; border-radius: 999px; font-size: 12px; --mdc-icon-size: 16px;
    background: var(--card-background-color, #fff); color: var(--primary-text-color); box-shadow: 0 1px 3px rgba(0,0,0,.18); }
  .tool.on { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .panel { border-radius: 14px; padding: 12px; background: color-mix(in srgb, var(--primary-text-color) 4%, transparent); display: grid; gap: 10px; }
  .panel-title { font-weight: 600; font-size: 14px; color: var(--primary-text-color); display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }
  .muted { color: var(--secondary-text-color); font-weight: 400; font-size: 12px; }
  .hint { font-size: 12px; color: var(--secondary-text-color); }
  .actions .primary { width: 100%; display: flex; align-items: center; justify-content: center; gap: 8px; padding: 14px; border-radius: 12px;
    background: var(--primary-color); color: var(--text-primary-color, #fff); font-weight: 600; font-size: 16px; }
  .actions .row { display: flex; gap: 8px; }
  .actions .row button { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 8px 4px; border-radius: 12px; font-size: 12px;
    background: color-mix(in srgb, var(--primary-text-color) 7%, transparent); color: var(--primary-text-color); }
  .room-chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .room-chip { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 999px; font-size: 13px;
    background: var(--card-background-color, #fff); color: var(--primary-text-color); border: 1px solid var(--divider-color); }
  .room-chip .muted { font-size: 11px; }
  .room-chip.on { border-color: var(--primary-color); background: color-mix(in srgb, var(--primary-color) 14%, var(--card-background-color, #fff)); }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--room); }
  .num { width: 18px; height: 18px; border-radius: 50%; display: grid; place-items: center; font-size: 11px; font-weight: 700;
    background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .sub { display: flex; align-items: center; justify-content: space-between; font-size: 13px; color: var(--primary-text-color); }
  .seg { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; gap: 4px; padding: 4px; border-radius: 12px;
    background: color-mix(in srgb, var(--primary-text-color) 6%, transparent); }
  .seg button { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 7px 2px; border-radius: 9px; font-size: 11px;
    color: var(--secondary-text-color); --mdc-icon-size: 20px; }
  .seg button.on { background: var(--card-background-color, #fff); color: var(--primary-color); font-weight: 600; box-shadow: 0 1px 3px rgba(0,0,0,.15); }
  .seg.small { display: inline-grid; }
  .seg.small button { padding: 4px 12px; font-size: 13px; }
  .stats { display: flex; gap: 16px; align-items: center; color: var(--primary-text-color); --mdc-icon-size: 18px; }
  .stats > div { display: flex; align-items: center; gap: 4px; }
  .stats b { font-size: 16px; }
  .last { cursor: pointer; }
  .phase { display: flex; align-items: center; gap: 10px; color: var(--primary-text-color); --mdc-icon-size: 28px; }
  .phase ha-icon { color: var(--primary-color); }
  .phase .text { display: grid; font-size: 15px; }
  .scope { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--primary-text-color); --mdc-icon-size: 18px; }
  .bar { display: block; height: 4px; border-radius: 2px; margin-top: 4px; background: color-mix(in srgb, var(--primary-text-color) 10%, transparent); overflow: hidden; }
  .bar > span { display: block; height: 100%; background: var(--primary-color); }
  .bar.low > span { background: var(--warning-color); }
  .volume input { flex: 1; min-width: 80px; accent-color: var(--primary-color); }
  .dnd { flex-wrap: wrap; gap: 6px; }
  .parts { display: grid; gap: 4px; }
  .part { display: flex; align-items: center; gap: 10px; min-height: 36px; color: var(--primary-text-color); --mdc-icon-size: 20px; }
  .part[data-action] { cursor: pointer; }
  .part .text { flex: 1; display: grid; font-size: 14px; cursor: pointer; }
  .pill { padding: 3px 10px; border-radius: 999px; font-size: 12px; color: var(--secondary-text-color);
    background: color-mix(in srgb, var(--primary-text-color) 7%, transparent); }
  .pill.ok { color: var(--success-color, #2ea043); background: color-mix(in srgb, var(--success-color, #2ea043) 14%, transparent); }
  .pill.warn { color: var(--warning-color); background: color-mix(in srgb, var(--warning-color) 16%, transparent); font-weight: 600; }
  .setting { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; padding: 6px 0; color: var(--primary-text-color); }
  .setting .text { flex: 1; display: grid; }
  .toggle { width: 38px; height: 22px; border-radius: 11px; background: var(--divider-color); position: relative; flex: none; transition: background .15s; }
  .toggle span { position: absolute; top: 3px; left: 3px; width: 16px; height: 16px; border-radius: 50%; background: #fff; transition: left .15s; box-shadow: 0 1px 2px rgba(0,0,0,.3); }
  .toggle.on { background: var(--primary-color); }
  .toggle.on span { left: 19px; }
  .canvas { position: relative; }
  .map:not(.editing) .overlay { pointer-events: none; }
  .map.editing svg { touch-action: none; user-select: none; -webkit-user-select: none; }
  .map.tool-wall svg, .map.tool-zone svg, .map.tool-split svg { cursor: crosshair; }
  .zoom { position: absolute; right: 6px; bottom: 6px; display: flex; flex-direction: column; gap: 6px; }
  .zoom .tool { padding: 6px; }
  .edit-bar { display: flex; gap: 4px; overflow-x: auto; padding-bottom: 8px; scrollbar-width: none; }
  .etool { display: flex; flex-direction: column; align-items: center; gap: 2px; min-width: 66px; padding: 6px 8px; border-radius: 10px;
    font-size: 11px; color: var(--primary-text-color); background: var(--card-background-color, #fff); --mdc-icon-size: 20px; flex: 1 0 auto; }
  .etool.on { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .zone { fill: var(--zone); fill-opacity: 0.22; stroke: var(--zone); stroke-width: 1.5; vector-effect: non-scaling-stroke; stroke-dasharray: 4 3; }
  .map.editing .zone { cursor: move; }
  .zone.on { fill-opacity: 0.38; stroke-dasharray: none; stroke-width: 2.5; }
  .zone.draft { pointer-events: none; }
  .vwall { stroke: #e5484d; stroke-width: 4; stroke-linecap: round; vector-effect: non-scaling-stroke; pointer-events: none; }
  .vwall.on { stroke-width: 6; }
  .vwall.draft { stroke-dasharray: 6 4; }
  .vwall-hit { stroke: transparent; stroke-width: 22; vector-effect: non-scaling-stroke; pointer-events: stroke; }
  .map.editing .vwall-hit { cursor: move; }
  .handle { fill: #fff; stroke: var(--primary-color); stroke-width: 2.5; vector-effect: non-scaling-stroke; cursor: grab; }
  .split-line { stroke: var(--primary-color); stroke-width: 3; stroke-dasharray: 8 5; vector-effect: non-scaling-stroke; pointer-events: none; }
  .measure { text-anchor: middle; font-weight: 600; fill: var(--primary-text-color); paint-order: stroke;
    stroke: var(--card-background-color, #fff); stroke-width: 3px; pointer-events: none; }
  .edit-context { display: grid; gap: 8px; padding: 8px 4px 0; }
  .edit-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .ebtn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 12px; border-radius: 10px; font-size: 13px; --mdc-icon-size: 18px;
    background: color-mix(in srgb, var(--primary-text-color) 8%, transparent); color: var(--primary-text-color); }
  .ebtn.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .ebtn.danger { color: var(--error-color); }
  .edit-msg { font-size: 13px; color: var(--success-color, #2ea043); }
  .edit-msg.bad { color: var(--error-color); }
  input.rename { flex: 1; min-width: 140px; padding: 8px 10px; border-radius: 10px; border: 1px solid var(--divider-color);
    background: var(--card-background-color, #fff); color: var(--primary-text-color); font: inherit; }
  .legend { display: flex; flex-wrap: wrap; gap: 12px; font-size: 12px; color: var(--secondary-text-color); }
  .legend > span { display: inline-flex; align-items: center; gap: 5px; }
  .swatch { width: 14px; height: 10px; border-radius: 3px; flex: none; background: color-mix(in srgb, var(--zone) 35%, transparent); border: 1.5px solid var(--zone); }
  .swatch.wall { background: #e5484d; height: 4px; border: none; }
  .items { display: grid; gap: 2px; }
  .item { display: flex; align-items: center; gap: 8px; padding: 4px 6px; border-radius: 8px; }
  .item.on { background: color-mix(in srgb, var(--primary-color) 12%, transparent); }
  .item .link { flex: 1; display: flex; justify-content: space-between; gap: 8px; text-align: left; font-size: 13px; color: var(--primary-text-color); }
  .icon-btn { --mdc-icon-size: 18px; color: var(--secondary-text-color); padding: 4px; }
  .save-row { display: flex; gap: 8px; flex-wrap: wrap; }
  .spinner { width: 14px; height: 14px; border-radius: 50%; border: 2px solid currentColor; border-right-color: transparent; animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
`;

if (!customElements.get("lefant-vacuum-card")) {
  try {
    customElements.define("lefant-vacuum-card", LefantVacuumCard);
  } catch (e) {
    // already defined by an older copy loaded before the frontend registry
    console.warn("lefant-vacuum-card:", e.message);
  }
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "lefant-vacuum-card",
    name: "Lefant robot",
    description: "Mappa con stanze selezionabili e comandi del robot Lefant",
  });
}

if (!customElements.get("roborock-vacuum-card")) {
  try {
    customElements.define("roborock-vacuum-card", RoborockVacuumCard);
  } catch (e) {
    console.warn("roborock-vacuum-card:", e.message);
  }
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "roborock-vacuum-card",
    name: "Roborock robot",
    description: "Mappa con stanze selezionabili e comandi del robot Roborock",
  });
}
