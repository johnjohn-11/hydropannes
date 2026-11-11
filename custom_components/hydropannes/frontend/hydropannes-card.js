/*
 * Hydro-Pannes card: the outage tracker of one location, laid out like the Info-pannes site.
 *
 * Config: `entity` is the Info-pannes sensor of the location. The other entities are found on the same device by their translation key, so renamed entities keep working. `entities` can override any of them by key, `title` replaces the device name.
 */

const UNKNOWN = new Set(["unknown", "unavailable", ""]);

const TEXT = {
  fr: {
    start: "Début",
    end: "Fin",
    end_estimated: "Rétablissement prévu",
    between: (a, b) => `entre ${a} et ${b}`,
    restoration: "Rétablissement",
    cause: "Cause",
    customers: "Adresses touchées",
    duration: "Durée",
    planned: "Interruption planifiée",
    latest: "Au plus tard",
    fallback: "En cas de report",
    next: "Suivantes",
    unavailable: "Données indisponibles",
    missing: "Entité introuvable",
    // Official wording of the site's outage tracker (TRACKERS.ETAPE-PANNE).
    steps: {
      debut: "Début de la panne",
      analyse: "Évaluation des travaux requis",
      en_route: "Équipe désignée",
      en_cours: "Travaux en cours sur le réseau électrique",
      en_cours_purs: "Réalisation des travaux par ordre de priorité",
      analyse_en_cours: "Heure de rétablissement en cours d’évaluation",
      en_revision: "Heure de rétablissement en cours de révision",
      prevision: "Rétablissement prévu",
      retabli: "Service rétabli",
    },
  },
  en: {
    start: "Start",
    end: "End",
    end_estimated: "Expected restoration",
    between: (a, b) => `between ${a} and ${b}`,
    restoration: "Restoration",
    cause: "Cause",
    customers: "Affected addresses",
    duration: "Duration",
    planned: "Planned interruption",
    latest: "At the latest",
    fallback: "In case of postponement",
    next: "Next",
    unavailable: "Data unavailable",
    missing: "Entity not found",
    steps: {
      debut: "Start of power outage",
      analyse: "Assessment of work required",
      en_route: "Crew assigned",
      en_cours: "Work in progress on the power grid",
      en_cours_purs: "Work proceeding in order of priority",
      analyse_en_cours: "Estimated restoration time under analysis",
      en_revision: "Estimated restoration time under review",
      prevision: "Power restoration expected",
      retabli: "Power restored",
    },
  },
};

// Info-pannes state → [theme color variable, icon].
const STATUS = {
  aucune_panne: ["--success-color", "mdi:lightning-bolt"],
  panne_en_cours: ["--error-color", "mdi:flash-off"],
  panne_majeure: ["--error-color", "mdi:flash-alert"],
  reprise_graduelle: ["--warning-color", "mdi:flash-triangle"],
  service_retabli: ["--success-color", "mdi:check-circle"],
  interruption_planifiee_en_cours: ["--warning-color", "mdi:hammer-wrench"],
  interruption_planifiee_a_venir: ["--info-color", "mdi:calendar-clock"],
  interruption_planifiee_reportee: ["--info-color", "mdi:calendar-arrow-right"],
  interruption_planifiee_terminee: ["--disabled-color", "mdi:calendar-check"],
  interruption_planifiee_annulee: ["--disabled-color", "mdi:calendar-remove"],
};

// The tracker is drawn for an unplanned outage, from its start to the restoration.
const TRACKED = new Set(["panne_en_cours", "panne_majeure", "reprise_graduelle", "service_retabli"]);

// Intervention state → index of the current step, as the site's panneCodeEtape pipe does with codeIntervention: R (crew on the way) → 2, L (on site) → 3, anything else → 1. The start (0) is always passed.
const STEP_INDEX = {
  equipe_designee: 2,
  travaux_en_cours: 3,
  travaux_par_priorite: 3,
  reprise_graduelle: 3,
};

