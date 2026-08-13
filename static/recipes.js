/* Recipes, read from Daisy's Kitchen's Firestore via /api/recipes.
 *
 * Three views in one page, switched rather than navigated: the grid, a recipe,
 * and cooking mode. Cooking mode is the reason this isn't just an iframe of the
 * Flutter app - one step at a time in type you can read from across a kitchen,
 * with the step's timer one tap away.
 */

const recipesGrid = document.getElementById("recipes-grid");
const recipesFilters = document.getElementById("recipes-filters");
const recipesNote = document.getElementById("recipes-note");
const browseView = document.getElementById("recipes-browse");
const detailView = document.getElementById("recipe-detail");
const detailHead = document.getElementById("recipe-detail-head");
const ingredientsEl = document.getElementById("recipe-ingredients");
const stepsEl = document.getElementById("recipe-steps");
const titleEl = document.getElementById("recipes-title");
const backBtn = document.getElementById("recipes-back");
const cookStartBtn = document.getElementById("cook-start");
const cookExitBtn = document.getElementById("cook-exit");

const cookMode = document.getElementById("cook-mode");
const cookProgress = document.getElementById("cook-progress");
const cookStep = document.getElementById("cook-step");
const cookIngredients = document.getElementById("cook-ingredients");
const cookPrev = document.getElementById("cook-prev");
const cookNext = document.getElementById("cook-next");
const cookTimer = document.getElementById("cook-timer");

let all = [];
let categoryFilter = null;
let current = null;
let stepIndex = 0;

function show(which) {
  browseView.classList.toggle("hidden", which !== "browse");
  detailView.classList.toggle("hidden", which !== "detail");
  cookMode.classList.toggle("hidden", which !== "cook");
  backBtn.classList.toggle("hidden", which === "browse");
  cookStartBtn.classList.toggle("hidden", which !== "detail");
  cookExitBtn.classList.toggle("hidden", which !== "cook");
  titleEl.textContent =
    which === "browse" ? "Recipes" : current ? current.title : "Recipes";
}

function timeLabel(recipe) {
  const parts = [];
  if (recipe.total_minutes) parts.push(`${recipe.total_minutes} min`);
  if (recipe.servings) parts.push(`serves ${recipe.servings}`);
  if (recipe.difficulty) parts.push(recipe.difficulty);
  return parts.join(" · ");
}

