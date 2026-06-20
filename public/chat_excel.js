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

  function clearMessageClasses(message) {
    message.classList.remove(...MESSAGE_CLASSES);
  }

  function markerTarget(marker) {
    return (
      marker.closest(".ai-message") ||
      marker.closest("[data-step-type]") ||
      marker.closest("[data-testid*='step' i]") ||
      marker.parentElement
    );
  }

  function selectAllIncludingSelf(scope, selector) {
    const items = Array.from(scope.querySelectorAll(selector));
    if (scope.matches && scope.matches(selector)) {
      items.unshift(scope);
    }
    return items;
  }

  function classifyMessages(root) {
    const scope = root || document;
    const messages = selectAllIncludingSelf(
      scope,
      ".ai-message, [data-step-type], [data-testid*='step' i]",
    );
    for (const message of messages) {
      clearMessageClasses(message);
    }

    const markers = selectAllIncludingSelf(scope, ".cx-ui-marker[data-cx-kind]");
    for (const marker of markers) {
      const target = markerTarget(marker);
      const kind = marker.getAttribute("data-cx-kind");
      if (target) {
        clearMessageClasses(target);
      }
      if (target && kind) {
        target.classList.add(`cx-msg-${kind}`);
      }
    }
  }

  function boot() {
    document.documentElement.classList.add("cx-enhanced");
    classifyMessages(document);

    const root = document.querySelector("#root") || document.body;
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.target instanceof Element) {
          classifyMessages(mutation.target.closest(".ai-message") || mutation.target);
        }
        for (const node of mutation.addedNodes) {
          if (node instanceof Element) {
            classifyMessages(node);
          }
        }
      }
    });
    observer.observe(root, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