// Restoration state → wording of the last step while the outage lasts.
const LAST_STEP = {
  en_evaluation: "analyse_en_cours",
  en_revision: "en_revision",
  prevu: "prevision",
};

// unit_of_measurement → seconds, the duration sensor's unit can be changed in the UI.
const UNIT_SECONDS = { s: 1, min: 60, h: 3600, d: 86400 };

const escape = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

class HydroPannesCard extends HTMLElement {
  static getConfigForm() {
    return {
      schema: [
        {
          name: "entity",
          required: true,
          selector: { entity: { domain: "sensor", integration: "hydropannes" } },
        },
        { name: "title", selector: { text: {} } },
      ],
    };
  }

  static getStubConfig(hass) {
    const found = Object.values(hass.entities || {}).find(
      (e) => e.platform === "hydropannes" && e.translation_key === "info_pannes",
    );
    return { entity: found ? found.entity_id : "" };
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("entity is required: the Info-pannes sensor of the location");
    }
    this._config = config;
    this._signature = undefined;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 4;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  /** Map translation key → entity id for the entities of the location's device. */
  _entities() {
    const registry = this._hass.entities || {};
    const main = registry[this._config.entity];
    const found = { info_pannes: this._config.entity };
    if (main && main.device_id) {
      for (const entry of Object.values(registry)) {
        if (entry.device_id === main.device_id && entry.translation_key) {
          found[entry.translation_key] = entry.entity_id;
        }
      }
    }
    return { ...found, ...(this._config.entities || {}) };
  }

  _state(entities, key) {
    const id = entities[key];
    return id ? this._hass.states[id] : undefined;
  }

  _known(stateObj) {
    return stateObj && !UNKNOWN.has(stateObj.state) ? stateObj : undefined;
  }

  _format(stateObj) {
    return this._hass.formatEntityState ? this._hass.formatEntityState(stateObj) : stateObj.state;
  }

  _locale() {
    return (this._hass.locale && this._hass.locale.language) || this._hass.language || "fr";
  }

