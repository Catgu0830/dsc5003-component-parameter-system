// Administrator operation log viewer.

document.addEventListener("DOMContentLoaded", async () => {

    if (!getToken()) {
        window.location.href = "../login.html";
        return;
    }

    let currentUser = null;
    let currentPage = 1;
    let totalPages = 1;

    function show(text, type = "") {
        const element = document.getElementById("logMessage");
        element.textContent = text;
        element.className = "form-message " + type;
    }

    function formatDate(value) {
        if (!value) return "-";
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("en-US");
    }

    function safeText(value) {
        return value === null || value === undefined || value === "" ? "-" : String(value);
    }

    async function loadCurrentUser() {
        const cached = localStorage.getItem("currentUser");
        if (cached) {
            try { currentUser = JSON.parse(cached); } catch { currentUser = null; }
        }
        if (!currentUser || !currentUser.role) {
            const response = await apiRequest("/api/auth/me");
            currentUser = response.data;
            localStorage.setItem("currentUser", JSON.stringify(currentUser));
        }
    }

    async function loadLogs() {
        try {
            const response = await apiRequest(`/api/logs?page=${currentPage}&page_size=50`);
            const data = response.data || {};
            const items = data.items || [];
            document.getElementById("logCount").textContent = `${data.total ?? items.length} log(s)`;
            renderLogs(items);
            totalPages = Math.max(1, Math.ceil(Number(data.total ?? 0) / Number(data.page_size ?? 50)));
            document.getElementById("pageInfo").textContent = `Page ${currentPage} / ${totalPages}`;
            document.getElementById("prevPage").disabled = currentPage <= 1;
            document.getElementById("nextPage").disabled = currentPage >= totalPages;
        } catch (error) {
            document.getElementById("logTableBody").innerHTML =
                '<tr><td colspan="6">Unable to load logs.</td></tr>';
            show(error.message, "error");
        }
    }

    function renderLogs(items) {
        const body = document.getElementById("logTableBody");
        body.innerHTML = "";
        if (!items.length) {
            body.innerHTML = '<tr><td colspan="6">No log entries.</td></tr>';
            return;
        }
        items.forEach(item => {
            const row = document.createElement("tr");
            const target = [item.target_type, item.target_id].filter(Boolean).join(" #");
            [
                formatDate(item.created_time),
                item.username || item.user_id,
                item.action,
                target || "-",
                JSON.stringify(item.detail || {}),
                item.ip_address
            ].forEach(value => {
                const cell = document.createElement("td");
                cell.textContent = safeText(value);
                row.appendChild(cell);
            });
            body.appendChild(row);
        });
    }

    document.getElementById("prevPage").addEventListener("click", () => {
        if (currentPage > 1) {
            currentPage--;
            loadLogs();
        }
    });

    document.getElementById("nextPage").addEventListener("click", () => {
        if (currentPage < totalPages) {
            currentPage++;
            loadLogs();
        }
    });

    document.getElementById("backHome").addEventListener("click", () => {
        window.location.href = "dashboard.html";
    });

    try {
        await loadCurrentUser();
        if (currentUser.role !== "admin") {
            show("Only administrators can view operation logs.", "error");
            document.getElementById("logTableBody").innerHTML =
                '<tr><td colspan="6">Administrator access required.</td></tr>';
            return;
        }
        await loadLogs();
    } catch (error) {
        show(error.message, "error");
        if (error.message.includes("401")) {
            clearAuth();
            window.location.href = "../login.html";
        }
    }
});
