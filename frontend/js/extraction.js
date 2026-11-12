
// ========================================
// Component Extraction Module
// Uses Member C Flask API
// ========================================

document.addEventListener("DOMContentLoaded", () => {

    // Check authentication
    if (!getToken()) {
        window.location.href = "../login.html";
        return;
    }

    // Elements
    const fileForm = document.getElementById("fileUploadForm");
    const urlForm = document.getElementById("urlForm");
    const manualForm = document.getElementById("manualForm");
    const batchForm = document.getElementById("batchForm");

    const parameterRows = document.getElementById("parameterRows");

    const taskPanel = document.getElementById("taskPanel");

    let currentTaskId = null;
    let pollingVersion = 0;

    // Load categories from the 11-table backend.
    async function loadCategories() {

        try {

            const result = await apiRequest("/api/categories");

            const categories = result.data?.items || [];

            const select = document.getElementById("manualCategory");

            if (!select) return;

            select.innerHTML = '<option value="">Select a Category</option>';

            categories.forEach(category => {

                const option = document.createElement("option");

                option.value = category.name;
                option.textContent = category.name;

                select.appendChild(option);

            });

        } catch (error) {

            console.error("Category load error:", error);

        }

    }

    loadCategories();

    // ------------------------------------
    // Tab switching
    // ------------------------------------

    const tabButtons = document.querySelectorAll(".tab-button");

    tabButtons.forEach(button => {

        button.addEventListener("click", () => {

            const target = button.dataset.tab;

            document.querySelectorAll(".extraction-panel")
                .forEach(panel => {
                    panel.hidden = panel.id !== target;
                });

            tabButtons.forEach(item => {
                item.classList.toggle("active", item === button);
            });

        });

    });

    // ------------------------------------
    // Message helper
    // ------------------------------------

    function showMessage(id, message, type = "") {

        const element = document.getElementById(id);

        element.textContent = message;
        element.className = "form-message " + type;

    }

    // ------------------------------------
    // Button loading
    // ------------------------------------

    async function runWithLoading(button, text, callback) {

        const originalText = button.textContent;

        button.disabled = true;
        button.textContent = text;

        try {

            await callback();

        } finally {

            button.disabled = false;
            button.textContent = originalText;

        }

    }

    // ------------------------------------
    // Get task ID from API response
    // ------------------------------------

    function getTaskId(result) {

        const data = result.data || {};

        return (
            data.task_id ??
            data.id ??
            data.task?.task_id ??
            data.task?.id ??
            data.tasks?.[0]?.task_id ??
            data.tasks?.[0]?.id
        );

    }

    // ------------------------------------
    // Submit JSON task
    // ------------------------------------

    async function submitJsonTask(payload) {

        const result = await apiRequest("/api/tasks", {
            method: "POST",
            body: payload
        });

        await acceptTask(result);

    }

    // ------------------------------------
    // Accept created task
    // ------------------------------------

    async function acceptTask(result) {

        const taskId = getTaskId(result);

        if (taskId === undefined || taskId === null) {

            throw new Error(
                "The server responded without a task_id. Please check the API response."
            );

        }

        currentTaskId = taskId;

        taskPanel.hidden = false;

        document.getElementById("taskId").textContent = taskId;

        document.getElementById("taskStatus").textContent = "pending";

        document.getElementById("reviewStatus").textContent = "Pending Review";

        document.getElementById("taskError").textContent = "None";

        document.getElementById("extractedResults").innerHTML = "";

        document.getElementById("taskWarnings").innerHTML = "";

        document.getElementById("retryTask").hidden = true;

        const batchCount =
            Number(result.data?.count ?? result.data?.tasks?.length ?? 1);

        document.getElementById("pollMessage").textContent =
            batchCount > 1
                ? `${batchCount} extraction tasks created. Showing task ${taskId}; open Task Management to see all rows.`
                : "Task created successfully. Waiting for background processing...";

        taskPanel.scrollIntoView({
            behavior: "smooth"
        });

        await pollTask(taskId);

    }

    // ------------------------------------
    // Task status polling
    // Poll every 1 second
    // ------------------------------------

    function delay(ms) {

        return new Promise(resolve => setTimeout(resolve, ms));

    }

    async function pollTask(taskId) {

        const thisVersion = ++pollingVersion;

        const terminalStatuses = [
            "success",
            "failed",
            "paused",
            "cancelled"
        ];

        document.getElementById("refreshTask").disabled = false;

        for (let i = 0; i < 300; i++) {

            if (thisVersion !== pollingVersion) {
                return;
            }

            try {

                const result = await apiRequest(
                    `/api/tasks/${taskId}`
                );

                const task = result.data?.task || result.data;

                displayTask(task, taskId);

                if (terminalStatuses.includes(task.status)) {

                    document.getElementById("pollMessage").textContent =
                        "Task processing has finished.";

                    return;

                }

                document.getElementById("pollMessage").textContent =
                    "Background processing in progress. Please wait...";

            } catch (error) {

                document.getElementById("pollMessage").textContent =
                    "Failed to retrieve task status: " + error.message;

                if (error.message.includes("401")) {

                    clearAuth();

                    window.location.href = "../login.html";

                    return;

                }

                return;

            }

            await delay(1000);

        }

        if (thisVersion === pollingVersion) {

            document.getElementById("pollMessage").textContent =
                "Processing is taking longer than expected. Click Refresh Task Status to check again.";

        }

    }

    // ------------------------------------
    // Display task information
    // ------------------------------------

    function displayTask(task, taskId) {

        const status = task.status || "unknown";

        const reviewStatus = task.review_state || task.review_status || "unknown";

        document.getElementById("taskId").textContent = taskId;

        document.getElementById("taskStatus").textContent = status;

        const reviewLabels = {
            empty: "No extracted parameters",
            pending: "Pending Review",
            partial: "Partially Reviewed",
            reviewed: "Reviewed"
        };

        document.getElementById("reviewStatus").textContent =
            reviewLabels[reviewStatus] || reviewStatus;

        document.getElementById("taskError").textContent =
            task.error_msg || "None";

        const badge = document.getElementById("taskStatusBadge");

        const statusLabels = {
            pending: "Pending",
            processing: "Processing",
            success: "Extraction Successful",
            failed: "Extraction Failed",
            paused: "Paused",
            cancelled: "Cancelled"
        };

        badge.textContent =
            statusLabels[status] || status;

        badge.className = "status-badge status-" + status;

        // Warnings
        const warningBox = document.getElementById("taskWarnings");

        warningBox.innerHTML = "";

        const warnings =
            task.result?.warnings ||
            task.warnings ||
            [];

        warnings.forEach(warning => {

            const p = document.createElement("p");

            p.textContent =
                typeof warning === "string"
                    ? warning
                    : JSON.stringify(warning);

            warningBox.appendChild(p);

        });

        // Extracted components
        const resultBox = document.getElementById("extractedResults");

        resultBox.innerHTML = "";

        let components =
            task.components ||
            task.result?.components ||
            [];

        if (!Array.isArray(components)) {
            components = [];
        }

        if (status === "success") {

            const heading = document.createElement("h3");

            heading.textContent = "Extraction Results";

            resultBox.appendChild(heading);

            if (components.length === 0) {

                const p = document.createElement("p");

                p.textContent =
                    "The task has completed, but no component array is available in the current response. Please check the task details or refresh the page.";

                resultBox.appendChild(p);

            }

            components.forEach(component => {

                renderExtractedComponent(resultBox, component);

            });

            if (reviewStatus !== "reviewed") {

                const notice = document.createElement("p");

                notice.className = "review-notice";

                notice.textContent =
                    "Extraction successful! These results are still pending review. They will only be officially added to the component database after approval.";

                resultBox.appendChild(notice);

            }

        }

        // Retry only for failed tasks
        document.getElementById("retryTask").hidden =
            status !== "failed";

    }

    // ------------------------------------
    // Render extracted component
    // ------------------------------------

    function renderExtractedComponent(container, component) {

        const card = document.createElement("div");

        card.className = "extracted-component";

        const title = document.createElement("h4");

        title.textContent =
            component.model || "Unidentified Model";

        card.appendChild(title);

        const basic = document.createElement("p");

        basic.textContent =
            `Manufacturer: ${component.manufacturer || "-"} | Category: ${component.category || "-"}`;

        card.appendChild(basic);

        const parameters =
            component.parameters || [];

        if (parameters.length > 0) {

            const table = document.createElement("table");

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

                const values = [
                    parameter.name,
                    value,
                    parameter.unit || "-",
                    parameter.confidence ?? "-"
                ];

                values.forEach(value => {

                    const cell = document.createElement("td");

                    cell.textContent = value;

                    row.appendChild(cell);

                });

                tbody.appendChild(row);

            });

            table.appendChild(tbody);

            card.appendChild(table);

        }

        container.appendChild(card);

    }

    // ------------------------------------
    // File upload
    // ------------------------------------

    fileForm.addEventListener("submit", async event => {

        event.preventDefault();

        const file = document.getElementById("uploadFile").files[0];

        if (!file) {

            showMessage("fileMessage", "Please select a file first.", "error");

            return;

        }

        const allowedExtensions = [
            ".pdf",
            ".csv",
            ".xlsx"
        ];

        const extension = file.name
            .substring(file.name.lastIndexOf("."))
            .toLowerCase();

        if (!allowedExtensions.includes(extension)) {

            showMessage(
                "fileMessage",
                "Only PDF, CSV and XLSX files are supported.",
                "error"
            );

            return;

        }

        if (file.size > 20 * 1024 * 1024) {

            showMessage(
                "fileMessage",
                "File size cannot exceed 20 MB.",
                "error"
            );

            return;

        }

        const button = fileForm.querySelector("button[type=submit]");

        await runWithLoading(button, "Uploading...", async () => {

            showMessage("fileMessage", "Uploading file and creating extraction task...");

            const formData = new FormData();

            formData.append("file", file);

            const result = await apiRequest(
                "/api/tasks/upload",
                {
                    method: "POST",
                    body: formData
                }
            );

            showMessage(
                "fileMessage",
                "File uploaded successfully. Extraction task(s) created.",
                "success"
            );

            await acceptTask(result);

        }).catch(error => {

            showMessage(
                "fileMessage",
                error.message,
                "error"
            );

        });

    });

    // ------------------------------------
    // URL extraction
    // ------------------------------------

    urlForm.addEventListener("submit", async event => {

        event.preventDefault();

        const url = document.getElementById("sourceUrl").value.trim();

        let parsedUrl;

        try {

            parsedUrl = new URL(url);

        } catch {

            showMessage(
                "urlMessage",
                "Please enter a valid URL.",
                "error"
            );

            return;

        }

        if (!["http:", "https:"].includes(parsedUrl.protocol)) {

            showMessage(
                "urlMessage",
                "Only HTTP and HTTPS URLs are supported.",
                "error"
            );

            return;

        }

        const button = urlForm.querySelector("button[type=submit]");

        await runWithLoading(button, "Submitting...", async () => {

            showMessage("urlMessage", "Creating URL extraction task...");

            await submitJsonTask({
                source_type: "url",
                url: url
            });

            showMessage(
                "urlMessage",
                "URL extraction task created successfully.",
                "success"
            );

        }).catch(error => {

            showMessage(
                "urlMessage",
                error.message,
                "error"
            );

        });

    });

    // ------------------------------------
    // Manual parameter rows
    // ------------------------------------

    document.getElementById("addParameter")
        .addEventListener("click", () => {

            const row = document.createElement("div");

            row.className = "parameter-row";

            row.innerHTML = `
                <input
                    class="parameter-name"
                    placeholder="Parameter name, e.g. voltage"
                >

                <input
                    class="parameter-value"
                    placeholder="Parameter value, e.g. 3.3"
                >

                <input
                    class="parameter-unit"
                    placeholder="Unit, e.g. V"
                >

                <button
                    type="button"
                    class="remove-parameter"
                >
                    Remove
                </button>
            `;

            parameterRows.appendChild(row);

        });

    parameterRows.addEventListener("click", event => {

        if (event.target.classList.contains("remove-parameter")) {

            const rows =
                parameterRows.querySelectorAll(".parameter-row");

            if (rows.length > 1) {

                event.target.closest(".parameter-row").remove();

            } else {

                alert("At least one parameter row must remain.");

            }

        }

    });

    // ------------------------------------
    // Manual task creation
    // ------------------------------------

    manualForm.addEventListener("submit", async event => {

        event.preventDefault();

        const model =
            document.getElementById("manualModel").value.trim();

        const manufacturer =
            document.getElementById("manualManufacturer").value.trim();

        const category =
            document.getElementById("manualCategory").value;

        const packageValue =
            document.getElementById("manualPackage")?.value.trim() || "";

        const parameters = [];

        const rows =
            parameterRows.querySelectorAll(".parameter-row");

        for (const row of rows) {

            const name =
                row.querySelector(".parameter-name").value.trim();

            const value =
                row.querySelector(".parameter-value").value.trim();

            const unit =
                row.querySelector(".parameter-unit").value.trim();

            if (!name && !value && !unit) {
                continue;
            }

            if (!name || !value) {

                showMessage(
                    "manualMessage",
                    "Every parameter must have both a name and a value.",
                    "error"
                );

                return;

            }

            const parameter = {
                name: name,
                value: value
            };

            if (unit) {
                parameter.unit = unit;
            }

            parameters.push(parameter);

        }

        if (parameters.length === 0) {

            showMessage(
                "manualMessage",
                "Please enter at least one component parameter.",
                "error"
            );

            return;

        }

        const payload = {
            source_type: "manual",
            component: {
                model: model,
                manufacturer: manufacturer,
                category: category,
                package: packageValue,
                parameters: parameters
            }
        };

        const button =
            manualForm.querySelector("button[type=submit]");

        await runWithLoading(button, "Creating Task...", async () => {

            showMessage(
                "manualMessage",
                "Submitting manually entered component information..."
            );

            await submitJsonTask(payload);

            showMessage(
                "manualMessage",
                "Manual entry task created successfully.",
                "success"
            );

        }).catch(error => {

            showMessage(
                "manualMessage",
                error.message,
                "error"
            );

        });

    });

    // ------------------------------------
    // Batch manual entry
    // ------------------------------------

    batchForm.addEventListener("submit", async event => {

        event.preventDefault();

        let payload;

        try {

            payload = JSON.parse(
                document.getElementById("batchJson").value
            );

        } catch {

            showMessage(
                "batchMessage",
                "Invalid JSON. Paste an array or an object with a components array.",
                "error"
            );

            return;

        }

        const components = Array.isArray(payload)
            ? payload
            : payload?.components;

        if (!Array.isArray(components) || components.length === 0) {

            showMessage(
                "batchMessage",
                "The JSON must contain a non-empty components array.",
                "error"
            );

            return;

        }

        const button =
            batchForm.querySelector("button[type=submit]");

        await runWithLoading(button, "Creating Tasks...", async () => {

            const result = await apiRequest("/api/tasks/batch", {
                method: "POST",
                body: { components }
            });

            const count = result.data?.count ?? components.length;

            showMessage(
                "batchMessage",
                `${count} batch task(s) created successfully.`,
                "success"
            );

            await acceptTask(result);

        }).catch(error => {

            showMessage(
                "batchMessage",
                error.message,
                "error"
            );

        });

    });

    // ------------------------------------
    // Refresh task
    // ------------------------------------

    document.getElementById("refreshTask")
        .addEventListener("click", async () => {

            if (currentTaskId === null) {
                return;
            }

            await pollTask(currentTaskId);

        });

    // ------------------------------------
    // Retry failed task
    // ------------------------------------

    document.getElementById("retryTask")
        .addEventListener("click", async () => {

            if (currentTaskId === null) {
                return;
            }

            const confirmed = confirm(
                "Are you sure you want to retry this failed extraction task?"
            );

            if (!confirmed) {
                return;
            }

            const button =
                document.getElementById("retryTask");

            await runWithLoading(button, "Retrying...", async () => {

                await apiRequest(
                    `/api/tasks/${currentTaskId}/retry`,
                    {
                        method: "POST"
                    }
                );

                document.getElementById("pollMessage").textContent =
                    "Task resubmitted successfully. Waiting for processing...";

                await pollTask(currentTaskId);

            }).catch(error => {

                alert("Task retry failed: " + error.message);

            });

        });

    // ------------------------------------
    // Back to dashboard
    // ------------------------------------

    document.getElementById("backHome")
        .addEventListener("click", () => {

            window.location.href = "dashboard.html";

        });

});