  _dateTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return undefined;
    return new Intl.DateTimeFormat(this._locale(), {
      day: "numeric",
      month: "short",
      hour: "numeric",
      minute: "2-digit",
    }).format(date);
  }

  _time(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return undefined;
    return new Intl.DateTimeFormat(this._locale(), { hour: "numeric", minute: "2-digit" }).format(
      date,
    );
  }

  _duration(stateObj) {
    const factor = UNIT_SECONDS[stateObj.attributes.unit_of_measurement || "s"];
    if (!factor) return this._format(stateObj);
    const total = Math.round((Number(stateObj.state) * factor) / 60);
    if (!Number.isFinite(total)) return undefined;
    const hours = Math.floor(total / 60);
    const minutes = total % 60;
    return hours ? `${hours} h ${String(minutes).padStart(2, "0")} min` : `${minutes} min`;
  }

  _render() {
    if (!this._config || !this._hass) return;
    const entities = this._entities();
    const signature = Object.values(entities)
      .map((id) => {
        const s = this._hass.states[id];
        return s ? `${id}:${s.state}:${s.last_updated}` : `${id}:`;
      })
      .concat(this._locale())
      .join("|");
    if (signature === this._signature) return;
    this._signature = signature;

    const text = TEXT[this._locale().startsWith("fr") ? "fr" : "en"];
    const info = this._hass.states[this._config.entity];
    const registryEntry = (this._hass.entities || {})[this._config.entity];
    const device = registryEntry && (this._hass.devices || {})[registryEntry.device_id];
    const title =
      this._config.title ||
      (device && (device.name_by_user || device.name)) ||
      (info && info.attributes.friendly_name) ||
      this._config.entity;

    let color = "--disabled-color";
    let icon = "mdi:help-circle-outline";
    let label = text.missing;
    if (info) {
      label = UNKNOWN.has(info.state) ? text.unavailable : this._format(info);
      [color, icon] = STATUS[info.state] || [color, icon];
    }

    const sections = [];
    if (info && TRACKED.has(info.state)) {
      sections.push(this._tracker(text, entities, info));
    }
    if (info && info.state !== "aucune_panne" && !UNKNOWN.has(info.state)) {
      sections.push(this._details(text, entities));
    }
    sections.push(this._planned(text, entities));

    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header" style="--status: var(${color}, var(--primary-color))">
          <div class="badge"><ha-icon icon="${icon}"></ha-icon></div>
          <div class="heading">
            <div class="title">${escape(title)}</div>
            <div class="status">${escape(label)}</div>
          </div>
        </div>
        ${sections.join("")}
      </ha-card>`;
    this.shadowRoot.querySelector(".header").addEventListener("click", () => {
      this.dispatchEvent(
        new CustomEvent("hass-more-info", {
          bubbles: true,
          composed: true,
          detail: { entityId: this._config.entity },
        }),
      );
    });
  }

  _tracker(text, entities, info) {
    const intervention = this._known(this._state(entities, "statut_intervention"));
    const slug = intervention ? intervention.state : undefined;
    const restored = info.state === "service_retabli" || slug === "service_retabli";
    const current = restored ? 4 : (STEP_INDEX[slug] ?? 1);
    const major = info.state === "panne_majeure" || slug === "travaux_par_priorite";
    const restoration = this._known(this._state(entities, "retablissement"));
    const last = restored
      ? "retabli"
      : LAST_STEP[restoration && restoration.state] || "prevision";
    const steps = ["debut", "analyse", "en_route", major ? "en_cours_purs" : "en_cours", last];
    const items = steps.map((step, index) => {
      const cls = index < current || restored ? "done" : index === current ? "current" : "";
      return `<li class="${cls}"><span class="dot"></span><span>${escape(text.steps[step])}</span></li>`;
    });
    const description = intervention && intervention.attributes.description;
    return `<ol class="tracker">${items.join("")}</ol>${
      description ? `<p class="note">${escape(description)}</p>` : ""
    }`;
  }

  _details(text, entities) {
    const rows = [];
    const add = (label, value, note) => {
      if (value === undefined || value === null || value === "") return;
      rows.push(
        `<div class="row"><span class="label">${escape(label)}</span><span class="value">${escape(
          value,
        )}${note ? `<span class="note">${escape(note)}</span>` : ""}</span></div>`,
      );
    };

    const start = this._known(this._state(entities, "date_debut"));
    if (start) add(text.start, this._dateTime(start.state));

    const end = this._known(this._state(entities, "date_fin"));
    if (end) {
      const earliest = end.attributes.fin_estimee_min;
      const estimated = end.attributes.icon === "mdi:clock-alert";
      const value = earliest
        ? text.between(this._dateTime(earliest), this._time(end.state))
        : this._dateTime(end.state);
      add(estimated ? text.end_estimated : text.end, value);
    }

    const restoration = this._known(this._state(entities, "retablissement"));
    if (restoration) {
      add(text.restoration, this._format(restoration), restoration.attributes.description);
    }

    const cause = this._known(this._state(entities, "cause"));
    if (cause) add(text.cause, this._format(cause), cause.attributes.description);

    const customers = this._known(this._state(entities, "adresses_touchees"));
    if (customers && Number(customers.state) > 0) {
      add(text.customers, customers.attributes.arrondi || customers.state);
    }

    const duration = this._known(this._state(entities, "duree"));
    if (duration) add(text.duration, this._duration(duration));

    return rows.length ? `<div class="rows">${rows.join("")}</div>` : "";
  }

  _planned(text, entities) {
    const planned = this._state(entities, "intervention_planifiee");
    if (!planned || planned.state !== "on") return "";
    const window = (item) => {
      const start = item.debut && this._dateTime(item.debut);
      const sameDay =
        item.debut && item.fin && new Date(item.debut).toDateString() === new Date(item.fin).toDateString();
      const end = item.fin && (sameDay ? this._time(item.fin) : this._dateTime(item.fin));
      return [start, end].filter(Boolean).join(" – ");
    };
    const attrs = planned.attributes;
    const lines = [`<div class="value">${escape(window(attrs))}</div>`];
    if (attrs.fin_au_plus_tard) {
      lines.push(
        `<div class="note">${escape(text.latest)} : ${escape(
          this._dateTime(attrs.fin_au_plus_tard),
        )}</div>`,
      );
    }
    if (attrs.report_debut) {
      lines.push(
        `<div class="note">${escape(text.fallback)} : ${escape(
          this._dateTime(attrs.report_debut),
        )}</div>`,
      );
    }
    const following = Array.isArray(attrs.interruptions_suivantes)
      ? attrs.interruptions_suivantes
      : [];
    if (following.length) {
      lines.push(
        `<div class="note">${escape(text.next)} : ${escape(following.map(window).join(", "))}</div>`,
      );
    }
    return `<div class="planned"><ha-icon icon="mdi:calendar-clock"></ha-icon><div><div class="label">${escape(
      text.planned,
    )}</div>${lines.join("")}</div></div>`;
  }
}

const STYLE = `
  ha-card { padding: 16px; display: flex; flex-direction: column; gap: 16px; }
  .header { display: flex; align-items: center; gap: 12px; cursor: pointer; }
  .badge {
    width: 44px; height: 44px; border-radius: 50%; flex: none;
    display: flex; align-items: center; justify-content: center;
    color: var(--status);
    background: color-mix(in srgb, var(--status) 18%, transparent);
  }
  .heading { min-width: 0; }
  .title { color: var(--secondary-text-color); font-size: 0.9em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .status { font-size: 1.3em; font-weight: 500; color: var(--primary-text-color); }
  .tracker { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
  .tracker li {
    position: relative; padding: 0 0 14px 28px; min-height: 16px;
    color: var(--secondary-text-color);
  }
  .tracker li:last-child { padding-bottom: 0; }
  .tracker .dot {
    position: absolute; top: 3px; left: 0; width: 14px; height: 14px;
    border-radius: 50%; box-sizing: border-box; z-index: 1;
    border: 2px solid var(--divider-color); background: var(--card-background-color);
  }
  .tracker li:not(:last-child)::after {
    content: ""; position: absolute; top: 10px; left: 6px; width: 2px; height: 100%;
    background: var(--divider-color);
  }
  .tracker li.done .dot, .tracker li.current .dot { border-color: var(--primary-color); background: var(--primary-color); }
  .tracker li.done::after { background: var(--primary-color); }
  .tracker li.current { color: var(--primary-text-color); font-weight: 500; }
  .tracker li.current .dot { box-shadow: 0 0 0 4px color-mix(in srgb, var(--primary-color) 25%, transparent); }
  .rows { display: flex; flex-direction: column; gap: 10px; }
  .row { display: flex; justify-content: space-between; gap: 16px; }
  .label { color: var(--secondary-text-color); flex: none; }
  .value { text-align: right; color: var(--primary-text-color); }
  .note { display: block; margin: 2px 0 0; font-size: 0.85em; color: var(--secondary-text-color); }
  p.note { margin: -8px 0 0 28px; }
  .planned {
    display: flex; gap: 12px; padding: 12px; border-radius: 12px;
    background: color-mix(in srgb, var(--info-color, var(--primary-color)) 12%, transparent);
  }
  .planned ha-icon { color: var(--info-color, var(--primary-color)); flex: none; }
  .planned .value, .planned .note { text-align: left; }
`;

// The frontend loads this module alongside its own app, which replaces window.customElements with a scoped registry polyfill. Defined before that swap, the card lands in the native registry where dashboards never look, so wait for home-assistant to be defined and use whichever registry is current then.
customElements.whenDefined("home-assistant").then(() => {
  if (window.customElements.get("hydropannes-card")) return;
  window.customElements.define("hydropannes-card", HydroPannesCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "hydropannes-card",
    name: "Hydro-Pannes",
    description: "Suivi d'une panne ou d'une interruption planifiée, comme sur Info-pannes.",
    preview: true,
  });
});
