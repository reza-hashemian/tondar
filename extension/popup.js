const $ = (id) => document.getElementById(id);

async function init() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const s = await chrome.runtime.sendMessage({ type: "settings" });
  $("capture").checked = !!s.settings.capture;
  $("status").textContent = s.hostOk ? "Connected" : "App not found";
  $("status").className = "status " + (s.hostOk ? "ok" : "bad");
  $("capture").addEventListener("change", (e) =>
    chrome.runtime.sendMessage({ type: "settings", set: { capture: e.target.checked } }));
  $("clear").addEventListener("click", async () => {
    await chrome.runtime.sendMessage({ type: "clear", tabId: tab.id });
    render(tab);
  });
  render(tab);
}

async function render(tab) {
  const list = $("list");
  list.innerHTML = "";
  if (!/^https?:/i.test(tab.url || "")) {
    list.innerHTML = '<div class="msg">Open a web page to find videos.</div>';
    return;
  }
  const res = await chrome.runtime.sendMessage({ type: "options", tabId: tab.id, frameUrl: tab.url });
  for (const opt of res.options) {
    const b = document.createElement("button");
    b.className = "item";
    const l = document.createElement("div");
    l.className = "label";
    l.textContent = opt.label;
    const s = document.createElement("div");
    s.className = "sub";
    s.textContent = opt.sub;
    b.append(l, s);
    b.addEventListener("click", async () => {
      l.textContent = "Sending…";
      const r = await chrome.runtime.sendMessage({ type: "download", req: opt.req });
      l.textContent = r.ok ? "✓ Sent to Tondar" : "✗ " + r.error;
      if (r.ok) setTimeout(() => window.close(), 700);
    });
    list.appendChild(b);
  }
}

init();
