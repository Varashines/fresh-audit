const API_URL = `${window.location.origin}/api/v1`;
let session = {
  token: null,
  user: null,
  role: null,
  wh: null,
  warehouses: [],
  isOnline: true,
  step: 1,
  activeTask: null,
  inputVal: "0",
  queue: [],
  auditLogs: [],
};

// --- GENERAL ROUTER ENGINE ---
function routeTo(pId) {
  ["login", "tasks", "counting"].forEach((p) => {
    const el = document.getElementById(`view-${p}`);
    if (el) el.classList.add("hidden");
  });
  const target = document.getElementById(`view-${pId}`);
  if (target) target.classList.remove("hidden");
}

// --- AUDIT TRAIL LOGGING ---
function logAuditAction(action, taskId, metadata) {
  session.auditLogs.push({
    timestamp: new Date().toISOString(),
    user_id: session.user || "unknown",
    audit_task_id: taskId || null,
    action_executed: action,
    device_ip: "client-side",
    device_metadata: metadata || null,
  });
}

// --- ECOSYSTEM GATEWAY AUTHENTICATION ---
async function handleEcosystemAuth() {
  const username = document.getElementById("loginUser").value.trim();
  const password = document.getElementById("loginPass").value;

  try {
    const res = await fetch(`${API_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });

    if (res.ok) {
      const data = await res.json();
      session.token = `Bearer ${data.access_token}`;
      session.user = data.username;
      session.role = data.role;
      session.warehouses = data.authorized_warehouses;

      logAuditAction("LOGIN", null, null);

      document.getElementById("view-login").classList.add("hidden");
      document.getElementById("globalSessionBadge").classList.remove("hidden");
      document.getElementById("sessionLabel").innerText =
        `${session.role} (${session.user})`;

      if (session.role === "CENTRAL_ADMIN") {
        document.getElementById("view-admin").classList.remove("hidden");
        await syncAdminDashboards();
      } else {
        document.getElementById("view-auditor").classList.remove("hidden");

        const whSelector = document.getElementById("warehouseSelector");
        const whDropdown = document.getElementById("auditorWH");

        if (session.warehouses.length > 1) {
          whDropdown.innerHTML = "";
          session.warehouses.forEach((wh) => {
            const opt = document.createElement("option");
            opt.value = wh;
            opt.textContent = wh;
            whDropdown.appendChild(opt);
          });
          whSelector.classList.remove("hidden");
          session.wh = session.warehouses[0];
        } else {
          whSelector.classList.add("hidden");
          session.wh = session.warehouses[0];
        }

        document.getElementById("auditorContextDisplay").innerText =
          `WH: ${session.wh} | Auditor: ${session.user}`;
        await fetchAuditorTasks();
      }
    } else {
      const err = await res.json();
      alert(`Security Halt: ${err.detail}`);
    }
  } catch (e) {
    alert(
      "Core Database Engine Connection Timeout. Ensure backend is running.",
    );
  }
}

function switchWarehouse(wh) {
  session.wh = wh;
  document.getElementById("auditorContextDisplay").innerText =
    `WH: ${session.wh} | Auditor: ${session.user}`;
  fetchAuditorTasks();
}

// --- AUDITOR WORKSPACE PROCESSORS ---
async function fetchAuditorTasks() {
  const container = document.getElementById("availableTasksContainer");
  container.innerHTML = '<p class="text-xs text-slate-500 font-mono p-3 animate-pulse">Loading tasks...</p>';

  try {
    const res = await fetch(
      `${API_URL}/tasks?warehouse_id=${encodeURIComponent(session.wh)}`,
      {
        headers: { Authorization: session.token },
        cache: "no-store",
      },
    );
    if (!res.ok) {
      const err = await res.json();
      console.error("Task fetch failed:", err.detail);
      container.innerHTML = `<p class="text-xs text-red-400 font-mono p-3">Failed to load tasks: ${err.detail}</p>`;
      return;
    }
    const tasks = await res.json();
    container.innerHTML = "";

    if (tasks.length === 0) {
      container.innerHTML = '<p class="text-xs text-slate-500 font-mono p-3">No pending audit tasks for this warehouse.</p>';
      return;
    }

    tasks.forEach((t) => {
      const item = document.createElement("div");
      item.className =
        "p-3 bg-slate-900 border border-slate-800 rounded flex justify-between items-center cursor-pointer hover:border-amber-500 transition duration-150";
      item.innerHTML = `<div class='font-mono text-xs font-bold'>${t.id}<p class='text-[10px] text-slate-500'>${t.location}</p></div><span class='text-[10px] text-amber-500 font-bold uppercase'>Ready</span>`;
      item.onclick = () => initiateCountingSequence(t);
      container.appendChild(item);
    });
  } catch (e) {
    console.error("Failed fetching operator tasks manifest", e);
    container.innerHTML = '<p class="text-xs text-red-400 font-mono p-3">Network error. Check connection.</p>';
  }
}

function initiateCountingSequence(task) {
  session.activeTask = task;
  session.step = 1;
  session.inputVal = "0";

  document.getElementById("uiTaskId").innerText = task.id;
  document.getElementById("uiShelf").innerText = task.location;
  document.getElementById("uiItem").innerText = task.item;
  document.getElementById("numDisplay").innerText = "0";

  document.getElementById("pane-tasks").classList.add("hidden");
  document.getElementById("pane-counting").classList.remove("hidden");

  logAuditAction("START_COUNT", task.id, `location=${task.location},sku=${task.sku}`);

  advanceScanStep(1);
}

function advanceScanStep(s) {
  session.step = s;
  [1, 2, 3].forEach((step) => {
    document
      .getElementById(`step${step}`)
      .classList.toggle("hidden", step !== s);
    document.getElementById(`bar${step}`).className =
      step === s
        ? "h-1 bg-amber-500 rounded animate-pulse"
        : step < s
          ? "h-1 bg-emerald-500 rounded"
          : "h-1 bg-slate-800 rounded";
  });

  if (s === 2) {
    logAuditAction("LOCATION_SCAN", session.activeTask?.id, `location=${session.activeTask?.location}`);
  } else if (s === 3) {
    logAuditAction("SKU_SCAN", session.activeTask?.id, `sku=${session.activeTask?.sku}`);
  }
}

function pressNum(k) {
  if (k === "CLR") {
    session.inputVal = "0";
  } else if (session.inputVal === "0") {
    session.inputVal = k;
  } else {
    session.inputVal = session.inputVal + k;
  }
  document.getElementById("numDisplay").innerText = session.inputVal;
}

async function submitHandheldCount() {
  const qty = parseInt(session.inputVal);
  if (isNaN(qty) || qty < 0) {
    alert("Invalid count. Please enter a non-negative number.");
    return;
  }

  const confirmed = confirm(
    `Confirm count: ${qty} units of ${session.activeTask.item} at ${session.activeTask.location}?`
  );
  if (!confirmed) return;

  try {
    const taskSku = session.activeTask.sku;
    const completedTaskId = session.activeTask.id;

    const subRecord = {
      submission_id: crypto.randomUUID(),
      audit_task_id: completedTaskId,
      warehouse_id: session.wh,
      shelf_location: session.activeTask.location,
      item_sku: taskSku,
      audited_quantity: qty,
      submitted_at: new Date().toISOString(),
    };

    logAuditAction("SUBMIT_COUNT", completedTaskId, `quantity=${qty}`);

    const logsToSend = [...session.auditLogs];
    session.auditLogs = [];

    session.queue.push(subRecord);
    document.getElementById("mobileSyncBadge").innerText =
      `Queue: ${session.queue.length}`;

    document.getElementById("pane-counting").classList.add("hidden");
    document.getElementById("pane-tasks").classList.remove("hidden");

    let syncSucceeded = false;

    if (session.isOnline) {
      try {
        const res = await fetch(`${API_URL}/sync`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: session.token,
          },
          body: JSON.stringify({ submissions: session.queue, logs: logsToSend }),
          cache: "no-store",
        });

        if (res.ok) {
          const result = await res.json();
          session.queue = [];
          document.getElementById("mobileSyncBadge").innerText = "Queue: 0";
          syncSucceeded = true;
          showToast(`Synced ${result.metrics.synced} count(s). Master ledger updated.`);
        } else {
          const errBody = await res.json().catch(() => ({ detail: res.statusText }));
          console.error("Server ingestion failure:", errBody);
          showPersistentError(`Sync failed (${res.status}): ${errBody.detail || "Unknown error"}. Count saved locally — retrying.`);
        }
      } catch (netErr) {
        console.error("Network pipe broken during sync:", netErr);
        showPersistentError("Network error. Count saved locally — will retry when online.");
      }
    } else {
      showToast("Offline mode active. Buffered to local storage queue.");
    }

    hideCompletedTask(completedTaskId);

    await new Promise((r) => setTimeout(r, 500));
    await fetchAuditorTasks();
  } catch (err) {
    console.error("Fatal workflow tracking crash:", err);
    document.getElementById("pane-counting").classList.add("hidden");
    document.getElementById("pane-tasks").classList.remove("hidden");
  }
}

async function executeBackgroundSync() {
  if (session.queue.length === 0) return;
  try {
    const res = await fetch(`${API_URL}/sync`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: session.token,
      },
      body: JSON.stringify({ submissions: session.queue, logs: session.auditLogs }),
      cache: "no-store",
    });
    if (res.ok) {
      session.queue = [];
      session.auditLogs = [];
      document.getElementById("mobileSyncBadge").innerText = "Queue: 0";
      dismissSyncError();
      showToast("Sync Successful. Cloud database updated.");
    } else {
      const errBody = await res.json().catch(() => ({ detail: res.statusText }));
      console.error("Background sync failure:", errBody);
      showPersistentError(`Sync failed: ${errBody.detail || "Unknown error"}.`);
    }
  } catch (e) {
    console.error("Sync daemon paused due to connection state.");
    showPersistentError("Network error. Will retry when connection is restored.");
  }
}

function toggleOfflineMode() {
  session.isOnline = !session.isOnline;
  const btn = document.getElementById("netBtn");
  btn.innerText = session.isOnline ? "ONLINE" : "OFFLINE";
  btn.className = session.isOnline
    ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 rounded text-[10px] font-bold"
    : "bg-red-500/10 text-red-400 border border-red-500/20 px-2 py-0.5 rounded text-[10px] font-bold animate-pulse";

  if (session.isOnline && session.queue.length > 0) {
    executeBackgroundSync();
  }
}

function resetCountingWorkflow() {
  session.step = 1;
  session.activeTask = null;
  session.inputVal = "0";

  document.getElementById("pane-counting").classList.add("hidden");
  document.getElementById("pane-tasks").classList.remove("hidden");
}

// --- CENTRAL COMMAND BOARD CONTROLLERS ---
let masterData = { warehouses: [], shelf_locations: [], items: [] };

async function loadMasterData() {
  try {
    const res = await fetch(`${API_URL}/admin/master-data`, {
      headers: { Authorization: session.token },
      cache: "no-store",
    });
    if (!res.ok) throw new Error("Failed to fetch master data");
    masterData = await res.json();

    const whSelect = document.getElementById("taskWH");
    whSelect.innerHTML = "";
    if (masterData.warehouses.length === 0) {
      whSelect.innerHTML = '<option value="">No warehouses found</option>';
    } else {
      masterData.warehouses.forEach((wh) => {
        const opt = document.createElement("option");
        opt.value = wh;
        opt.textContent = wh;
        whSelect.appendChild(opt);
      });
    }

    const whBox = document.getElementById("whCheckboxes");
    whBox.innerHTML = "";
    if (masterData.warehouses.length === 0) {
      whBox.innerHTML = '<p class="text-[10px] text-slate-500">No warehouses found</p>';
    } else {
      masterData.warehouses.forEach((wh) => {
        const label = document.createElement("label");
        label.className = "flex items-center gap-2";
        label.innerHTML = `<input type="checkbox" value="${wh}" class="wh-cb" /> ${wh}`;
        whBox.appendChild(label);
      });
    }

    setupCombobox("taskShelf", "shelfDropdown", masterData.shelf_locations, null);
    setupCombobox("taskSku", "skuDropdown", masterData.items.map((i) => i.sku), (selectedSku) => {
      const match = masterData.items.find((i) => i.sku === selectedSku);
      if (match) {
        document.getElementById("taskItemName").value = match.name;
      }
    });
  } catch (e) {
    console.error("Failed to load master data", e);
  }
}

function setupCombobox(inputId, dropdownId, options, onSelect) {
  const input = document.getElementById(inputId);
  const dropdown = document.getElementById(dropdownId);

  input.addEventListener("input", () => {
    const val = input.value.toLowerCase();
    dropdown.innerHTML = "";
    if (val.length === 0) {
      options.forEach((opt) => addComboboxItem(dropdown, input, opt, onSelect));
    } else {
      const filtered = options.filter((o) => o.toLowerCase().includes(val));
      filtered.forEach((opt) => addComboboxItem(dropdown, input, opt, onSelect));
    }
    dropdown.classList.toggle("hidden", dropdown.children.length === 0);
  });

  input.addEventListener("focus", () => {
    dropdown.innerHTML = "";
    options.forEach((opt) => addComboboxItem(dropdown, input, opt, onSelect));
    dropdown.classList.remove("hidden");
  });

  input.addEventListener("blur", () => {
    setTimeout(() => dropdown.classList.add("hidden"), 150);
  });
}

function addComboboxItem(dropdown, input, value, onSelect) {
  const div = document.createElement("div");
  div.className = "combobox-item";
  div.textContent = value;
  div.addEventListener("mousedown", (e) => {
    e.preventDefault();
    input.value = value;
    if (onSelect) onSelect(value);
  });
  dropdown.appendChild(div);
}

async function syncAdminDashboards() {
  await loadMasterData();

  try {
    const usersRes = await fetch(`${API_URL}/admin/users`, {
      headers: { Authorization: session.token },
      cache: "no-store",
    });
    if (!usersRes.ok) throw new Error("Failed to fetch users");
    const users = await usersRes.json();
    const uBody = document.getElementById("adminUserTableBody");
    uBody.innerHTML = "";

    users.forEach((u) => {
      const tr = document.createElement("tr");
      tr.className = "border-b border-slate-800/40";
      tr.innerHTML = `<td class="py-2 font-mono font-bold">${u.username}</td><td>${u.role}</td><td class="font-mono text-amber-500">${u.authorized_warehouses.join(", ")}</td>`;
      uBody.appendChild(tr);
    });

    const vRes = await fetch(`${API_URL}/admin/variance-report`, {
      headers: { Authorization: session.token },
      cache: "no-store",
    });
    if (!vRes.ok) throw new Error("Failed to fetch variance report");
    const vData = await vRes.json();
    const vBody = document.getElementById("adminVarianceTableBody");
    vBody.innerHTML = "";

    vData.forEach((v) => {
      const tr = document.createElement("tr");
      tr.className = "border-b border-slate-800/40 py-2";
      const shrinkColor = v.shrinkage_rate !== null
        ? v.shrinkage_rate > 0 ? "text-red-400" : v.shrinkage_rate < 0 ? "text-blue-400" : "text-emerald-400"
        : "";
      const shrinkLabel = v.shrinkage_rate !== null
        ? (v.shrinkage_rate > 0 ? `${v.shrinkage_rate}%` : v.shrinkage_rate < 0 ? `+${Math.abs(v.shrinkage_rate)}% (overstock)` : "0%")
        : "Pending";
      tr.innerHTML = `<td class="py-2 font-mono text-amber-400">${v.audit_task_id}</td><td>${v.warehouse_id}</td><td>${v.shelf_location}</td><td>${v.item_name}</td><td class="text-right">${v.snapshot_quantity}</td><td class="text-right">${v.audited_quantity ?? "Pending"}</td><td class="text-right font-bold ${shrinkColor}">${shrinkLabel}</td>`;
      vBody.appendChild(tr);
    });

    window._lastVarianceData = vData;
  } catch (e) {
    console.error("Admin dashboard tracking extraction error.", e);
  }
}

function downloadCSV() {
  const data = window._lastVarianceData;
  if (!data || data.length === 0) {
    alert("No variance data available to download.");
    return;
  }

  const headers = ["Task ID", "Warehouse ID", "Item SKU", "Item Name", "Shelf Location", "Snapshot Quantity", "Audited Quantity", "Shrinkage Rate (%)"];
  const rows = data.map((v) => [
    v.audit_task_id,
    v.warehouse_id,
    v.item_sku,
    v.item_name,
    v.shelf_location,
    v.snapshot_quantity,
    v.audited_quantity ?? "",
    v.shrinkage_rate ?? "",
  ]);

  const csvContent = [headers, ...rows].map((r) => r.map((c) => `"${c}"`).join(",")).join("\n");
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `FreshAudit_Variance_${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
}

async function submitNewUserMapping() {
  const username = document.getElementById("newUsr").value.trim();
  const password = document.getElementById("newPwd").value;
  const role = document.getElementById("newRole").value;
  let authorized_warehouses = [];

  document.querySelectorAll(".wh-cb").forEach((cb) => {
    if (cb.checked) authorized_warehouses.push(cb.value);
  });

  if (!username || !password || authorized_warehouses.length === 0) {
    alert("All fields and at least one checkbox mapping mandatory.");
    return;
  }

  const res = await fetch(`${API_URL}/admin/users`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: session.token,
    },
    body: JSON.stringify({ username, password, role, authorized_warehouses }),
  });

  if (res.ok) {
    document.getElementById("newUsr").value = "";
    document.getElementById("newPwd").value = "";
    document.querySelectorAll(".wh-cb").forEach((cb) => (cb.checked = false));
    await syncAdminDashboards();
    showToast(`User ${username} created successfully.`);
  } else {
    const err = await res.json();
    alert(`Failed: ${err.detail}`);
  }
}

async function scheduleAuditTaskSnapshot() {
  const warehouse_id = document.getElementById("taskWH").value;
  const shelf_location = document.getElementById("taskShelf").value.trim();
  const snapshot_quantity = parseInt(document.getElementById("taskQty").value);
  const item_sku = document.getElementById("taskSku").value.trim();
  const item_name = document.getElementById("taskItemName").value.trim();

  if (!warehouse_id) {
    alert("Please select a target warehouse.");
    return;
  }

  if (!shelf_location) {
    alert("Please enter or select a shelf location.");
    return;
  }

  if (!item_sku || !item_name) {
    alert("Item SKU and Item Name are required.");
    return;
  }

  if (isNaN(snapshot_quantity) || snapshot_quantity <= 0) {
    alert("Expected stock must be a positive number.");
    return;
  }

  const taskId = `TASK-${Date.now()}-${crypto.randomUUID().slice(0, 8)}`;

  const res = await fetch(`${API_URL}/admin/tasks`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: session.token,
    },
    body: JSON.stringify({
      task_id: taskId,
      warehouse_id,
      items: [
        {
          item_sku,
          item_name,
          shelf_location,
          snapshot_quantity,
        },
      ],
    }),
  });

  if (res.ok) {
    await syncAdminDashboards();
    showToast(`Task ${taskId} created successfully.`);
  } else {
    const err = await res.json();
    alert(`Failed: ${err.detail}`);
  }
}