function renderGrid() {
  const shown = categoryFilter
    ? all.filter((recipe) => recipe.category === categoryFilter)
    : all;

  recipesGrid.innerHTML = "";
  shown.forEach((recipe) => {
    const card = document.createElement("button");
    card.className = "recipe-card";

    const art = document.createElement("div");
    art.className = "recipe-art";
    if (recipe.image) {
      const img = document.createElement("img");
      img.src = recipe.image;
      img.alt = "";
      img.loading = "lazy";
      // Plenty of recipes have no image, and a broken one looks worse than none.
      img.addEventListener("error", () => img.remove());
      art.appendChild(img);
    } else {
      art.classList.add("recipe-art--empty");
      art.textContent = recipe.title.slice(0, 1).toUpperCase();
    }
    card.appendChild(art);

    const meta = document.createElement("div");
    meta.className = "recipe-card-meta";
    meta.innerHTML = `<div class="recipe-card-title">${escapeHtml(recipe.title)}</div>
      <div class="recipe-card-sub">${escapeHtml(timeLabel(recipe))}</div>`;
    card.appendChild(meta);

    card.addEventListener("click", () => openRecipe(recipe));
    recipesGrid.appendChild(card);
  });

  if (shown.length === 0) {
    recipesGrid.innerHTML = '<p class="field-hint">No recipes here yet.</p>';
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : text;
  return div.innerHTML;
}

function renderFilters() {
  recipesFilters.innerHTML = "";
  const categories = [null, ...new Set(all.map((r) => r.category).filter(Boolean))];
  categories.forEach((category) => {
    const button = document.createElement("button");
    button.className = "pill-button";
    button.textContent = category || "All";
    button.classList.toggle("pill-button--accent", categoryFilter === category);
    button.addEventListener("click", () => {
      categoryFilter = category;
      renderFilters();
      renderGrid();
    });
    recipesFilters.appendChild(button);
  });
}

function openRecipe(recipe) {
  current = recipe;
  stepIndex = 0;

  detailHead.innerHTML = `
    <div class="recipe-detail-title">${escapeHtml(recipe.title)}</div>
    <div class="recipe-detail-sub">${escapeHtml(timeLabel(recipe))}</div>
    ${recipe.description ? `<p class="recipe-detail-desc">${escapeHtml(recipe.description)}</p>` : ""}`;

  ingredientsEl.innerHTML = `<h3>Ingredients</h3>`;
  const list = document.createElement("ul");
  list.className = "ingredient-list";
  recipe.ingredients.forEach((ingredient) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="ingredient-amount">${escapeHtml(ingredient.amount)}</span>
      <span>${escapeHtml(ingredient.name)}</span>`;
    list.appendChild(li);
  });
  ingredientsEl.appendChild(list);

  stepsEl.innerHTML = `<h3>Method</h3>`;
  const ol = document.createElement("ol");
  ol.className = "step-list";
  recipe.steps.forEach((step) => {
    const li = document.createElement("li");
    li.innerHTML =
      (step.title ? `<div class="step-title">${escapeHtml(step.title)}</div>` : "") +
      `<div>${escapeHtml(step.instruction)}</div>`;
    ol.appendChild(li);
  });
  stepsEl.appendChild(ol);

  if (recipe.notes) {
    const notes = document.createElement("p");
    notes.className = "recipe-notes";
    notes.textContent = recipe.notes;
    stepsEl.appendChild(notes);
  }

  show("detail");
}

/* ---------- cooking mode ---------- */

function renderCookStep() {
  const steps = current.steps;
  const step = steps[stepIndex];
  cookProgress.textContent = `Step ${stepIndex + 1} of ${steps.length}`;
  cookStep.innerHTML =
    (step.title ? `<div class="cook-step-title">${escapeHtml(step.title)}</div>` : "") +
    `<div class="cook-step-text">${escapeHtml(step.instruction)}</div>`;

  cookPrev.disabled = stepIndex === 0;
  cookNext.textContent = stepIndex === steps.length - 1 ? "Finish" : "Next step";

  // Only offered when the recipe actually specifies one - inventing a duration
  // would be worse than not offering it.
  if (step.timer_seconds) {
    const minutes = Math.round(step.timer_seconds / 60);
    cookTimer.textContent = `Start ${minutes} min timer`;
    cookTimer.classList.remove("hidden");
    cookTimer.onclick = () => {
      window.startKitchenTimer(step.timer_seconds, step.timer_label || current.title);
    };
  } else {
    cookTimer.classList.add("hidden");
    cookTimer.onclick = null;
  }

  cookIngredients.innerHTML = "";
  current.ingredients.forEach((ingredient) => {
    const li = document.createElement("li");
    li.textContent = `${ingredient.amount} ${ingredient.name}`.trim();
    cookIngredients.appendChild(li);
  });
}

cookStartBtn.addEventListener("click", () => {
  if (!current || current.steps.length === 0) {
    showToast("This recipe has no steps to follow.");
    return;
  }
  stepIndex = 0;
  renderCookStep();
  show("cook");
});

cookExitBtn.addEventListener("click", () => show("detail"));
backBtn.addEventListener("click", () => show("browse"));

cookPrev.addEventListener("click", () => {
  if (stepIndex > 0) {
    stepIndex -= 1;
    renderCookStep();
  }
});

cookNext.addEventListener("click", () => {
  if (stepIndex < current.steps.length - 1) {
    stepIndex += 1;
    renderCookStep();
  } else {
    show("detail");
    showToast("Enjoy.");
  }
});

async function load() {
  try {
    const resp = await fetch("/api/recipes");
    const data = await resp.json();
    all = data.recipes || [];
    renderFilters();
    renderGrid();
    recipesNote.textContent = data.errors && data.errors.length
      ? data.errors[0]
      : `${all.length} recipes from Daisy's Kitchen${data.stale ? " (offline copy)" : ""}`;
  } catch (e) {
    recipesNote.textContent = "Couldn't load recipes.";
  }
}

show("browse");
load();
