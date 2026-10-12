class ButtonActionsPanel extends HTMLElement {
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
            <button class="secondary" data-action="integration-settings">
              Integration settings
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
            <p class="intro">See every remote and button in one place. Configure remotes, timing, and button actions in focused popups without leaving this dashboard.</p>
          </div>
          <div class="header-actions">
            <button class="secondary" data-action="refresh">Refresh</button>
            <button class="primary" data-action="add-remote">Add or import remote</button>
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
          <button class="secondary" data-action="integration-settings">
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
                   <button class="primary" data-action="add-remote">Set up a remote</button>
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
        <details class="remote-collapse">
          <summary class="remote-header">
          <div class="remote-heading">
            <div class="remote-icon"><ha-icon icon="mdi:remote"></ha-icon></div>
            <div>
              <h2>${title}</h2>
              <div class="meta">${source} <span class="dot">·</span> ${remote.buttons.length} ${remote.buttons.length === 1 ? "button" : "buttons"}</div>
            </div>
          </div>
          <span class="status ${healthy ? "healthy" : "attention"}">${healthy ? "Active" : this._escape(remote.state.replaceAll("_", " "))}</span>
          </summary>
          <div class="remote-content">
            <div class="remote-actions">
              <button class="secondary" data-action="manage-remote" data-entry-id="${this._escape(remote.entry_id)}">Manage remote</button>
            </div>
            <div class="remote-details">
              <span>${remote.supports_double ? "Double press supported" : "No double press"}</span>
              <span>${remote.supports_long ? "Long press supported" : "No long press"}</span>
              <span>Double ${remote.timing.double_ms} ms</span>
              <span>Hold ${remote.timing.hold_ms} ms</span>
              <span>Repeat ${remote.timing.repeat_ms} ms</span>
            </div>
            <div class="button-list">${buttons}</div>
          </div>
        </details>
      </ha-card>`;
  }

  _buttonRow(remote, button) {
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
          <button class="text-button" data-action="edit-button" data-entry-id="${this._escape(remote.entry_id)}" data-subentry-id="${this._escape(button.subentry_id)}" aria-label="Edit ${this._escape(button.title)}">Edit</button>
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
          target.matches("[data-action], [data-menu-option]"),
      );
      if (!control) return;
      event.preventDefault();
      if (control.dataset.menuOption) {
        this._submitFlow({ next_step_id: control.dataset.menuOption });
        return;
      }
      this._handleAction(control.dataset.action, control.dataset);
    });
    this.shadowRoot.addEventListener("submit", (event) => {
      if (!event.target.matches("[data-flow-form]")) return;
      event.preventDefault();
      this._submitFlow(this._flowInput || {});
    });
    this.shadowRoot.addEventListener("value-changed", (event) => {
      if (event.target.id !== "dashboard-flow-form") return;
      this._flowInput = event.detail.value;
    });
    this.shadowRoot.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && this.shadowRoot.querySelector(".dialog-host")) {
        this._closeDialog();
      }
    });
  }

  _handleAction(action, data = {}) {
    switch (action) {
      case "refresh":
        this._load();
        break;
      case "add-remote":
        this._startFlow("config", "Add or import remote", {
          handler: "button_actions",
        });
        break;
      case "integration-settings":
        this._openSettingsDialog();
        break;
      case "manage-remote":
        this._openManageDialog(data.entryId);
        break;
      case "edit-button":
        this._startFlow("subentry", "Edit button", {
          handler: [data.entryId, "button"],
          subentry_id: data.subentryId,
        });
        break;
      case "manage-configure-remote":
        this._startFlow("config", "Manage remote", {
          handler: "button_actions",
          entry_id: data.entryId,
        });
        break;
      case "manage-timing":
      case "settings-timing":
        this._startFlow("options", "Integration settings", {
          handler: data.entryId,
        });
        break;
      case "manage-add-button":
        this._startFlow("subentry", "Add button", {
          handler: [data.entryId, "button"],
        });
        break;
      case "settings-select-remote":
        this._startFlow("options", "Remote timing settings", {
          handler: data.entryId,
        });
        break;
      case "dialog-close":
        this._closeDialog();
        break;
      case "flow-continue":
        this._submitFlow(this._flowInput || {});
        break;
      case "flow-back":
        this._openManageDialog(data.entryId);
        break;
    }
  }

  _apiPath(kind, flowId) {
    const paths = {
      config: "config/config_entries/flow",
      options: "config/config_entries/options/flow",
      subentry: "config/config_entries/subentries/flow",
    };
    return `${paths[kind]}${flowId ? `/${encodeURIComponent(flowId)}` : ""}`;
  }

  async _startFlow(kind, title, payload) {
    const flow = { kind, title, flowId: null };
    this._activeFlow = flow;
    this._renderDialog(title, `<p class="dialog-loading">Opening configuration…</p>`);
    try {
      const step = await this._hass.callApi(
        "POST",
        this._apiPath(kind),
        payload,
        { "HA-Frontend-Base": `${window.location.protocol}//${window.location.host}` },
      );
      if (this._activeFlow !== flow) return;
      this._activeFlow.flowId = step.flow_id;
      await this._showFlowStep(step);
    } catch (error) {
      if (this._activeFlow === flow) this._renderDialogError(error);
    }
  }

  async _submitFlow(userInput) {
    const flow = this._activeFlow;
    if (!flow?.flowId) return;
    const form = this.shadowRoot.querySelector("#dashboard-flow-form");
    if (form?.reportValidity && !form.reportValidity()) return;
    if (form) form.disabled = true;
    try {
      const step = await this._hass.callApi(
        "POST",
        this._apiPath(flow.kind, flow.flowId),
        userInput,
        { "HA-Frontend-Base": `${window.location.protocol}//${window.location.host}` },
      );
      if (this._activeFlow !== flow) return;
      await this._showFlowStep(step);
    } catch (error) {
      if (this._activeFlow === flow) this._renderDialogError(error);
    }
  }

  async _showFlowStep(step) {
    if (step.type === "create_entry") {
      this._activeFlow = null;
      await this._load();
      this._renderDialog(
        "Configuration saved",
        `<p class="dialog-success">${this._escape(step.title || "Your changes have been saved.")}</p>`,
        `<button class="primary" data-action="dialog-close">Done</button>`,
      );
      return;
    }
    if (step.type === "abort") {
      this._activeFlow = null;
      this._renderDialog(
        "Configuration not changed",
        `<p>${this._escape(step.reason.replaceAll("_", " "))}</p>`,
        `<button class="primary" data-action="dialog-close">Close</button>`,
      );
      return;
    }
    if (step.type === "menu") {
      const options = Array.isArray(step.menu_options)
        ? step.menu_options.map((option) => [option, this._menuLabel(option)])
        : Object.entries(step.menu_options);
      this._renderDialog(
        this._activeFlow.title,
        `<p class="dialog-description">Choose how you want to continue.</p>
         <div class="flow-menu">${options
           .map(
             ([option, label]) =>
               `<button class="menu-option" data-menu-option="${this._escape(option)}">${this._escape(label)}</button>`,
           )
           .join("")}</div>`,
        `<button class="secondary" data-action="dialog-close">Cancel</button>`,
      );
      return;
    }
    if (step.type === "form") {
      this._flowInput = this._initialFlowData(step.data_schema);
      this._renderDialog(
        this._activeFlow.title,
        this._renderFlowForm(step),
        `<button class="secondary" data-action="dialog-close">Cancel</button>
         <button class="primary" data-action="flow-continue">Continue</button>`,
      );
      this._configureFlowForm(step);
      return;
    }
    if (step.type === "progress") {
      this._renderDialog(
        this._activeFlow.title,
        `<p class="dialog-loading">Working…</p>`,
      );
      window.setTimeout(async () => {
        const flow = this._activeFlow;
        if (!flow?.flowId) return;
        try {
          const next = await this._hass.callApi(
            "GET",
            this._apiPath(flow.kind, flow.flowId),
            undefined,
            { "HA-Frontend-Base": `${window.location.protocol}//${window.location.host}` },
          );
          if (this._activeFlow !== flow) return;
          await this._showFlowStep(next);
        } catch (error) {
          if (this._activeFlow === flow) this._renderDialogError(error);
        }
      }, 500);
      return;
    }
    if (step.type === "external") {
      this._renderDialog(
        this._activeFlow.title,
        `<p>Continue setup in the external service.</p>
         <a class="primary button-link" href="${this._escape(step.url)}" target="_blank" rel="noopener noreferrer">Open setup</a>`,
        `<button class="secondary" data-action="dialog-close">Close</button>`,
      );
      return;
    }
    this._renderDialogError(new Error(`Unsupported configuration step: ${step.type}`));
  }

  _menuLabel(option) {
    const labels = {
      device: "Add from a device",
      import_blueprint: "Import a Pico blueprint",
      import_all: "Import all Pico blueprints",
      duplicate: "Duplicate an existing remote",
      manual: "Create a remote manually",
      import_pico: "Read presses directly from the Pico",
      import_entities: "Use event entities",
      duplicate_pico: "Read presses directly from the Pico",
      duplicate_entities: "Use event entities",
      duplicate_numbered: "Create numbered buttons",
    };
    return labels[option] || option.replaceAll("_", " ");
  }

  _renderFlowForm(step) {
    return `<p class="dialog-description">${this._escape(this._stepDescription(step))}</p>
      ${step.errors?.base ? `<p class="field-error">${this._escape(this._errorLabel(step.errors.base))}</p>` : ""}
      <ha-form id="dashboard-flow-form"></ha-form>`;
  }

  _initialFlowData(schema) {
    return Object.fromEntries(
      schema
        .map((field) => [
          field.name,
          field.description?.suggested_value ?? field.default,
        ])
        .filter(([, value]) => value !== undefined),
    );
  }

  _configureFlowForm(step) {
    const form = this.shadowRoot.querySelector("#dashboard-flow-form");
    if (!form) {
      this._renderDialogError(new Error("Home Assistant's visual form could not be loaded."));
      return;
    }
    form.hass = this._hass;
    form.schema = step.data_schema;
    form.data = this._flowInput;
    form.error = step.errors || undefined;
    form.computeLabel = (field) => this._fieldLabel(field.name);
    form.computeError = (_field, error) => this._errorLabel(error);
    form.context = {
      handler: step.handler,
      domain: "button_actions",
    };
  }

  _fieldLabel(name) {
    const labels = {
      name: "Remote name",
      double_ms: "Double-press delay (ms)",
      hold_ms: "Hold delay (ms)",
      repeat_ms: "Repeat interval (ms)",
      entities: "Button event entities",
      automation: "Blueprint automation",
      disable_source: "Disable the source automation after import",
      supports_double: "Supports double press",
      supports_long: "Supports long press",
      repeat: "Repeat while held",
      detect_all: "Detect every gesture",
    };
    return labels[name] || name.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
  }

  _stepDescription(step) {
    const descriptions = {
      reconfigure: `Update settings for ${step.description_placeholders?.button || "this button"}.`,
      actions: `Set the actions for ${step.description_placeholders?.button || "this button"}.`,
      manual_buttons: `Choose the event entity for each button on ${step.description_placeholders?.remote || "this remote"}.`,
      reconfigure_events: "Choose how each event type from this remote should be interpreted.",
      device_confirm: `Confirm the ${step.description_placeholders?.count || ""} buttons found for ${step.description_placeholders?.remote || "this device"}.`,
    };
    return descriptions[step.step_id] || "Complete the fields below and continue.";
  }

  _errorLabel(error) {
    const labels = {
      invalid_action: "One or more action lists are invalid.",
      no_entities: "Select at least one event entity.",
      already_configured: "One or more event entities are already assigned to another button.",
      no_buttons: "At least one button with an event entity is required.",
      not_blueprint: "The selected automation is not a supported Pico blueprint.",
      no_blueprint_automations: "No eligible Pico blueprint automations were found.",
      nothing_to_import: "No valid blueprint automations were selected.",
    };
    return labels[error] || error.replaceAll("_", " ");
  }

  _openSettingsDialog() {
    const remotes = this._remotes || [];
    const content = remotes.length
      ? `<p class="dialog-description">Choose a remote to adjust its click and hold timing. These settings are stored per remote.</p>
         <div class="dialog-remote-list">${remotes.map((remote) => `
           <div class="dialog-remote">
             <div><strong>${this._escape(remote.title)}</strong><small>${remote.buttons.length} configured ${remote.buttons.length === 1 ? "button" : "buttons"}</small></div>
             <button class="secondary" data-action="settings-select-remote" data-entry-id="${this._escape(remote.entry_id)}">Timing settings</button>
           </div>`).join("")}</div>`
      : `<p class="dialog-description">There are no remotes to configure yet. Add a remote to manage its settings.</p>`;
    this._renderDialog(
      "Integration settings",
      content,
      `<button class="secondary" data-action="dialog-close">Close</button>`,
    );
  }

  _openManageDialog(entryId) {
    const remote = (this._remotes || []).find((item) => item.entry_id === entryId);
    if (!remote) {
      this._renderDialogError(new Error("That remote is no longer available. Refresh the dashboard and try again."));
      return;
    }
    const content = `<div class="manage-summary">
        <p class="dialog-description">Manage <strong>${this._escape(remote.title)}</strong> without leaving this dashboard.</p>
        <div class="manage-actions">
          <button class="secondary" data-action="manage-configure-remote" data-entry-id="${this._escape(entryId)}">Remote configuration</button>
          <button class="secondary" data-action="manage-timing" data-entry-id="${this._escape(entryId)}">Timing settings</button>
          <button class="primary" data-action="manage-add-button" data-entry-id="${this._escape(entryId)}">Add button</button>
        </div>
        <h3>Buttons</h3>
        <div class="dialog-button-list">${remote.buttons.length ? remote.buttons.map((button) => `
          <div class="dialog-remote">
            <div><strong>${this._escape(button.title)}</strong><small>${this._escape(button.entities.join(", ") || "Read directly from Lutron")}</small></div>
            <button class="secondary" data-action="edit-button" data-entry-id="${this._escape(entryId)}" data-subentry-id="${this._escape(button.subentry_id)}">Edit button</button>
          </div>`).join("") : `<p class="muted">No buttons are configured.</p>`}</div>
      </div>`;
    this._renderDialog(
      "Manage remote",
      content,
      `<button class="secondary" data-action="dialog-close">Close</button>`,
    );
  }

  _renderDialog(title, content, footer = "") {
    let host = this.shadowRoot.querySelector(".dialog-host");
    if (!host) {
      this._dialogOpener = this.shadowRoot.activeElement;
      host = document.createElement("div");
      host.className = "dialog-host";
      this.shadowRoot.append(host);
    }
    host.innerHTML = `<div class="dialog-backdrop">
      <section class="dashboard-dialog" role="dialog" aria-modal="true" aria-labelledby="dashboard-dialog-title">
        <header class="dialog-header"><h2 id="dashboard-dialog-title">${this._escape(title)}</h2>
          <button class="icon-button" data-action="dialog-close" aria-label="Close dialog">×</button>
        </header>
        <div class="dialog-content">${content}</div>
        ${footer ? `<footer class="dialog-footer">${footer}</footer>` : ""}
      </section>
    </div>`;
    host.querySelector(".dialog-backdrop").addEventListener("click", (event) => {
      if (event.target === event.currentTarget) this._closeDialog();
    });
    host.querySelector(".dashboard-dialog button, .dashboard-dialog input, .dashboard-dialog select, .dashboard-dialog textarea")?.focus();
  }

  _renderDialogError(error) {
    const message = typeof error === "string"
      ? error
      : error?.message || error?.body || "Home Assistant could not complete this request.";
    this._activeFlow = null;
    this._renderDialog(
      "Could not save configuration",
      `<p class="field-error">${this._escape(message)}</p>`,
      `<button class="secondary" data-action="dialog-close">Close</button>`,
    );
  }

  _closeDialog() {
    const flow = this._activeFlow;
    this._activeFlow = null;
    this.shadowRoot.querySelector(".dialog-host")?.remove();
    this._dialogOpener?.focus?.();
    this._dialogOpener = null;
    if (flow?.flowId) {
      this._hass.callApi(
        "DELETE",
        this._apiPath(flow.kind, flow.flowId),
        undefined,
        { "HA-Frontend-Base": `${window.location.protocol}//${window.location.host}` },
      ).catch((error) => console.error("Could not close Button Actions config flow", error));
    }
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
      .dialog-host { position: fixed; inset: 0; z-index: 10; }
      .dialog-backdrop { box-sizing: border-box; display: grid; place-items: center; width: 100%; height: 100%; padding: 20px; background: rgb(0 0 0 / 48%); }
      .dashboard-dialog { display: flex; flex-direction: column; width: min(620px, 100%); max-height: min(820px, 92vh); overflow: hidden; color: var(--primary-text-color); background: var(--card-background-color); border-radius: 16px; box-shadow: 0 14px 48px rgb(0 0 0 / 28%); }
      .dialog-header { flex: none; justify-content: space-between; gap: 16px; padding: 20px 24px; border-bottom: 1px solid var(--divider-color); }
      .dialog-header h2 { font-size: 20px; }
      .icon-button { padding: 4px 10px; color: var(--secondary-text-color); background: transparent; font-size: 26px; line-height: 1; }
      .dialog-content { overflow: auto; padding: 22px 24px; }
      .dialog-footer { display: flex; justify-content: flex-end; gap: 8px; flex: none; padding: 16px 24px; border-top: 1px solid var(--divider-color); }
      .dialog-description { margin: 0 0 18px; color: var(--secondary-text-color); line-height: 1.5; }
      .dialog-loading, .dialog-success { padding: 8px 0; color: var(--secondary-text-color); }
      .dialog-success { color: var(--success-color, #2e7d32); }
      .flow-menu, .dialog-remote-list, .dialog-button-list { display: grid; gap: 8px; }
      .menu-option { width: 100%; padding: 14px 16px; text-align: left; color: var(--primary-text-color); background: var(--secondary-background-color); }
      .menu-option:hover, .dialog-remote button:hover { filter: brightness(.96); }
      #dashboard-flow-form { display: block; margin-top: 18px; }
      .dialog-remote small { color: var(--secondary-text-color); font-size: 12px; font-weight: 400; line-height: 1.45; }
      .field-error { color: var(--error-color); }
      .dialog-remote { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 13px 14px; border: 1px solid var(--divider-color); border-radius: 10px; }
      .dialog-remote > div { display: grid; gap: 4px; min-width: 0; }
      .dialog-remote strong { overflow-wrap: anywhere; }
      .manage-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 22px; }
      .manage-summary h3 { margin: 0 0 12px; font-size: 15px; }
      .button-link { display: inline-block; text-decoration: none; }
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
        .dialog-backdrop { align-items: end; padding: 0; }
        .dashboard-dialog { width: 100%; max-height: 92dvh; border-radius: 16px 16px 0 0; }
        .dialog-header { padding: 16px 18px; }
        .dialog-content { padding: 18px; }
        .dialog-footer { padding: 13px 18px; }
        .dialog-remote { align-items: flex-start; flex-direction: column; }
      }
    `;
  }
}

if (!customElements.get("button-actions-panel")) {
  customElements.define("button-actions-panel", ButtonActionsPanel);
}
