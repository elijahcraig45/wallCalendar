function initPanel(overlayId, closeId) {
  const overlay = document.getElementById(overlayId);
  const closeBtn = document.getElementById(closeId);

  function open() {
    overlay.classList.remove("hidden");
  }

  function close() {
    overlay.classList.add("hidden");
  }

  closeBtn.addEventListener("click", close);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });

  return { open, close };
}