// --- UTILITIES ---
function showToast(msg) {
  const t = document.getElementById("deviceToast");
  document.getElementById("toastMessage").innerText = msg;
  t.className =
    "opacity-100 fixed bottom-4 max-w-xs bg-slate-900 border-l-4 border-amber-500 text-slate-200 p-3 rounded shadow-2xl text-xs z-50 transition-all duration-300";
  setTimeout(() => {
    t.className =
      "opacity-0 fixed bottom-4 max-w-xs bg-slate-900 border-l-4 border-amber-500 text-slate-200 p-3 rounded shadow-2xl text-xs pointer-events-none transition-all duration-300";
  }, 3000);
}

function showPersistentError(msg) {
  const banner = document.getElementById("syncErrorBanner");
  const msgEl = document.getElementById("syncErrorMsg");
  if (banner && msgEl) {
    msgEl.innerText = msg;
    banner.classList.remove("hidden");
    banner.classList.add("flex");
  }
  showToast(msg);
}

function dismissSyncError() {
  const banner = document.getElementById("syncErrorBanner");
  if (banner) {
    banner.classList.add("hidden");
    banner.classList.remove("flex");
  }
}

function hideCompletedTask(taskId) {
  const container = document.getElementById("availableTasksContainer");
  if (!container) return;
  const items = container.children;
  for (let i = items.length - 1; i >= 0; i--) {
    const el = items[i];
    if (el.querySelector && el.querySelector("div")?.innerText?.includes(taskId)) {
      el.className =
        "p-3 bg-emerald-950 border border-emerald-500/30 rounded flex justify-between items-center transition-all duration-300 opacity-50 pointer-events-none";
      const badge = el.querySelector("span");
      if (badge) {
        badge.className = "text-[10px] text-emerald-400 font-bold uppercase";
        badge.innerText = "Submitted";
      }
    }
  }
}

async function retryPendingSync() {
  dismissSyncError();
  if (session.queue.length === 0) return;
  await executeBackgroundSync();
  await fetchAuditorTasks();
}

function terminateSession() {
  session = {
    token: null,
    user: null,
    role: null,
    wh: null,
    warehouses: [],
    isOnline: true,
    step: 1,
    activeTask: null,
    inputVal: "0",
    queue: [],
    auditLogs: [],
  };
  location.reload();
}
