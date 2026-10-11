import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

class TestHTMLElement {
  matches(selector) {
    return selector.split(", ").some((part) => {
      const attribute = part.slice(6, -1);
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

test("dashboard controls open their intended Home Assistant destinations", async () => {
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
    /data-route="\/config\/integrations\/add\?domain=button_actions">Add or import remote/,
  );
  assert.match(
    panel.shadowRoot.innerHTML,
    /data-route="\/config\/integrations\/integration\/button_actions">\s*Integration settings/,
  );
  assert.match(
    panel.shadowRoot.innerHTML,
    /data-route="\/config\/integrations#config_entry=remote-entry-id">Manage remote/,
  );
  assert.match(
    panel.shadowRoot.innerHTML,
    /data-route="\/config\/integrations\/integration\/button_actions#config_entry=remote-entry-id" aria-label="Manage Button 1">Edit/,
  );
});

test("refresh reloads panel data and route controls navigate", async () => {
  const panel = await createPanel();
  let clickHandler;
  let loaded = false;
  let navigated;
  panel.shadowRoot = {
    addEventListener(_type, handler) {
      clickHandler = handler;
    },
  };
  panel._load = () => {
    loaded = true;
  };
  panel._route = (path) => {
    navigated = path;
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

  click({ route: "/config/integrations/add?domain=button_actions" });
  assert.equal(navigated, "/config/integrations/add?domain=button_actions");
});
