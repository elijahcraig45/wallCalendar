const accountList = document.getElementById("account-list");

async function post(path, body) {
  const resp = await fetch(path, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!resp.ok) {
    let message = "Something went wrong";
    try {
      const data = await resp.json();
      message = data.error || message;
    } catch (e) {
      // response body wasn't JSON - keep the generic message
    }
    showToast(message);
    return false;
  }
  return true;
}

const HEALTH_COPY = {
  needs_reauth: "Needs reconnecting",
  transient: "Couldn't verify right now",
  unknown: "May need reconnecting",
};

async function loadAccounts() {
  const [accountsResp, health] = await Promise.all([
    fetch("/api/calendar/accounts").then((r) => r.json()),
    fetch("/api/calendar/accounts/health").then((r) => r.json()),
  ]);
  const healthByEmail = {};
  health.forEach((h) => { healthByEmail[h.email] = h; });

  accountList.innerHTML = "";

  if (accountsResp.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No Google accounts signed in yet.";
    accountList.appendChild(li);
    return;
  }

  accountsResp.forEach((acct) => {
    const li = document.createElement("li");
    const h = healthByEmail[acct.email];

    const title = document.createElement("div");
    title.className = "row-title";

    const nameInput = document.createElement("input");
    nameInput.className = "text-input";
    nameInput.value = acct.label;
    nameInput.addEventListener("change", async () => {
      const ok = await post(
        `/api/calendar/accounts/${encodeURIComponent(acct.email)}/label`,
        { label: nameInput.value }
      );
      if (ok) showToast("Saved");
    });
    title.appendChild(nameInput);

    const sub = document.createElement("span");
    sub.className = "row-subtext";
    sub.textContent = acct.email;
    title.appendChild(sub);

    if (h && !h.ok) {
      const badge = document.createElement("span");
      badge.className = `health-badge health-badge--${h.kind}`;
      badge.textContent = HEALTH_COPY[h.kind] || "Couldn't verify right now";
      title.appendChild(badge);
    }

    li.appendChild(title);

    if (h && !h.ok && h.kind !== "transient") {
      const reconnectLink = document.createElement("a");
      reconnectLink.className = "reconnect-button";
      reconnectLink.textContent = "Reconnect";
      reconnectLink.href = `/auth/google/start?reauth=${encodeURIComponent(acct.email)}`;
      li.appendChild(reconnectLink);
    }

    const removeBtn = document.createElement("button");
    removeBtn.textContent = "Sign out";
    removeBtn.addEventListener("click", async () => {
      const ok = await post(
        `/api/calendar/accounts/${encodeURIComponent(acct.email)}/remove`
      );
      if (ok) {
        showToast("Signed out");
        loadAccounts();
      }
    });
    li.appendChild(removeBtn);

    accountList.appendChild(li);
  });
}

const params = new URLSearchParams(window.location.search);
if (params.get("mismatch")) {
  showToast(`Signed in as ${params.get("signed_in")} — ${params.get("mismatch")} still needs reconnecting`);
  window.history.replaceState({}, "", "/accounts");
} else if (params.get("signed_in")) {
  showToast(`Signed in as ${params.get("signed_in")}`);
  window.history.replaceState({}, "", "/accounts");
} else if (params.get("error")) {
  showToast(`Sign-in failed: ${params.get("error")}`);
  window.history.replaceState({}, "", "/accounts");
}

loadAccounts();
