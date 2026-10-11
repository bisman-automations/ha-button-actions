class ButtonActionsPanel extends HTMLElement {
  _integrationRoute() {
    return "/config/integrations/integration/button_actions";
  }

  _addRemoteRoute() {
    return "/config/integrations/add?domain=button_actions";
  }

  _remoteRoute(entryId) {
    return `${this._integrationRoute()}#config_entry=${encodeURIComponent(entryId)}`;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) {
      this._loaded = true;
      this._load();
    }
  }

  async _load() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }
    this._renderLoading();
    try {
      const result = await this._hass.callWS({
        type: "button_actions/panel/config",
      });
      this._remotes = result.remotes;
      this._render();
    } catch (error) {
      this._renderError(error);
    }
  }

  _escape(value) {
    return String(value).replace(/[&<>"']/g, (character) => {
      const entities = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      };
      return entities[character];
    });
  }

  _route(path) {
    const from = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    window.history.pushState({ from }, "", path);
    const event = new Event("location-changed", {
      bubbles: true,
      composed: true,
    });
    event.detail = { replace: false };
    window.dispatchEvent(event);
  }

  _renderLoading() {
    this.shadowRoot.innerHTML = `
      <style>${this._styles()}</style>
      <main><ha-card><div class="message">Loading Button Actions…</div></ha-card></main>`;
  }

  _renderError(error) {
    this.shadowRoot.innerHTML = `
      <style>${this._styles()}</style>
      <main>
        <ha-card>
          <div class="message error">
            <h2>Dashboard unavailable</h2>
            <p>${this._escape(error?.message || "Home Assistant could not load the remote configuration.")}</p>
            <button class="secondary" data-route="/config/integrations/integration/button_actions">
              Open integration settings
            </button>
          </div>
        </ha-card>
      </main>`;
    this._bindRoutes();
  }

  _render() {
    const remotes = this._remotes || [];
    const buttonCount = remotes.reduce(
      (count, remote) => count + remote.buttons.length,
      0,
    );
    const unavailableCount = remotes.reduce(
      (count, remote) =>
        count + remote.buttons.filter((button) => !button.available).length,
      0,
    );
    const cards = remotes
      .map((remote) => this._remoteCard(remote))
      .join("");

    this.shadowRoot.innerHTML = `
      <style>${this._styles()}</style>
      <main>
        <header>
          <div>
            <p class="eyebrow">REMOTE CONFIGURATION</p>
            <h1>Button Actions</h1>
            <p class="intro">See every remote and button in one place. Edit actions and timing using Home Assistant’s built-in configuration forms.</p>
          </div>
          <div class="header-actions">
            <button class="secondary" data-action="refresh">Refresh</button>
            <button class="primary" data-route="${this._addRemoteRoute()}">Add or import remote</button>
          </div>
        </header>
        <section class="summary" aria-label="Configuration summary">
          <ha-card><span class="number">${remotes.length}</span><span>remotes</span></ha-card>
          <ha-card><span class="number">${buttonCount}</span><span>buttons</span></ha-card>
          <ha-card class="${unavailableCount ? "warning" : ""}">
            <span class="number">${unavailableCount}</span><span>buttons with unavailable sources</span>
          </ha-card>
        </section>
        <div class="toolbar">
          <label>
            <span class="visually-hidden">Search remotes and buttons</span>
            <input type="search" placeholder="Search remotes, buttons, or entities" autocomplete="off">
          </label>
          <button class="secondary" data-route="${this._integrationRoute()}">
            Integration settings
          </button>
        </div>
        ${
          remotes.length
            ? `<section class="remotes" aria-label="Remotes">${cards}</section>
               <p class="no-results" hidden>No remotes or buttons match that search.</p>`
            : `<ha-card class="empty">
                 <div class="message">
                   <h2>No remotes configured yet</h2>
                   <p>Add a device, import a Pico blueprint automation, or create a remote by hand.</p>
                   <button class="primary" data-route="${this._addRemoteRoute()}">Set up a remote</button>
                 </div>
               </ha-card>`
        }
      </main>`;
    this._bindRoutes();
    const search = this.shadowRoot.querySelector('input[type="search"]');
    search?.addEventListener("input", () => this._filter(search.value));
  }

  _remoteCard(remote) {
    const title = this._escape(remote.title);
    const route = `/config/integrations#config_entry=${encodeURIComponent(remote.entry_id)}`;
    const healthy = remote.state === "loaded";
    const source =
      remote.source === "lutron_caseta" ? "Lutron Caséta" : "Event entities";
    const buttons = remote.buttons.length
      ? remote.buttons.map((button) => this._buttonRow(remote, button)).join("")
      : `<div class="empty-buttons">No buttons configured.</div>`;
    return `
      <ha-card class="remote" data-search="${this._searchText(
        [remote.title, remote.source, ...remote.buttons.flatMap((button) => [button.title, ...button.entities])].join(" "),
      )}">
        <div class="remote-header">
          <div class="remote-heading">
            <div class="remote-icon"><ha-icon icon="mdi:remote"></ha-icon></div>
            <div>
              <h2>${title}</h2>
              <div class="meta">${source} <span class="dot">·</span> ${remote.buttons.length} ${remote.buttons.length === 1 ? "button" : "buttons"}</div>
            </div>
          </div>
          <div class="remote-actions">
            <span class="status ${healthy ? "healthy" : "attention"}">${healthy ? "Active" : this._escape(remote.state.replaceAll("_", " "))}</span>
            <button class="secondary" data-route="${this._escape(route)}">Manage remote</button>
          </div>
        </div>
        <div class="remote-details">
          <span>${remote.supports_double ? "Double press supported" : "No double press"}</span>
          <span>${remote.supports_long ? "Long press supported" : "No long press"}</span>
          <span>Double ${remote.timing.double_ms} ms</span>
          <span>Hold ${remote.timing.hold_ms} ms</span>
          <span>Repeat ${remote.timing.repeat_ms} ms</span>
        </div>
        <div class="button-list">${buttons}</div>
      </ha-card>`;
  }

  _buttonRow(remote, button) {
    const route = this._remoteRoute(remote.entry_id);
    const gestures = button.gestures.length
      ? button.gestures
          .map((gesture) => `<span class="chip">${this._escape(gesture.replaceAll("_", " "))}</span>`)
          .join("")
      : `<span class="muted">No actions assigned</span>`;
    const entities = button.entities.length
      ? button.entities.map((entity) => `<code>${this._escape(entity)}</code>`).join("")
      : `<span class="muted">Read directly from Lutron</span>`;
    return `
      <div class="button-row" data-search="${this._searchText(
        [button.title, button.slot, ...button.entities, ...button.gestures].join(" "),
      )}">
        <div class="button-icon"><ha-icon icon="${this._buttonIcon(button.slot)}"></ha-icon></div>
        <div class="button-info">
          <div class="button-title">${this._escape(button.title)}</div>
          <div class="entities">${entities}</div>
          <div class="chips">${gestures}
            ${button.repeat ? '<span class="chip accent">Repeats while held</span>' : ""}
            ${button.detect_all ? '<span class="chip">Detect every gesture</span>' : ""}
          </div>
        </div>
        <div class="button-actions">
          ${button.available ? "" : '<span class="status attention">Source unavailable</span>'}
          <button class="text-button" data-route="${this._escape(route)}" aria-label="Manage ${this._escape(button.title)}">Edit</button>
        </div>
      </div>`;
  }

  _buttonIcon(slot) {
    const icons = {
      on: "mdi:power-on",
      raise: "mdi:arrow-up-bold",
      stop: "mdi:circle-medium",
      lower: "mdi:arrow-down-bold",
      off: "mdi:power-off",
    };
    if (icons[slot]) return icons[slot];
    const match = /^button_(\d+)$/.exec(slot);
    return match && Number(match[1]) < 10
      ? `mdi:numeric-${match[1]}-circle`
      : "mdi:gesture-tap-button";
  }

  _searchText(value) {
    return this._escape(value.toLocaleLowerCase());
  }

  _filter(value) {
    const query = value.trim().toLocaleLowerCase();
    let visible = 0;
    this.shadowRoot.querySelectorAll(".remote").forEach((card) => {
      const remoteMatches = card.dataset.search.includes(query);
      let buttonMatches = 0;
      card.querySelectorAll(".button-row").forEach((row) => {
        const matches = !query || remoteMatches || row.dataset.search.includes(query);
        row.hidden = !matches;
        if (matches) buttonMatches += 1;
      });
      card.hidden = Boolean(query) && !remoteMatches && !buttonMatches;
      if (!card.hidden) visible += 1;
    });
    const noResults = this.shadowRoot.querySelector(".no-results");
    if (noResults) noResults.hidden = !query || visible > 0;
  }

  _bindRoutes() {
    if (this._routesBound) return;
    this._routesBound = true;
    this.shadowRoot.addEventListener("click", (event) => {
      const control = event.composedPath().find(
        (target) =>
          target instanceof HTMLElement &&
          target.matches("[data-route], [data-action]"),
      );
      if (!control) return;
      event.preventDefault();
      if (control.dataset.route) {
        this._route(control.dataset.route);
      } else if (control.dataset.action === "refresh") {
        this._load();
      }
    });
  }

  _styles() {
    return `
      :host { display: block; color: var(--primary-text-color); }
      main { max-width: 1120px; margin: 0 auto; padding: 28px 24px 48px; }
      header, .toolbar, .remote-header, .remote-heading, .remote-actions, .remote-details,
      .button-row, .button-actions { display: flex; align-items: center; }
      header { justify-content: space-between; gap: 24px; margin-bottom: 24px; }
      .header-actions { display: flex; gap: 8px; }
      h1 { margin: 2px 0 8px; font-size: 32px; font-weight: 500; }
      h2 { margin: 0; font-size: 19px; font-weight: 500; }
      p { margin: 0; }
      .eyebrow { color: var(--secondary-text-color); font-size: 11px; letter-spacing: .12em; font-weight: 600; }
      .intro { color: var(--secondary-text-color); max-width: 680px; line-height: 1.5; }
      ha-card { display: block; background: var(--card-background-color); border-radius: 12px; }
      .summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 24px; }
      .summary ha-card { padding: 18px 20px; display: flex; align-items: baseline; gap: 9px; color: var(--secondary-text-color); }
      .number { color: var(--primary-text-color); font-size: 25px; font-weight: 600; }
      .warning .number { color: var(--error-color); }
      .toolbar { justify-content: space-between; gap: 12px; margin-bottom: 16px; }
      input { box-sizing: border-box; width: min(440px, 70vw); border: 1px solid var(--divider-color); border-radius: 8px; padding: 11px 14px; color: var(--primary-text-color); background: var(--card-background-color); font: inherit; }
      button { border: 0; border-radius: 8px; padding: 10px 15px; font: inherit; font-weight: 500; cursor: pointer; }
      button.primary { color: var(--text-primary-color, #fff); background: var(--primary-color); }
      button.secondary { color: var(--primary-color); background: var(--secondary-background-color); }
      button.text-button { color: var(--primary-color); background: transparent; padding: 8px 10px; }
      .remotes { display: grid; gap: 16px; }
      .remote { overflow: hidden; }
      .remote-header { justify-content: space-between; gap: 16px; padding: 19px 22px; }
      .remote-heading { gap: 14px; min-width: 0; }
      .remote-icon, .button-icon { display: grid; flex: none; place-items: center; color: var(--primary-color); background: var(--secondary-background-color); border-radius: 10px; }
      .remote-icon { width: 44px; height: 44px; }
      .remote-icon ha-icon { --mdc-icon-size: 25px; }
      .meta, .remote-details { color: var(--secondary-text-color); font-size: 13px; }
      .meta { margin-top: 5px; }
      .dot { padding: 0 5px; }
      .remote-actions { gap: 12px; }
      .status { display: inline-flex; align-items: center; white-space: nowrap; font-size: 12px; font-weight: 600; }
      .status.healthy { color: var(--success-color, #2e7d32); }
      .status.attention { color: var(--error-color); }
      .remote-details { display: flex; flex-wrap: wrap; gap: 8px 18px; padding: 12px 22px; background: var(--secondary-background-color); }
      .button-list { padding: 0 22px; }
      .button-row { gap: 14px; border-bottom: 1px solid var(--divider-color); padding: 16px 0; }
      .button-row:last-child { border-bottom: 0; }
      .button-row[hidden], .remote[hidden], .no-results[hidden] { display: none; }
      .button-icon { width: 36px; height: 36px; }
      .button-icon ha-icon { --mdc-icon-size: 21px; }
      .button-info { min-width: 0; flex: 1; }
      .button-title { font-size: 14px; font-weight: 600; }
      .entities { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 4px; color: var(--secondary-text-color); font-size: 12px; }
      code { font-family: var(--code-font-family, monospace); font-size: 11px; }
      .chips { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
      .chip { border-radius: 20px; padding: 3px 8px; color: var(--secondary-text-color); background: var(--secondary-background-color); font-size: 11px; }
      .chip.accent { color: var(--primary-color); }
      .muted { color: var(--secondary-text-color); font-size: 12px; }
      .button-actions { flex-direction: column; align-items: flex-end; gap: 4px; }
      .empty-buttons { padding: 18px 22px; color: var(--secondary-text-color); }
      .empty .message, .message { padding: 26px; }
      .message h2 { margin-bottom: 8px; }
      .message p { margin: 0 0 16px; color: var(--secondary-text-color); line-height: 1.5; }
      .message.error { color: var(--error-color); }
      .no-results { padding: 22px; color: var(--secondary-text-color); text-align: center; }
      .visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); }
      @media (max-width: 700px) {
        main { padding: 18px 12px 32px; }
        header { align-items: flex-start; flex-direction: column; }
        .header-actions { width: 100%; }
        .summary { grid-template-columns: 1fr; gap: 8px; }
        .summary ha-card { padding: 12px 16px; }
        .toolbar { align-items: stretch; flex-direction: column; }
        input { width: 100%; }
        .remote-header { align-items: flex-start; flex-direction: column; padding: 16px; }
        .remote-actions { width: 100%; justify-content: space-between; }
        .remote-details { padding: 12px 16px; gap: 8px 12px; }
        .button-list { padding: 0 16px; }
        .button-row { align-items: flex-start; gap: 9px; }
        .button-icon { width: 30px; height: 30px; }
      }
    `;
  }
}

if (!customElements.get("button-actions-panel")) {
  customElements.define("button-actions-panel", ButtonActionsPanel);
}
