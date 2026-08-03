const menuToggle = document.getElementById("menu-toggle");
const drawer = document.getElementById("nav-drawer");
const backdrop = document.getElementById("nav-backdrop");

function closeDrawer() {
  drawer.classList.remove("open");
  backdrop.classList.remove("open");
}

menuToggle.addEventListener("click", () => {
  drawer.classList.toggle("open");
  backdrop.classList.toggle("open");
});

backdrop.addEventListener("click", closeDrawer);

let toastTimer = null;

function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.add("hidden"), 3500);
}
