// Parameter-level audit page for the 11-table schema.

document.addEventListener("DOMContentLoaded", async () => {

    if (!getToken()) {
        window.location.href = "../login.html";
        return;
    }

    let currentUser = null;
    let canAudit = false;
    let currentPage = 1;
    let totalPages = 1;
    let currentTask = null;
    let currentTaskId = null;
    let catalogParameters = [];
    let categories = [];

    function showMessage(id, message, type = "") {
        const element = document.getElementById(id);
        if (!element) return;
        element.textContent = message;
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

    function getSourceLabel(source) {
        const labels = {
            manual: "Manual Entry",
            url: "URL",
            pdf: "PDF",
            csv: "CSV",
            excel: "Excel",
            xlsx: "Excel"
        };
        return labels[source] || source || "-";
    }

    function taskId(task) {
        return task.task_id ?? task.id;
    }

    function componentsOf(task) {
        return task?.result?.components || task?.components || [];
    }

    function handleAuthError(error) {
        if (!error) return;
        if (error.message.includes("401")) {
            clearAuth();
            window.location.href = "../login.html";
            return;
        }
        if (error.message.includes("403")) {
            showMessage("listMessage", "You do not have permission to review parameters.", "error");
        }
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
        if (currentUser.role === "user") {
            window.location.href = "dashboard.html";
            return false;
        }
        canAudit = currentUser.role === "auditor";
        return true;
    }

    async function loadCatalog() {
        const [categoryResponse, parameterResponse] = await Promise.all([
            apiRequest("/api/categories"),
            apiRequest("/api/parameters")
        ]);
        categories = categoryResponse.data?.items || [];
        catalogParameters = parameterResponse.data?.items || [];

        const select = document.getElementById("identityCategory");
        select.innerHTML = "";
        const blank = document.createElement("option");
        blank.value = "";
        blank.textContent = "Select a category";
        select.appendChild(blank);
        categories.forEach(category => {
            const option = document.createElement("option");
            option.value = category.name;
            option.textContent = category.name;
            select.appendChild(option);
        });
    }

    function renderReviews(items, total) {
        const body = document.getElementById("pendingBody");
        body.innerHTML = "";
        document.getElementById("reviewCount").textContent =
            `${total} pending task(s)`;

        if (!items.length) {
            body.innerHTML = '<tr><td colspan="7">No pending reviews found.</td></tr>';
            return;
        }

        items.forEach(task => {
            const row = document.createElement("tr");
            const components = componentsOf(task);
            const first = components[0] || {};
            const values = [
                taskId(task),
                getSourceLabel(task.source_type),
                first.model || task.extracted_model || "-",
                first.manufacturer || task.extracted_manufacturer || "-",
                `${task.pending_count ?? 0} / ${task.param_count ?? 0}`,
                formatDate(task.created_time)
            ];
            values.forEach(value => {
                const cell = document.createElement("td");
                cell.textContent = safeText(value);
                row.appendChild(cell);
            });

            const actionCell = document.createElement("td");
            const button = document.createElement("button");
            button.className = "primary-button";
            button.textContent = "Review";
            button.addEventListener("click", () => openReview(taskId(task)));
            actionCell.appendChild(button);
            row.appendChild(actionCell);
            body.appendChild(row);
        });
    }

    async function loadReviews() {
        showMessage("listMessage", "");
        document.getElementById("pendingBody").innerHTML =
            '<tr><td colspan="7">Loading reviews...</td></tr>';
        const params = new URLSearchParams({ page: currentPage, page_size: 20 });
        try {
            const response = await apiRequest(`/api/audit/tasks?${params.toString()}`);
            const data = response.data || {};
            const items = data.items || [];
            const total = Number(data.total ?? items.length);
            const pageSize = Number(data.page_size ?? 20);
            currentPage = Number(data.page ?? currentPage);
            totalPages = Math.max(1, Math.ceil(total / pageSize));
            renderReviews(items, total);
            document.getElementById("pageInfo").textContent =
                `Page ${currentPage} / ${totalPages}`;
            document.getElementById("prevPage").disabled = currentPage <= 1;
            document.getElementById("nextPage").disabled = currentPage >= totalPages;
        } catch (error) {
            document.getElementById("pendingBody").innerHTML =
                '<tr><td colspan="7">Unable to load pending reviews.</td></tr>';
            showMessage("listMessage", error.message, "error");
            handleAuthError(error);
        }
    }

    function appendInfo(container, label, value) {
        const item = document.createElement("div");
        item.className = "task-info-item";
        const heading = document.createElement("strong");
        heading.textContent = label;
        const content = document.createElement("span");
        content.textContent = safeText(value);
        item.appendChild(heading);
        item.appendChild(content);
        container.appendChild(item);
    }

    function renderTaskInfo(task) {
        const container = document.getElementById("taskInfo");
        container.innerHTML = "";
        appendInfo(container, "Source", getSourceLabel(task.source_type));
        appendInfo(container, "Source Location", task.source_location);
        appendInfo(container, "Status", task.status);
        appendInfo(container, "Review State", task.review_state);
        appendInfo(container, "Parameters", `${task.approved_count ?? 0} approved / ${task.rejected_count ?? 0} rejected / ${task.pending_count ?? 0} pending`);
        appendInfo(container, "Component ID", task.component_id);
        appendInfo(container, "Created", formatDate(task.created_time));
        appendInfo(container, "Finished", formatDate(task.finished_time));
    }

    function parameterOption(selectedId) {
        const select = document.createElement("select");
        select.className = "audit-param-map";
        const blank = document.createElement("option");
        blank.value = "";
        blank.textContent = "Unmapped — select parameter";
        select.appendChild(blank);
        catalogParameters.forEach(parameter => {
            const option = document.createElement("option");
            option.value = parameter.parameter_id;
            const unit = parameter.unit ? ` [${parameter.unit}]` : "";
            option.textContent = `${parameter.display_name} (${parameter.canonical_name})${unit}`;
            select.appendChild(option);
        });
        if (selectedId !== null && selectedId !== undefined) {
            select.value = String(selectedId);
            if (!select.value) {
                const option = document.createElement("option");
                option.value = String(selectedId);
                option.textContent = `Parameter #${selectedId}`;
                select.appendChild(option);
                select.value = String(selectedId);
            }
        }
        return select;
    }

    function renderParameters(parameters) {
        const body = document.getElementById("paramBody");
        body.innerHTML = "";
        if (!parameters.length) {
            body.innerHTML = '<tr><td colspan="10">No extraction parameters.</td></tr>';
            return;
        }

        parameters.forEach(parameter => {
            const row = document.createElement("tr");
            const pending = parameter.review_status === "pending";

            const idCell = document.createElement("td");
            idCell.textContent = parameter.extraction_param_id;
            row.appendChild(idCell);

            const nameCell = document.createElement("td");
            const nameInput = document.createElement("input");
            nameInput.className = "audit-param-name";
            nameInput.value = parameter.raw_name || "";
            nameInput.disabled = !pending || !canAudit;
            nameCell.appendChild(nameInput);
            row.appendChild(nameCell);

            const valueCell = document.createElement("td");
            const valueInput = document.createElement("input");
            valueInput.className = "audit-param-value";
            valueInput.value = parameter.raw_value || "";
            valueInput.disabled = !pending || !canAudit;
            valueCell.appendChild(valueInput);
            row.appendChild(valueCell);

            const mapCell = document.createElement("td");
            const mapSelect = parameterOption(parameter.parameter_id);
            mapSelect.disabled = !pending || !canAudit;
            mapSelect.addEventListener("change", () => {
                const selected = catalogParameters.find(
                    item => String(item.parameter_id) === mapSelect.value
                );
                const unit = row.querySelector(".audit-param-unit");
                if (selected && selected.unit && unit && !unit.value) {
                    unit.value = selected.unit;
                }
            });
            mapCell.appendChild(mapSelect);
            row.appendChild(mapCell);

            const numCell = document.createElement("td");
            const numInput = document.createElement("input");
            numInput.className = "audit-param-num";
            numInput.type = "number";
            numInput.step = "any";
            numInput.value = parameter.value_num ?? "";
            numInput.disabled = !pending || !canAudit;
            numCell.appendChild(numInput);
            row.appendChild(numCell);

            const unitCell = document.createElement("td");
            const unitInput = document.createElement("input");
            unitInput.className = "audit-param-unit";
            unitInput.value = parameter.unit || "";
            unitInput.disabled = !pending || !canAudit;
            unitCell.appendChild(unitInput);
            row.appendChild(unitCell);

            const confidenceCell = document.createElement("td");
            confidenceCell.textContent = parameter.confidence ?? "-";
            row.appendChild(confidenceCell);

            const pageCell = document.createElement("td");
            pageCell.textContent = parameter.source?.page ?? "-";
            if (parameter.source?.snippet) {
                pageCell.title = parameter.source.snippet;
            }
            row.appendChild(pageCell);

            const statusCell = document.createElement("td");
            statusCell.textContent = parameter.review_status;
            statusCell.className = "audit-status-" + parameter.review_status;
            row.appendChild(statusCell);

            const actionCell = document.createElement("td");
            if (canAudit && pending) {
                const approve = document.createElement("button");
                approve.className = "primary-button audit-action";
                approve.textContent = "Approve";
                approve.addEventListener("click", () => submitParam(parameter, row, "approve"));

                const reject = document.createElement("button");
                reject.className = "danger-button audit-action";
                reject.textContent = "Reject";
                reject.addEventListener("click", () => submitParam(parameter, row, "reject"));

                actionCell.appendChild(approve);
                actionCell.appendChild(reject);
            } else {
                actionCell.textContent = canAudit ? "-" : "Read only";
            }
            row.appendChild(actionCell);
            body.appendChild(row);
        });
    }

    function renderIdentity(task) {
        document.getElementById("identityModel").value = task.extracted_model || "";
        document.getElementById("identityManufacturer").value = task.extracted_manufacturer || "";
        document.getElementById("identityCategory").value = task.extracted_category || "";
        document.getElementById("identityPackage").value = task.extracted_package || "";
        if (task.extracted_category && !categories.some(item => item.name === task.extracted_category)) {
            const select = document.getElementById("identityCategory");
            if (!Array.from(select.options).some(option => option.value === task.extracted_category)) {
                const option = document.createElement("option");
                option.value = task.extracted_category;
                option.textContent = `${task.extracted_category} (not in dictionary)`;
                select.appendChild(option);
            }
            select.value = task.extracted_category;
        }
        const disabled = !canAudit;
        ["identityModel", "identityManufacturer", "identityCategory", "identityPackage", "saveIdentity"].forEach(id => {
            document.getElementById(id).disabled = disabled;
        });
    }

    function renderTask(task) {
        currentTask = task;
        currentTaskId = taskId(task);
        document.getElementById("reviewPanel").hidden = false;
        document.getElementById("reviewTaskId").textContent = `#${currentTaskId}`;
        renderTaskInfo(task);
        renderIdentity(task);
        const component = componentsOf(task)[0] || {};
        renderParameters(component.parameters || []);
        document.getElementById("reviewPanel").scrollIntoView({ behavior: "smooth" });
    }

    async function openReview(id) {
        showMessage("detailMessage", "");
        try {
            const response = await apiRequest(`/api/audit/tasks/${encodeURIComponent(id)}`);
            renderTask(response.data?.task || response.data);
        } catch (error) {
            showMessage("detailMessage", "Unable to load task: " + error.message, "error");
            handleAuthError(error);
        }
    }

    function rowPayload(row, action, parameter) {
        const map = row.querySelector(".audit-param-map");
        const valueNumText = row.querySelector(".audit-param-num").value.trim();
        return {
            action: action,
            parameter_id: map.value ? Number(map.value) : null,
            raw_name: row.querySelector(".audit-param-name").value.trim(),
            raw_value: row.querySelector(".audit-param-value").value.trim(),
            value_num: valueNumText === "" ? null : Number(valueNumText),
            unit: row.querySelector(".audit-param-unit").value.trim() || null
        };
    }

    async function submitParam(parameter, row, action) {
        const payload = rowPayload(row, action, parameter);
        if (action === "approve" && !payload.parameter_id) {
            showMessage("detailMessage", "Map the parameter to a definition before approving.", "error");
            return;
        }
        if (action === "reject") {
            const comment = prompt("Rejection comment (required):");
            if (comment === null) return;
            if (!comment.trim()) {
                showMessage("detailMessage", "Rejection requires a comment.", "error");
                return;
            }
            payload.comment = comment.trim();
        } else {
            payload.comment = "";
        }
        try {
            await apiRequest(`/api/audit/params/${parameter.extraction_param_id}`, {
                method: "POST",
                body: payload
            });
            showMessage("detailMessage", `Parameter ${parameter.extraction_param_id} ${action}d.`, "success");
            await openReview(currentTaskId);
            await loadReviews();
            await loadLogs();
        } catch (error) {
            showMessage("detailMessage", error.message, "error");
            handleAuthError(error);
        }
    }

    async function saveIdentity() {
        if (!currentTaskId) return;
        const payload = {
            model: document.getElementById("identityModel").value.trim(),
            manufacturer: document.getElementById("identityManufacturer").value.trim(),
            category: document.getElementById("identityCategory").value,
            package: document.getElementById("identityPackage").value.trim() || null
        };
        try {
            const response = await apiRequest(
                `/api/audit/tasks/${encodeURIComponent(currentTaskId)}/identity`,
                { method: "PUT", body: payload }
            );
            renderTask(response.data?.task || response.data);
            showMessage("detailMessage", "Identity saved.", "success");
        } catch (error) {
            showMessage("detailMessage", error.message, "error");
            handleAuthError(error);
        }
    }

    function renderLogs(items) {
        const body = document.getElementById("auditLogsBody");
        body.innerHTML = "";
        if (!items.length) {
            body.innerHTML = '<tr><td colspan="6">No audit records.</td></tr>';
            return;
        }
        items.forEach(item => {
            const row = document.createElement("tr");
            [
                formatDate(item.audit_time),
                item.task_id,
                item.raw_name,
                item.auditor,
                item.action,
                item.comment || "-"
            ].forEach(value => {
                const cell = document.createElement("td");
                cell.textContent = safeText(value);
                row.appendChild(cell);
            });
            body.appendChild(row);
        });
    }

    async function loadLogs() {
        try {
            const response = await apiRequest("/api/audit/logs?page=1&page_size=50");
            renderLogs(response.data?.items || []);
            showMessage("logsMessage", "");
        } catch (error) {
            showMessage("logsMessage", "Unable to load audit log: " + error.message, "error");
            handleAuthError(error);
        }
    }

    document.getElementById("prevPage").addEventListener("click", () => {
        if (currentPage > 1) {
            currentPage--;
            loadReviews();
        }
    });

    document.getElementById("nextPage").addEventListener("click", () => {
        if (currentPage < totalPages) {
            currentPage++;
            loadReviews();
        }
    });

    document.getElementById("closeReview").addEventListener("click", () => {
        document.getElementById("reviewPanel").hidden = true;
        currentTask = null;
        currentTaskId = null;
    });

    document.getElementById("saveIdentity").addEventListener("click", saveIdentity);
    document.getElementById("refreshLogs").addEventListener("click", loadLogs);
    document.getElementById("backHome").addEventListener("click", () => {
        window.location.href = "dashboard.html";
    });

    try {
        if (!(await loadCurrentUser())) return;
        await loadCatalog();
        await loadReviews();
        await loadLogs();
        const requestedTask = new URLSearchParams(window.location.search).get("task");
        if (requestedTask) {
            await openReview(requestedTask);
        }
        if (!canAudit) {
            showMessage("listMessage", "Administrator view is read-only. Only auditors can approve or reject parameters.", "");
        }
    } catch (error) {
        showMessage("listMessage", error.message, "error");
        handleAuthError(error);
    }
});
