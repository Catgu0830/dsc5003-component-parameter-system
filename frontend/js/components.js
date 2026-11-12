
// ========================================
// Component Search Module
// ========================================

document.addEventListener("DOMContentLoaded", () => {

    // Check authentication status
    if (!getToken()) {
        window.location.href = "../login.html";
        return;
    }

    const searchForm = document.getElementById("searchForm");

    const componentTable =
        document.getElementById("componentTable");

    const resultCount =
        document.getElementById("resultCount");

    const searchMessage =
        document.getElementById("searchMessage");

    const pageInfo =
        document.getElementById("pageInfo");

    const previousPage =
        document.getElementById("previousPage");

    const nextPage =
        document.getElementById("nextPage");

    const detailPanel =
        document.getElementById("detailPanel");

    const detailContent =
        document.getElementById("detailContent");

    const pageSize = 10;

    let currentPage = 1;
    let totalPages = 1;
    const FILTER_STORAGE_KEY = "componentSavedFilters";

    function readSavedFilters() {
        try {
            const value = JSON.parse(localStorage.getItem(FILTER_STORAGE_KEY) || "{}");
            return value && typeof value === "object" ? value : {};
        } catch {
            return {};
        }
    }

    function writeSavedFilters(filters) {
        localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(filters));
    }

    function renderSavedFilters() {
        const filters = readSavedFilters();
        const select = document.getElementById("savedFilterSelect");
        const current = select.value;
        select.innerHTML = '<option value="">Saved filters...</option>';
        Object.keys(filters).sort().forEach(name => {
            const option = document.createElement("option");
            option.value = name;
            option.textContent = name;
            select.appendChild(option);
        });
        if (current && filters[current]) {
            select.value = current;
        }
    }

    function collectFilterState() {
        return {
            keyword: document.getElementById("keyword").value.trim(),
            category: document.getElementById("category").value,
            manufacturer: document.getElementById("manufacturer").value.trim(),
            package: document.getElementById("package").value.trim(),
            voltageMin: document.getElementById("voltageMin").value,
            voltageMax: document.getElementById("voltageMax").value
        };
    }

    function saveCurrentFilter() {
        const name = prompt("Name for this filter:");
        if (!name || !name.trim()) return;
        const filters = readSavedFilters();
        filters[name.trim()] = collectFilterState();
        writeSavedFilters(filters);
        renderSavedFilters();
        document.getElementById("savedFilterSelect").value = name.trim();
        searchMessage.textContent = "Filter saved locally.";
    }

    function loadSelectedFilter() {
        const name = document.getElementById("savedFilterSelect").value;
        const filters = readSavedFilters();
        const state = filters[name];
        if (!state) {
            searchMessage.textContent = "Select a saved filter first.";
            return;
        }
        document.getElementById("keyword").value = state.keyword || "";
        document.getElementById("category").value = state.category || "";
        document.getElementById("manufacturer").value = state.manufacturer || "";
        document.getElementById("package").value = state.package || "";
        document.getElementById("voltageMin").value = state.voltageMin || "";
        document.getElementById("voltageMax").value = state.voltageMax || "";
        currentPage = 1;
        loadComponents();
    }

    function deleteSelectedFilter() {
        const name = document.getElementById("savedFilterSelect").value;
        if (!name) return;
        if (!confirm(`Delete saved filter "${name}"?`)) return;
        const filters = readSavedFilters();
        delete filters[name];
        writeSavedFilters(filters);
        renderSavedFilters();
        searchMessage.textContent = "Filter deleted.";
    }

    // Load categories from the 11-table backend.
    async function loadCategories() {

        try {

            const result = await apiRequest("/api/categories");

            const categories = result.data?.items || [];

            const select = document.getElementById("category");

            select.innerHTML = '<option value="">All Categories</option>';

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

    // Load components
    async function loadComponents() {

        searchMessage.textContent = "Searching...";
        componentTable.innerHTML = "";

        const params = new URLSearchParams();

        params.set("page", currentPage);
        params.set("page_size", pageSize);
        params.set("sort", "model");
        params.set("order", "asc");

        const keyword =
            document.getElementById("keyword").value.trim();

        const category =
            document.getElementById("category").value;

        const manufacturer =
            document.getElementById("manufacturer").value.trim();

        const packageValue =
            document.getElementById("package").value.trim();

        const voltageMin =
            document.getElementById("voltageMin").value;

        const voltageMax =
            document.getElementById("voltageMax").value;

        // Apply basic filters
        if (keyword) {
            params.set("keyword", keyword);
        }

        if (category) {
            params.set("category", category);
        }

        if (manufacturer) {
            params.set("manufacturer", manufacturer);
        }

        if (packageValue) {
            params.set("package", packageValue);
        }

        // Apply voltage range filter
        if (voltageMin !== "" || voltageMax !== "") {

            const min = voltageMin === ""
                ? undefined
                : Number(voltageMin);

            const max = voltageMax === ""
                ? undefined
                : Number(voltageMax);

            if (
                (min !== undefined && !Number.isFinite(min)) ||
                (max !== undefined && !Number.isFinite(max)) ||
                (min !== undefined && min < 0) ||
                (max !== undefined && max < 0) ||
                (min !== undefined && max !== undefined && min > max)
            ) {

                searchMessage.textContent =
                    "Please enter a valid voltage range. " +
                    "The minimum value cannot exceed the maximum value.";

                return;
            }

            const filter = {
                name: "voltage",
                unit: "V"
            };

            if (min !== undefined) {
                filter.min = min;
            }

            if (max !== undefined) {
                filter.max = max;
            }

            params.set(
                "filters",
                JSON.stringify([filter])
            );

        }

        try {

            const result = await apiRequest(
                `/api/components?${params.toString()}`
            );

            const data = result.data;

            const components = data.items || [];

            const total = data.total || 0;

            totalPages = Math.max(
                1,
                Math.ceil(total / pageSize)
            );

            resultCount.textContent =
                `${total} components found`;

            searchMessage.textContent =
                components.length > 0
                    ? "Search completed successfully."
                    : "No components match your search criteria.";

            renderComponents(components);

            updatePagination();

        } catch (error) {

            console.error(error);

            searchMessage.textContent =
                "Search failed: " + error.message;

            if (error.message.includes("401")) {
                clearAuth();
                window.location.href = "../login.html";
            }

        }

    }

    // Render search results
    function renderComponents(components) {

        componentTable.innerHTML = "";

        if (components.length === 0) {

            const row = document.createElement("tr");

            const cell = document.createElement("td");

            cell.colSpan = 5;
            cell.textContent = "No matching components found.";

            row.appendChild(cell);
            componentTable.appendChild(row);

            return;
        }

        components.forEach(component => {

            const row = document.createElement("tr");

            const values = [
                component.model,
                component.manufacturer,
                component.category,
                (component.parameters || []).length
            ];

            values.forEach(value => {

                const cell = document.createElement("td");

                cell.textContent = value ?? "-";

                row.appendChild(cell);

            });

            // Create details button
            const actionCell = document.createElement("td");

            const button = document.createElement("button");

            button.textContent = "View Details";
            button.className = "table-action";

            button.addEventListener("click", () => {
                showDetails(component.component_id);
            });

            actionCell.appendChild(button);

            row.appendChild(actionCell);

            componentTable.appendChild(row);

        });

    }

    // Display component details
    async function showDetails(id) {

        try {

            const result = await apiRequest(
                `/api/components/${id}`
            );

            const component =
                result.data.component || result.data;

            const parameters =
                component.parameters || result.data.parameters || [];

            detailContent.innerHTML = "";

            const title = document.createElement("h3");

            title.textContent =
                component.model || "Component Details";

            detailContent.appendChild(title);

            const basicInfo = [
                ["Model", component.model],
                ["Manufacturer", component.manufacturer],
                ["Category", component.category],
                ["Package", component.package],
                ["Component ID", component.component_id],
                ["Description", component.description]
            ];

            basicInfo.forEach(([label, value]) => {

                const p = document.createElement("p");

                p.textContent =
                    `${label}: ${value ?? "-"}`;

                detailContent.appendChild(p);

            });

            const heading = document.createElement("h3");

            heading.textContent = "Component Parameters";

            detailContent.appendChild(heading);

            if (parameters.length === 0) {

                const p = document.createElement("p");

                p.textContent = "No parameters available.";

                detailContent.appendChild(p);

            }

            parameters.forEach(parameter => {

                const p = document.createElement("p");

                const value =
                    parameter.value ??
                    parameter.value_num ??
                    parameter.value_text ??
                    "-";

                p.textContent =
                    `${parameter.name}: ${value}` +
                    `${parameter.unit || ""}`;

                detailContent.appendChild(p);

            });

            renderExportActions(component.component_id);
            renderHistory(component);
            await renderSimilar(component.component_id);

            detailPanel.hidden = false;

            detailPanel.scrollIntoView({
                behavior: "smooth"
            });

        } catch (error) {

            alert("Failed to retrieve component details: " + error.message);

        }

    }

    function renderExportActions(componentId) {
        const heading = document.createElement("h3");
        heading.textContent = "Export Component Detail";
        detailContent.appendChild(heading);
        const actions = document.createElement("div");
        actions.className = "filter-actions";
        ["csv", "xlsx", "json"].forEach(format => {
            const button = document.createElement("button");
            button.className = "secondary-button";
            button.textContent = format.toUpperCase();
            button.addEventListener("click", () => downloadComponentExport(componentId, format));
            actions.appendChild(button);
        });
        detailContent.appendChild(actions);
    }

    async function downloadComponentExport(componentId, format) {
        try {
            const response = await fetch(
                `${API_BASE_URL}/api/export/components/${componentId}?format=${format}`,
                { headers: { Authorization: `Bearer ${getToken()}` } }
            );
            if (!response.ok) {
                let message = `Export failed: HTTP ${response.status}`;
                try {
                    const error = await response.json();
                    message = error.message || message;
                } catch {
                    // Keep HTTP message.
                }
                throw new Error(message);
            }
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = `component-${componentId}.${format}`;
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
        } catch (error) {
            alert(error.message);
        }
    }

    function renderHistory(component) {
        const history = component.history || [];
        if (!Array.isArray(history) || !history.length) return;

        const heading = document.createElement("h3");
        heading.textContent = "Extraction History";
        detailContent.appendChild(heading);

        const wrapper = document.createElement("div");
        wrapper.className = "table-wrapper";
        const table = document.createElement("table");
        const thead = document.createElement("thead");
        thead.innerHTML = `
            <tr>
                <th>Task</th>
                <th>Source</th>
                <th>Status</th>
                <th>Review State</th>
                <th>Created</th>
            </tr>
        `;
        table.appendChild(thead);
        const tbody = document.createElement("tbody");
        history.forEach(task => {
            const row = document.createElement("tr");
            [
                task.task_id,
                task.source_type,
                task.status,
                task.review_state,
                formatDate(task.created_time)
            ].forEach(value => {
                const cell = document.createElement("td");
                cell.textContent = value ?? "-";
                row.appendChild(cell);
            });
            tbody.appendChild(row);
        });
        table.appendChild(tbody);
        wrapper.appendChild(table);
        detailContent.appendChild(wrapper);

        const button = document.createElement("button");
        button.className = "primary-button";
        button.textContent = "Compare Latest Two";
        button.disabled = history.length < 2;
        detailContent.appendChild(button);

        const diff = document.createElement("div");
        detailContent.appendChild(diff);
        button.addEventListener("click", async () => {
            diff.textContent = "Loading version comparison...";
            try {
                const result = await apiRequest(`/api/components/${component.component_id}/versions`);
                const data = result.data;
                diff.innerHTML = "";
                const info = document.createElement("p");
                info.textContent = `${data.changed_count} changed parameter(s) from task ${data.from_task.task_id} to task ${data.to_task.task_id}.`;
                diff.appendChild(info);
                const diffWrapper = document.createElement("div");
                diffWrapper.className = "table-wrapper";
                const diffTable = document.createElement("table");
                diffTable.innerHTML = `
                    <thead><tr><th>Parameter</th><th>From</th><th>To</th><th>Changed</th></tr></thead>
                    <tbody></tbody>
                `;
                const body = diffTable.querySelector("tbody");
                data.rows.forEach(item => {
                    const row = document.createElement("tr");
                    const from = item.from ? `${item.from.raw_value} ${item.from.unit || ""}`.trim() : "-";
                    const to = item.to ? `${item.to.raw_value} ${item.to.unit || ""}`.trim() : "-";
                    [item.name, from, to, item.changed ? "Yes" : "No"].forEach(value => {
                        const cell = document.createElement("td");
                        cell.textContent = value;
                        row.appendChild(cell);
                    });
                    body.appendChild(row);
                });
                diffWrapper.appendChild(diffTable);
                diff.appendChild(diffWrapper);
            } catch (error) {
                diff.textContent = "Version comparison failed: " + error.message;
            }
        });
    }

    async function renderSimilar(componentId) {
        try {
            const result = await apiRequest(`/api/components/${componentId}/similar?limit=5`);
            const items = result.data?.items || [];
            if (!items.length) return;
            const heading = document.createElement("h3");
            heading.textContent = "Similar Components";
            detailContent.appendChild(heading);
            items.forEach(item => {
                const p = document.createElement("p");
                const button = document.createElement("button");
                button.className = "table-action";
                button.textContent = "View";
                button.addEventListener("click", () => showDetails(item.component_id));
                p.textContent = `${item.model} · ${item.manufacturer} · ${item.package || "-"} · shared: ${item.shared_parameters.join(", ")} `;
                p.appendChild(button);
                detailContent.appendChild(p);
            });
        } catch (error) {
            console.error("Similar components error:", error);
        }
    }

    function formatDate(value) {
        if (!value) return "-";
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("en-US");
    }

    // Update pagination
    function updatePagination() {

        pageInfo.textContent =
            `Page ${currentPage} / ${totalPages}`;

        previousPage.disabled =
            currentPage <= 1;

        nextPage.disabled =
            currentPage >= totalPages;

    }

    // Search submission
    searchForm.addEventListener("submit", event => {

        event.preventDefault();

        currentPage = 1;

        loadComponents();

    });

    // Reset search filters
    searchForm.addEventListener("reset", () => {

        setTimeout(() => {

            currentPage = 1;

            loadComponents();

        }, 0);

    });

    // Previous page
    previousPage.addEventListener("click", () => {

        if (currentPage > 1) {

            currentPage--;

            loadComponents();

        }

    });

    // Next page
    nextPage.addEventListener("click", () => {

        if (currentPage < totalPages) {

            currentPage++;

            loadComponents();

        }

    });

    // Back to Dashboard
    document.getElementById("backHome")
        .addEventListener("click", () => {

            window.location.href = "dashboard.html";

        });

    // Close component details
    document.getElementById("closeDetail")
        .addEventListener("click", () => {

            detailPanel.hidden = true;

        });

    document.getElementById("saveFilter")
        .addEventListener("click", saveCurrentFilter);

    document.getElementById("loadFilter")
        .addEventListener("click", loadSelectedFilter);

    document.getElementById("deleteFilter")
        .addEventListener("click", deleteSelectedFilter);

    // Initialize page
    loadCategories().finally(() => {
        renderSavedFilters();
        loadComponents();
    });

});
