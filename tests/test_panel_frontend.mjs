import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

class TestHTMLElement {
  matches(selector) {
    return selector.split(", ").some((part) => {
      const attribute = part
        .slice(6, -1)
        .replace(/-([a-z])/g, (_match, char) => char.toUpperCase());
      return Object.hasOwn(this.dataset, attribute);
    });
  }
}

function createPanel() {
  let Panel;
  const context = {
    HTMLElement: TestHTMLElement,
    customElements: {
      define(_name, element) {
        Panel = element;
      },
      get() {
        return undefined;
      },
    },
    window: {
      location: { pathname: "/", search: "", hash: "" },
      history: { pushState() {} },
      dispatchEvent() {},
    },
    Event: class {
      constructor(type, options) {
        this.type = type;
        Object.assign(this, options);
      }
    },
  };
  const source = readFile(
    new URL(
      "../custom_components/button_actions/frontend/button-actions-panel.js",
      import.meta.url,
    ),
    "utf8",
  );
  return source.then((script) => {
    vm.runInNewContext(script, context);
    return new Panel();
  });
}

const remote = {
  entry_id: "remote-entry-id",
  title: "Office Remote",
  state: "loaded",
  source: "event_entity",
  buttons: [
    {
      slot: "button_1",
      subentry_id: "button-subentry-id",
      title: "Button 1",
      entities: ["event.office_remote_button"],
      gestures: ["short_press"],
      repeat: false,
      detect_all: false,
      available: true,
    },
  ],
  supports_double: true,
  supports_long: true,
  timing: { double_ms: 280, hold_ms: 650, repeat_ms: 350 },
};

test("dashboard actions expose in-place configuration popups", async () => {
  const panel = await createPanel();
  panel._remotes = [remote];
  panel.shadowRoot = {
    innerHTML: "",
    querySelector: () => null,
    addEventListener() {},
  };

  panel._render();

  assert.match(
    panel.shadowRoot.innerHTML,
    /data-action="add-remote">Add or import remote/,
  );
  assert.match(
    panel.shadowRoot.innerHTML,
    /data-action="integration-settings">\s*Integration settings/,
  );
  assert.match(
    panel.shadowRoot.innerHTML,
    /data-action="manage-remote" data-entry-id="remote-entry-id">Manage remote/,
  );
  assert.match(
    panel.shadowRoot.innerHTML,
    /data-action="edit-button" data-entry-id="remote-entry-id" data-subentry-id="button-subentry-id" aria-label="Edit Button 1">Edit/,
  );
});

test("remote management and integration settings stay in popup dialogs", async () => {
  const panel = await createPanel();
  panel._remotes = [remote];
  const dialogs = [];
  panel._renderDialog = (...args) => dialogs.push(args);

  panel._openSettingsDialog();
  assert.equal(dialogs[0][0], "Integration settings");
  assert.match(dialogs[0][1], /Timing settings/);
  assert.match(dialogs[0][1], /remote-entry-id/);

  panel._openManageDialog("remote-entry-id");
  assert.equal(dialogs[1][0], "Manage remote");
  assert.match(dialogs[1][1], /Remote configuration/);
  assert.match(dialogs[1][1], /Add button/);
  assert.match(dialogs[1][1], /data-subentry-id="button-subentry-id"/);
});

test("refresh reloads dashboard data", async () => {
  const panel = await createPanel();
  let clickHandler;
  let loaded = false;
  panel.shadowRoot = {
    addEventListener(type, handler) {
      if (type === "click") clickHandler = handler;
    },
  };
  panel._load = () => {
    loaded = true;
  };
  panel._bindRoutes();

  const click = (dataset) => {
    let prevented = false;
    clickHandler({
      composedPath: () => [
        Object.assign(new TestHTMLElement(), { dataset }),
      ],
      preventDefault: () => {
        prevented = true;
      },
    });
    assert.equal(prevented, true);
  };

  click({ action: "refresh" });
  assert.equal(loaded, true);
});

