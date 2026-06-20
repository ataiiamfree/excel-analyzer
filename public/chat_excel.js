(function () {
  const MESSAGE_CLASSES = [
    "cx-msg-reasoning",
    "cx-msg-progress",
    "cx-msg-plan",
    "cx-msg-execute",
    "cx-msg-result",
    "cx-msg-artifact",
    "cx-msg-preview",
  ];

  const KIND_MARKERS = {
    reasoning: "\u2063\u2062\u200b\u2062\u2063",
    progress: "\u2063\u2062\u200c\u2062\u2063",
    plan: "\u2063\u2062\u200d\u2062\u2063",
    execute: "\u2063\u2062\u2060\u2062\u2063",
    result: "\u2063\u2062\u2061\u2062\u2063",
    artifact: "\u2063\u2062\u2063\u2062\u2063",
    preview: "\u2063\u2062\u2064\u2062\u2063",
  };

  const LEGACY_MARKER_RE =
    /<span\s+[^>]*class=["']cx-ui-marker["'][^>]*data-cx-kind=["']([^"']+)["'][^>]*><\/span>\s*/g;

  function clearMessageClasses(message) {
    message.classList.remove(...MESSAGE_CLASSES);
  }

  function closestMessageContainer(node) {
    const element = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
    if (!element) return null;
    return (
      element.closest(".ai-message") ||
      element.closest("[data-step-type]") ||
      element.closest("[data-testid*='step' i]") ||
      element
    );
  }

  function applyKind(target, kind) {
    if (!target || !kind) return;
    clearMessageClasses(target);
    target.classList.add(`cx-msg-${kind}`);
    target.setAttribute("data-cx-kind", kind);
  }

  function markerKind(text) {
    for (const [kind, marker] of Object.entries(KIND_MARKERS)) {
      if (text.includes(marker)) return kind;
    }

    LEGACY_MARKER_RE.lastIndex = 0;
    const legacy = LEGACY_MARKER_RE.exec(text);
    return legacy ? legacy[1] : "";
  }

  function stripMarkers(text) {
    let next = text;
    for (const marker of Object.values(KIND_MARKERS)) {
      next = next.split(marker).join("");
    }
    LEGACY_MARKER_RE.lastIndex = 0;
    return next.replace(LEGACY_MARKER_RE, "");
  }

  function textNodes(root) {
    if (!root) return [];
    if (root.nodeType === Node.TEXT_NODE) return [root];
    if (!root.querySelectorAll && root !== document) return [];

    const nodes = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node) {
      nodes.push(node);
      node = walker.nextNode();
    }
    return nodes;
  }

  function classifyMessages(root) {
    for (const textNode of textNodes(root || document)) {
      const text = textNode.nodeValue || "";
      const kind = markerKind(text);
      if (!kind) continue;
      applyKind(closestMessageContainer(textNode), kind);
      textNode.nodeValue = stripMarkers(text);
    }
  }

  function boot() {
    document.documentElement.classList.add("cx-enhanced");
    classifyMessages(document);

    const root = document.querySelector("#root") || document.body;
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        classifyMessages(mutation.target);
        for (const node of mutation.addedNodes) {
          classifyMessages(node);
        }
      }
    });
    observer.observe(root, { childList: true, characterData: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
