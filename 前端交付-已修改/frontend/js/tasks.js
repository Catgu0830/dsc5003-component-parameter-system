
// ========================================
// Task Management Module
// Component Extraction System
// ========================================

document.addEventListener("DOMContentLoaded", () => {

    // Authentication
    if (!getToken()) {
        window.location.href = "../login.html";
        return;
    }

    // DOM elements
    const tableBody = document.getElementById("tasksTableBody");
    const detailPanel = document.getElementById("taskDetailPanel");

    let currentPage = 1;
    let totalPages = 1;
    let currentTaskId = null;

    function getCachedUser() {
        try {
            return JSON.parse(localStorage.getItem("currentUser") || "{}");
        } catch {
            return {};
        }
    }

    // ------------------------------------
    // Helpers
    // ------------------------------------

    function getData(result) {
        return result?.data ?? result ?? {};
    }

    function getTaskId(task) {
        return task.task_id ?? task.id;
    }

    // Task status labels
    function getStatusLabel(status) {

        const labels = {
            pending: "Pending",
            processing: "Processing",
            success: "Successful",
            failed: "Failed",
            paused: "Paused",
            cancelled: "Cancelled"
        };

        return labels[status] || status || "-";
    }

    // Review status labels
    function getReviewLabel(status) {

        const labels = {
            empty: "No Parameters",
            pending: "Pending Review",
            partial: "Partially Reviewed",
            reviewed: "Reviewed"
        };

        return labels[status] || status || "-";
    }

    // Source type labels
    function getSourceLabel(source) {

        const labels = {
            manual: "Manual Entry",
            url: "URL Extraction",
            pdf: "PDF Upload",
            csv: "CSV Upload",
            excel: "Excel Upload",
            xlsx: "Excel Upload",
            file: "File Upload",
            upload: "File Upload"
        };

        return labels[source] || source || "-";
    }

    // Date formatting
    function formatDate(value) {

        if (!value) return "-";

        const date = new Date(value);

        if (Number.isNaN(date.getTime())) {
            return String(value);
        }

        return date.toLocaleString("en-US");
    }

    // Display messages
    function showMessage(id, message, type = "") {

        const element = document.getElementById(id);

        element.textContent = message;
        element.className = "form-message " + type;
    }

    // Set text content
    function setText(id, value) {

        document.getElementById(id).textContent =
            value ?? "-";
    }

    // Append information item
    function appendInfo(container, label, value) {

        const item = document.createElement("div");

        item.className = "task-info-item";

        const title = document.createElement("strong");

        title.textContent = label;

        const content = document.createElement("span");

        content.textContent =
            value === undefined || value === null || value === ""
                ? "-"
                : String(value);

        item.appendChild(title);
        item.appendChild(content);

        container.appendChild(item);
    }

    // Extract task list data
    function getListData(result) {

        const data = getData(result);

        return {

            items:
                data.items ||
                data.tasks ||
                data.results ||
                [],

            total: Number(data.total ?? 0),

            page: Number(data.page ?? currentPage),

            pageSize: Number(
                data.page_size ??
                document.getElementById("pageSize").value
            )
        };
    }

    // ------------------------------------
    // Load task list
    // ------------------------------------

    async function loadTasks() {

        tableBody.innerHTML = `
            <tr>
                <td colspan="7">Loading tasks...</td>
            </tr>
        `;

        showMessage("listMessage", "");

        const status =
            document.getElementById("statusFilter").value;

        const reviewStatus =
            document.getElementById("reviewFilter").value;

        const pageSize =
            document.getElementById("pageSize").value;

        const params = new URLSearchParams({
            page: currentPage,
            page_size: pageSize
        });

        if (status) {
            params.set("status", status);
        }

        if (reviewStatus) {
            params.set("review_state", reviewStatus);
        }

        try {

            const result = await apiRequest(
                `/api/tasks?${params.toString()}`
            );

            const response = getListData(result);

            renderTasks(response);

        } catch (error) {

            tableBody.innerHTML = `
                <tr>
                    <td colspan="7">Failed to load tasks.</td>
                </tr>
            `;

            showMessage(
                "listMessage",
                error.message,
                "error"
            );

            if (error.message.includes("401")) {
                clearAuth();
                window.location.href = "../login.html";
            }

        }

    }

    // ------------------------------------
    // Render task list
    // ------------------------------------

    function renderTasks(response) {

        const items = response.items;
        const total = response.total;
        const pageSize = response.pageSize;

        tableBody.innerHTML = "";

        if (!items.length) {

            tableBody.innerHTML = `
                <tr>
                    <td colspan="7">No matching tasks found.</td>
                </tr>
            `;

        }

        items.forEach(task => {

            const row = document.createElement("tr");

            const id = getTaskId(task);

            const values = [
                id,
                getSourceLabel(task.source_type),
                getStatusLabel(task.status),
                getReviewLabel(task.review_state),
                formatDate(task.created_time),
                formatDate(task.finished_time)
            ];

            values.forEach((value, index) => {

                const cell = document.createElement("td");

                if (index === 2) {

                    const badge = document.createElement("span");

                    badge.className =
                        `task-status-pill status-${task.status}`;

                    badge.textContent = value;

                    cell.appendChild(badge);

                } else {

                    cell.textContent = value;

                }

                row.appendChild(cell);

            });

            // Details button
            const actionCell = document.createElement("td");

            const detailButton = document.createElement("button");

            detailButton.className = "secondary-button";

            detailButton.textContent = "View Details";

            detailButton.addEventListener("click", () => {
                openTaskDetail(id);
            });

            actionCell.appendChild(detailButton);

            row.appendChild(actionCell);

            tableBody.appendChild(row);

        });

        totalPages = Math.max(1, Math.ceil(total / pageSize));

        currentPage = response.page;

        setText("taskCount", `${total} Records`);

        setText(
            "pageInfo",
            `Page ${currentPage} / ${totalPages}`
        );

        document.getElementById("prevPage").disabled =
            currentPage <= 1;

        document.getElementById("nextPage").disabled =
            currentPage >= totalPages;

    }

    // ------------------------------------
    // Open task details
    // ------------------------------------

    async function openTaskDetail(taskId) {

        currentTaskId = taskId;

        detailPanel.hidden = false;

        detailPanel.scrollIntoView({
            behavior: "smooth"
        });

        document.getElementById("detailComponents").innerHTML =
            "Loading...";

        document.getElementById("detailSource").innerHTML = "";

        document.getElementById("detailAudit").innerHTML = "";

        try {

            const result = await apiRequest(
                `/api/tasks/${encodeURIComponent(taskId)}`
            );

            const data = getData(result);

            const task = data.task || data;

            renderTaskDetail(task);

        } catch (error) {

            showMessage(
                "detailMessage",
                "Failed to retrieve task details: " + error.message,
                "error"
            );

            if (error.message.includes("401")) {
                clearAuth();
                window.location.href = "../login.html";
            }

        }

    }

    // ------------------------------------
    // Render task details
    // ------------------------------------

    function renderTaskDetail(task) {

        const id = getTaskId(task) ?? currentTaskId;

        const status = task.status || "unknown";

        const reviewStatus = task.review_state || task.review_status || "unknown";

        setText("detailTaskId", `Task ID: ${id}`);

        const basicInfo =
            document.getElementById("taskBasicInfo");

        basicInfo.innerHTML = "";

        appendInfo(
            basicInfo,
            "Source Type",
            getSourceLabel(task.source_type)
        );

        appendInfo(
            basicInfo,
            "Task Status",
            getStatusLabel(status)
        );

        appendInfo(
            basicInfo,
            "Review Status",
            getReviewLabel(reviewStatus)
        );

        appendInfo(
            basicInfo,
            "Created At",
            formatDate(task.created_time)
        );

        appendInfo(
            basicInfo,
            "Completed At",
            formatDate(task.finished_time)
        );

        appendInfo(
            basicInfo,
            "Last Action",
            task.action || "-"
        );

        appendInfo(
            basicInfo,
            "Action Time",
            formatDate(task.action_time)
        );

        // Error
        const errorBox =
            document.getElementById("detailError");

        errorBox.hidden = !task.error_msg;

        errorBox.textContent =
            task.error_msg || "";

        // Warnings
        renderWarnings(task.result?.warnings || task.warnings || []);

        // Components
        const components =
            task.components ||
            task.result?.components ||
            [];

        renderComponents(components);

        // Source
        renderSource(task);

        // Audit
        renderAudit(task);

        // Available actions
        document.getElementById("detailRetry").hidden =
            status !== "failed";

        document.getElementById("downloadSource").hidden =
            !hasSourceFile(task);

        const user = getCachedUser();
        const canDelete = user.role === "admin" ||
            (user.role === "user" && Number(user.user_id) === Number(task.user_id));
        document.getElementById("detailDelete").hidden =
            !canDelete || status === "processing";

        showMessage("detailMessage", "");

    }

    // ------------------------------------
    // Render warnings
    // ------------------------------------

    function renderWarnings(warnings) {

        const container =
            document.getElementById("detailWarnings");

        container.innerHTML = "";

        if (!Array.isArray(warnings) || !warnings.length) {
            return;
        }

        const heading = document.createElement("h3");

        heading.textContent = "Extraction Warnings";

        container.appendChild(heading);

        warnings.forEach(warning => {

            const p = document.createElement("p");

            p.className = "task-warning-item";

            p.textContent =
                typeof warning === "string"
                    ? warning
                    : JSON.stringify(warning);

            container.appendChild(p);

        });

    }

    // ------------------------------------
    // Render extracted components
    // ------------------------------------

    function renderComponents(components) {

        const container =
            document.getElementById("detailComponents");

        container.innerHTML = "";

        if (!Array.isArray(components) || !components.length) {

            container.textContent = "No extraction results available.";

            return;

        }

        components.forEach(component => {

            const card = document.createElement("div");

            card.className = "task-component-card";

            const heading = document.createElement("h4");

            heading.textContent =
                component.model || "Unidentified Model";

            card.appendChild(heading);

            const info = document.createElement("p");

            info.textContent =
                `Manufacturer: ${component.manufacturer || "-"} | Category: ${component.category || "-"}`;

            card.appendChild(info);

            const parameters = component.parameters || [];

            if (parameters.length) {

                const table = document.createElement("table");

                table.className = "task-table";

                const thead = document.createElement("thead");

                thead.innerHTML = `
                    <tr>
                        <th>Parameter Name</th>
                        <th>Parameter Value</th>
                        <th>Unit</th>
                        <th>Confidence</th>
                    </tr>
                `;

                table.appendChild(thead);

                const tbody = document.createElement("tbody");

                parameters.forEach(parameter => {

                    const row = document.createElement("tr");

                    const value =
                        parameter.value ??
                        parameter.value_num ??
                        parameter.value_text ??
                        "-";

                    [
                        parameter.name,
                        value,
                        parameter.unit || "-",
                        parameter.confidence ?? "-"
                    ].forEach(item => {

                        const cell = document.createElement("td");

                        cell.textContent = item;

                        row.appendChild(cell);

                    });

                    tbody.appendChild(row);

                });

                table.appendChild(tbody);

                card.appendChild(table);

            }

            container.appendChild(card);

        });

    }

    // ------------------------------------
    // Render source information
    // ------------------------------------

    function renderSource(task) {

        const container =
            document.getElementById("detailSource");

        container.innerHTML = "";

        const source = task.source || {};

        appendInfo(
            container,
            "Source Type",
            getSourceLabel(task.source_type)
        );

        appendInfo(
            container,
            "Source Location",
            task.source_location ||
            task.url ||
            source.url ||
            "-"
        );

        appendInfo(
            container,
            "Original Filename",
            task.original_filename ||
            source.filename ||
            source.original_filename ||
            "-"
        );

    }

    // ------------------------------------
    // Render audit history
    // ------------------------------------

    function renderAudit(task) {

        const container =
            document.getElementById("detailAudit");

        container.innerHTML = "";

        const history =
            task.audit_history ||
            task.audit_logs ||
            task.audit ||
            [];

        if (!Array.isArray(history) || !history.length) {

            container.textContent = "No audit records available.";

            return;

        }

        history.forEach(item => {

            const card = document.createElement("div");

            card.className = "task-history-item";

            appendInfo(
                card,
                "Audit Action",
                item.action || "-"
            );

            appendInfo(
                card,
                "Review Comment",
                item.comment || "-"
            );

            appendInfo(
                card,
                "Review Time",
                formatDate(item.audit_time)
            );

            container.appendChild(card);

        });

    }

    // ------------------------------------
    // Check source file availability
    // ------------------------------------

    function hasSourceFile(task) {

        const source = task.source || {};

        const sourceType = String(
            task.source_type || ""
        ).toLowerCase();

        return Boolean(
            task.original_filename ||
            task.source_file ||
            source.filename ||
            source.original_filename ||
            ["pdf", "csv", "xlsx", "file", "upload"]
                .includes(sourceType)
        );

    }

    // ------------------------------------
    // Task actions
    // ------------------------------------

    async function performTaskAction(endpoint, message) {

        if (currentTaskId === null) return;

        try {

            await apiRequest(
                `/api/tasks/${encodeURIComponent(currentTaskId)}/${endpoint}`,
                {
                    method: "POST"
                }
            );

            showMessage(
                "detailMessage",
                message,
                "success"
            );

            await openTaskDetail(currentTaskId);

            await loadTasks();

        } catch (error) {

            showMessage(
                "detailMessage",
                error.message,
                "error"
            );

        }

    }

    // ------------------------------------
    // Retry
    // ------------------------------------

    document.getElementById("detailRetry")
        .addEventListener("click", async () => {

            if (!confirm("Are you sure you want to retry this failed task?")) {
                return;
            }

            await performTaskAction(
                "retry",
                "Task retry has been submitted successfully."
            );

        });

    // ------------------------------------
    // Delete task
    // ------------------------------------

    document.getElementById("detailDelete")
        .addEventListener("click", async () => {

            if (currentTaskId === null) return;
            if (!confirm("Delete this extraction task? This cannot be undone.")) {
                return;
            }

            try {

                await apiRequest(`/api/tasks/${encodeURIComponent(currentTaskId)}`, {
                    method: "DELETE",
                    body: { confirm: true }
                });

                showMessage("listMessage", "Task deleted.", "success");
                detailPanel.hidden = true;
                currentTaskId = null;
                await loadTasks();

            } catch (error) {

                showMessage("detailMessage", error.message, "error");

            }

        });

    // ------------------------------------
    // Download source file
    // ------------------------------------

    async function downloadSource() {

        if (currentTaskId === null) return;

        try {

            const token = getToken();

            const baseUrl =
                API_BASE_URL.replace(/\/$/, "");

            const response = await fetch(
                `${baseUrl}/api/tasks/${encodeURIComponent(currentTaskId)}/source`,
                {
                    method: "GET",
                    headers: {
                        Authorization: `Bearer ${token}`
                    }
                }
            );

            if (!response.ok) {

                let message =
                    `Download failed: HTTP ${response.status}`;

                try {

                    const error = await response.json();

                    message = error.message || message;

                } catch {
                    // Keep default error message
                }

                throw new Error(message);

            }

            const blob = await response.blob();

            const disposition =
                response.headers.get("Content-Disposition") || "";

            // Support both filename and filename*
            const match = disposition.match(
                /filename\*?=(?:UTF-8''|")?([^";]+)/i
            );

            let filename =
                match
                    ? decodeURIComponent(match[1].replace(/"$/, ""))
                    : `task-${currentTaskId}-source`;

            const url = URL.createObjectURL(blob);

            const link = document.createElement("a");

            link.href = url;
            link.download = filename;

            document.body.appendChild(link);

            link.click();

            link.remove();

            URL.revokeObjectURL(url);

        } catch (error) {

            showMessage(
                "detailMessage",
                error.message,
                "error"
            );

        }

    }

    document.getElementById("downloadSource")
        .addEventListener("click", downloadSource);

    // ------------------------------------
    // Pagination
    // ------------------------------------

    document.getElementById("prevPage")
        .addEventListener("click", () => {

            if (currentPage > 1) {

                currentPage--;

                loadTasks();

            }

        });

    document.getElementById("nextPage")
        .addEventListener("click", () => {

            if (currentPage < totalPages) {

                currentPage++;

                loadTasks();

            }

        });

    // ------------------------------------
    // Filters
    // ------------------------------------

    document.getElementById("applyFilters")
        .addEventListener("click", () => {

            currentPage = 1;

            loadTasks();

        });

    document.getElementById("resetFilters")
        .addEventListener("click", () => {

            document.getElementById("statusFilter").value = "";

            document.getElementById("reviewFilter").value = "";

            document.getElementById("pageSize").value = "20";

            currentPage = 1;

            loadTasks();

        });

    document.getElementById("pageSize")
        .addEventListener("change", () => {

            currentPage = 1;

            loadTasks();

        });

    // ------------------------------------
    // Refresh
    // ------------------------------------

    document.getElementById("refreshTasks")
        .addEventListener("click", loadTasks);

    document.getElementById("refreshDetail")
        .addEventListener("click", () => {

            if (currentTaskId !== null) {
                openTaskDetail(currentTaskId);
            }

        });

    // ------------------------------------
    // Close detail
    // ------------------------------------

    document.getElementById("closeDetail")
        .addEventListener("click", () => {

            detailPanel.hidden = true;

            currentTaskId = null;

        });

    // ------------------------------------
    // Initial loading
    // ------------------------------------

    loadTasks();

});