test("flow popups use Home Assistant config, options, and subentry APIs", async () => {
  const panel = await createPanel();
  const calls = [];
  panel._renderDialog = () => {};
  panel._showFlowStep = async () => {};
  panel._hass = {
    callApi: async (...args) => {
      calls.push(args);
      return { flow_id: `flow-${calls.length}` };
    },
  };

  await panel._startFlow("config", "Add or import remote", {
    handler: "button_actions",
  });
  await panel._startFlow("config", "Manage remote", {
    handler: "button_actions",
    entry_id: "remote-entry-id",
  });
  await panel._startFlow("options", "Integration settings", {
    handler: "remote-entry-id",
  });
  await panel._startFlow("subentry", "Edit button", {
    handler: ["remote-entry-id", "button"],
    subentry_id: "button-subentry-id",
  });

  assert.deepEqual(
    calls.map(([method, path, body]) => [method, path, body]),
    [
      ["POST", "config/config_entries/flow", { handler: "button_actions" }],
      [
        "POST",
        "config/config_entries/flow",
        { handler: "button_actions", entry_id: "remote-entry-id" },
      ],
      [
        "POST",
        "config/config_entries/options/flow",
        { handler: "remote-entry-id" },
      ],
      [
        "POST",
        "config/config_entries/subentries/flow",
        {
          handler: ["remote-entry-id", "button"],
          subentry_id: "button-subentry-id",
        },
      ],
    ],
  );
  assert.ok(calls.every(([, , , headers]) => headers["HA-Frontend-Base"]));
});

test("flow forms use Home Assistant's native visual selectors and preserve values", async () => {
  const panel = await createPanel();
  panel._hass = {};
  const form = panel._renderFlowForm({
    step_id: "reconfigure",
    data_schema: [
      {
        name: "entities",
        required: true,
        selector: { entity: { multiple: true, domain: ["event"] } },
        description: { suggested_value: ["event.remote_button"] },
      },
      {
        name: "short_press",
        selector: { action: {} },
        description: {
          suggested_value: [{ action: "light.turn_on" }],
        },
      },
    ],
  });
  assert.match(form, /<ha-form id="dashboard-flow-form"><\/ha-form>/);
  assert.doesNotMatch(form, /textarea|data-json|JSON list/);
  const schema = [
    {
      name: "entities",
      description: { suggested_value: ["event.remote_button"] },
    },
    {
      name: "short_press",
      description: { suggested_value: [{ action: "light.turn_on" }] },
    },
  ];
  assert.deepEqual(JSON.parse(JSON.stringify(panel._initialFlowData(schema))), {
    entities: ["event.remote_button"],
    short_press: [{ action: "light.turn_on" }],
  });

  let formElement;
  panel.shadowRoot = {
    querySelector: () => formElement,
  };
  formElement = {};
  panel._flowInput = panel._initialFlowData(schema);
  panel._configureFlowForm({
    handler: "button_actions",
    data_schema: schema,
    errors: { short_press: "invalid_action" },
  });
  assert.equal(formElement.hass, panel._hass);
  assert.deepEqual(formElement.schema, schema);
  assert.deepEqual(JSON.parse(JSON.stringify(formElement.data)), {
    entities: ["event.remote_button"],
    short_press: [{ action: "light.turn_on" }],
  });
  assert.equal(formElement.context.domain, "button_actions");
  assert.equal(formElement.error.short_press, "invalid_action");
  assert.equal(formElement.computeError(null, "invalid_action"), "One or more action lists are invalid.");
});

test("visual form changes are retained as flow submission data", async () => {
  const panel = await createPanel();
  const listeners = {};
  panel.shadowRoot = {
    addEventListener(type, handler) {
      listeners[type] = handler;
    },
  };
  panel._bindRoutes();

  const values = {
    short_press: [{ action: "light.turn_on", target: { entity_id: "light.desk" } }],
    long_press: [],
    repeat: false,
  };
  listeners["value-changed"]({
    target: { id: "dashboard-flow-form" },
    detail: { value: values },
  });

  assert.deepEqual(JSON.parse(JSON.stringify(panel._flowInput)), values);
});

test("saving through a popup refreshes the dashboard and shows completion", async () => {
  const panel = await createPanel();
  let refreshCount = 0;
  let completion;
  panel._activeFlow = { kind: "subentry", title: "Edit button", flowId: "flow-id" };
  panel._load = async () => {
    refreshCount += 1;
  };
  panel._renderDialog = (...args) => {
    completion = args;
  };

  await panel._showFlowStep({
    type: "create_entry",
    title: "Button 1",
  });

  assert.equal(refreshCount, 1);
  assert.equal(completion[0], "Configuration saved");
  assert.match(completion[1], /Button 1/);
});
