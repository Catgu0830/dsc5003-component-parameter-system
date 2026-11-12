
// ========================================
// Component Comparison Module
// Backend API Integration
// ========================================

document.addEventListener("DOMContentLoaded", () => {

    // Check authentication
    if (!getToken()) {
        window.location.href = "../login.html";
        return;
    }

    const API_ORIGIN = API_BASE_URL;

    const selectionBody =
        document.getElementById("componentSelectionBody");

    const selectedContainer =
        document.getElementById("selectedComponents");

    const compareButton =
        document.getElementById("compareButton");

    let currentPage = 1;
    let totalPages = 1;

    // Selected components: ID -> component
    const selected = new Map();

    // Latest comparison result
    let comparisonData = null;

    // ------------------------------------
    // Helpers
    // ------------------------------------

    function getData(result) {
        return result?.data ?? result ?? {};
    }

    function getId(component) {
        return component.component_id ?? component.id;
    }

    function showMessage(id, message, type = "") {

        const element = document.getElementById(id);

        element.textContent = message;
        element.className = "form-message " + type;

    }

    function safeText(value) {

        return value === null || value === undefined || value === ""
            ? "-"
            : String(value);

    }

    // Display category labels in English
    function getCategoryLabel(category) {

        const labels = {
            resistor: "Resistor",
            capacitor: "Capacitor",
            diode: "Diode",
            transistor: "Transistor",
            ic: "Integrated Circuit",
            inductor: "Inductor",
            other: "Other"
        };

        return labels[String(category).toLowerCase()] || safeText(category);

    }

    // ------------------------------------
    // Load component list
    // ------------------------------------

    async function loadComponents() {

        selectionBody.innerHTML = `
            <tr>
                <td colspan="5">Loading components...</td>
            </tr>
        `;

        const params = new URLSearchParams();

        params.set("page", currentPage);
        params.set("page_size", "100");

        const keyword =
            document.getElementById("componentKeyword").value.trim();

        const category =
            document.getElementById("componentCategory").value;

        if (keyword) {
            params.set("keyword", keyword);
        }

        if (category) {
            params.set("category", category);
        }

        try {

            const result = await apiRequest(
                `/api/components?${params.toString()}`
            );

            const data = getData(result);

            const components = data.items || [];

            const total = Number(data.total || 0);

            const pageSize = Number(data.page_size || 100);

            totalPages = Math.max(
                1,
                Math.ceil(total / pageSize)
            );

            renderComponentList(components);

            document.getElementById("availableCount").textContent =
                `${total} components available`;

            document.getElementById("componentPageInfo").textContent =
                `Page ${currentPage} / ${totalPages}`;

            document.getElementById("componentPrev").disabled =
                currentPage <= 1;

            document.getElementById("componentNext").disabled =
                currentPage >= totalPages;

        } catch (error) {

            selectionBody.innerHTML = `
                <tr>
                    <td colspan="5">Failed to load components.</td>
                </tr>
            `;

            showMessage(
                "selectionMessage",
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
    // Render selectable component list
    // ------------------------------------

    function renderComponentList(components) {

        selectionBody.innerHTML = "";

        if (!components.length) {

            selectionBody.innerHTML = `
                <tr>
                    <td colspan="5">No components found.</td>
                </tr>
            `;

            return;

        }

        components.forEach(component => {

            const id = getId(component);

            const row = document.createElement("tr");

            const checkboxCell = document.createElement("td");

            const checkbox = document.createElement("input");

            checkbox.type = "checkbox";

            checkbox.checked = selected.has(String(id));

            checkbox.disabled =
                !checkbox.checked && selected.size >= 10;

            checkbox.addEventListener("change", () => {

                if (checkbox.checked) {

                    if (selected.size >= 10) {

                        checkbox.checked = false;

                        showMessage(
                            "selectionMessage",
                            "You can select a maximum of 10 components.",
                            "error"
                        );

                        return;

                    }

                    selected.set(String(id), component);

                } else {

                    selected.delete(String(id));

                    comparisonData = null;

                    document.getElementById("comparisonResult").hidden = true;

                }

                renderSelected();

                renderComponentList(components);

            });

            checkboxCell.appendChild(checkbox);

            row.appendChild(checkboxCell);

            const values = [
                component.model,
                component.manufacturer,
                getCategoryLabel(component.category),
                (component.parameters || []).length
            ];

            values.forEach(value => {

                const cell = document.createElement("td");

                cell.textContent = safeText(value);

                row.appendChild(cell);

            });

            selectionBody.appendChild(row);

        });

    }

    // ------------------------------------
    // Selected component display
    // ------------------------------------

    function renderSelected() {

        selectedContainer.innerHTML = "";

        document.getElementById("selectedCount").textContent =
            `Selected: ${selected.size} / 10`;

        compareButton.disabled = selected.size < 2;

        if (selected.size === 0) {

            selectedContainer.innerHTML = `
                <p class="user-info">
                    Please select components from the list above.
                </p>
            `;

            return;

        }

        selected.forEach((component, id) => {

            const chip = document.createElement("div");

            chip.className = "selected-component-chip";

            const name = document.createElement("span");

            name.textContent = component.model || `ID ${id}`;

            const remove = document.createElement("button");

            remove.type = "button";

            remove.textContent = "×";

            remove.title = "Remove";

            remove.addEventListener("click", () => {

                selected.delete(id);

                comparisonData = null;

                document.getElementById("comparisonResult").hidden = true;

                renderSelected();

                loadComponents();

            });

            chip.appendChild(name);

            chip.appendChild(remove);

            selectedContainer.appendChild(chip);

        });

    }

    // ------------------------------------
    // Compare API
    // ------------------------------------

    async function compareComponents() {

        if (selected.size < 2 || selected.size > 10) {

            showMessage(
                "selectionMessage",
                "Please select between 2 and 10 components.",
                "error"
            );

            return;

        }

        compareButton.disabled = true;

        compareButton.textContent = "Comparing...";

        try {

            const ids = Array.from(selected.keys());

            const params = new URLSearchParams();

            params.set("ids", ids.join(","));

            const result = await apiRequest(
                `/api/components/compare?${params.toString()}`
            );

            const data = getData(result);

            comparisonData = {
                components: data.components || [],
                rows: data.rows || []
            };

            if (!comparisonData.components.length) {

                throw new Error(
                    "The comparison API did not return component information."
                );

            }

            renderComparison(comparisonData);

            document.getElementById("comparisonResult").hidden = false;

            document.getElementById("comparisonResult")
                .scrollIntoView({
                    behavior: "smooth"
                });

            showMessage(
                "selectionMessage",
                "Component comparison completed successfully!",
                "success"
            );

        } catch (error) {

            showMessage(
                "selectionMessage",
                "Comparison failed: " + error.message,
                "error"
            );

        } finally {

            compareButton.disabled = selected.size < 2;

            compareButton.textContent = "Start Comparison";

        }

    }

    // ------------------------------------
    // Normalize parameter value
    // ------------------------------------

    function extractValue(value) {

        if (value === null || value === undefined) {
            return null;
        }

        if (typeof value === "object") {

            const actual =
                value.value ??
                value.value_num ??
                value.value_text;

            if (actual === null || actual === undefined) {
                return null;
            }

            return {
                value: actual,
                unit: value.unit || ""
            };

        }

        return {
            value: value,
            unit: ""
        };

    }

    function formatValue(value, defaultUnit = "") {

        const normalized = extractValue(value);

        if (!normalized) {
            return "Missing";
        }

        return `${normalized.value}${normalized.unit || defaultUnit ? " " + (normalized.unit || defaultUnit) : ""}`;

    }

    // ------------------------------------
    // Get cell value from comparison row
    // Supports object and array forms
    // ------------------------------------
    // ========================================
    // Get parameter value from comparison row
    // Safely handle null and missing values
    // ========================================

    function getRowValue(row, component, index) {

        if (!row || !component) {
            return null;
        }

        const id = String(getId(component));

        const values = row.values;

        // Case 1: API returns an array
        if (Array.isArray(values)) {

            // Ignore null and undefined entries
            const matched = values.find(item => {

                if (item === null || item === undefined) {
                    return false;
                }

                if (typeof item !== "object") {
                    return false;
                }

                const itemId =
                    item.component_id ?? item.id;

                return itemId !== undefined &&
                       itemId !== null &&
                       String(itemId) === id;

            });

            // Use the matched entry when available.
            // Otherwise, use the positional entry.
            const item = matched ?? values[index];

            if (item === null || item === undefined) {
                return null;
            }

            return extractValue(item);
        }

        // Case 2: API returns an object
        if (values && typeof values === "object") {

            const item =
                values[id] ??
                values[component.model] ??
                values[`component_${id}`];

            if (item === null || item === undefined) {
                return null;
            }

            return extractValue(item);
        }

        // Case 3: Read from component parameters
        const parameters = component.parameters || [];

        const parameterName = String(
            row.name ??
            row.parameter_name ??
            row.parameter ??
            ""
        ).toLowerCase();

        const parameter = parameters.find(item => {

            if (!item) {
                return false;
            }

            return String(item.name || "").toLowerCase()
                === parameterName;

        });

        return parameter
            ? extractValue(parameter)
            : null;
    }

    

    



    // ------------------------------------
    // Render comparison
    // ------------------------------------

    function renderComparison(data) {

        const components = data.components;

        const rows = data.rows;

        const head = document.getElementById("comparisonHead");

        const body = document.getElementById("comparisonBody");

        head.innerHTML = "";

        body.innerHTML = "";

        // Table header
        const headerRow = document.createElement("tr");

        const parameterHeader = document.createElement("th");

        parameterHeader.textContent = "Technical Parameter";

        headerRow.appendChild(parameterHeader);

        components.forEach(component => {

            const th = document.createElement("th");

            th.textContent = component.model || `ID ${getId(component)}`;

            headerRow.appendChild(th);

        });

        head.appendChild(headerRow);

        let differenceCount = 0;

        let missingCount = 0;

        rows.forEach(row => {

            const tr = document.createElement("tr");

            const parameterName =
                row.name ||
                row.parameter_name ||
                row.parameter ||
                "-";

            const nameCell = document.createElement("td");

            nameCell.textContent = parameterName;

            nameCell.className = "parameter-name-cell";

            tr.appendChild(nameCell);

            const values = components.map((component, index) =>
                getRowValue(row, component, index)
            );

            const missingIds =
                (row.missing_component_ids || []).map(String);

            const isMissing = values.some((value, index) =>
                !value ||
                missingIds.includes(String(getId(components[index])))
            );

            const normalizedValues = values
                .filter(Boolean)
                .map(item =>
                    `${item.value}|${item.unit || ""}`
                );

            const isDifferent =
                row.different !== undefined
                    ? Boolean(row.different)
                    : new Set(normalizedValues).size > 1;

            if (isDifferent) differenceCount++;

            if (isMissing) missingCount++;

            components.forEach((component, index) => {

                const td = document.createElement("td");

                const id = String(getId(component));

                const value = values[index];

                const missing =
                    !value || missingIds.includes(id);

                if (missing) {

                    td.className = "comparison-missing";

                    td.textContent = "Missing";

                } else {

                    td.textContent =
                        formatValue(value, row.unit || "");

                    if (isDifferent) {

                        td.className = "comparison-different";

                    }

                }

                tr.appendChild(td);

            });

            body.appendChild(tr);

        });

        // Statistics
        document.getElementById("statComponents").textContent =
            components.length;

        document.getElementById("statParameters").textContent =
            rows.length;

        document.getElementById("statDifferences").textContent =
            differenceCount;

        document.getElementById("statMissing").textContent =
            missingCount;

    }

    // ------------------------------------
    // Export comparison
    // ------------------------------------

    async function exportComparison(format) {

        if (!comparisonData || selected.size < 2) {

            showMessage(
                "exportMessage",
                "Please complete a component comparison first.",
                "error"
            );

            return;

        }

        showMessage(
            "exportMessage",
            `Generating ${format.toUpperCase()} file...`
        );

        try {

            const ids = Array.from(selected.keys());

            const params = new URLSearchParams();

            params.set("ids", ids.join(","));

            params.set("format", format);

            const response = await fetch(
                `${API_ORIGIN}/api/export/compare?${params.toString()}`,
                {
                    method: "GET",
                    headers: {
                        Authorization: `Bearer ${getToken()}`
                    }
                }
            );

            if (!response.ok) {

                let message =
                    `Export failed: HTTP ${response.status}`;

                try {

                    const error = await response.json();

                    message = error.message || message;

                } catch {
                    // Keep HTTP error
                }

                if (response.status === 401) {

                    clearAuth();

                    window.location.href = "../login.html";

                    return;

                }

                throw new Error(message);

            }

            const blob = await response.blob();

            const url = URL.createObjectURL(blob);

            const link = document.createElement("a");

            link.href = url;

            link.download =
                `component_comparison_${Date.now()}.${format}`;

            document.body.appendChild(link);

            link.click();

            link.remove();

            URL.revokeObjectURL(url);

            showMessage(
                "exportMessage",
                `${format.toUpperCase()} export completed successfully!`,
                "success"
            );

        } catch (error) {

            showMessage(
                "exportMessage",
                error.message,
                "error"
            );

        }

    }

    // ------------------------------------
    // Event listeners
    // ------------------------------------

    compareButton.addEventListener("click", compareComponents);

    document.getElementById("searchComponents")
        .addEventListener("click", () => {

            currentPage = 1;

            loadComponents();

        });

    document.getElementById("resetSearch")
        .addEventListener("click", () => {

            document.getElementById("componentKeyword").value = "";

            document.getElementById("componentCategory").value = "";

            currentPage = 1;

            loadComponents();

        });

    document.getElementById("componentKeyword")
        .addEventListener("keydown", event => {

            if (event.key === "Enter") {

                currentPage = 1;

                loadComponents();

            }

        });

    document.getElementById("clearSelection")
        .addEventListener("click", () => {

            selected.clear();

            comparisonData = null;

            document.getElementById("comparisonResult").hidden = true;

            renderSelected();

            loadComponents();

        });

    document.getElementById("componentPrev")
        .addEventListener("click", () => {

            if (currentPage > 1) {

                currentPage--;

                loadComponents();

            }

        });

    document.getElementById("componentNext")
        .addEventListener("click", () => {

            if (currentPage < totalPages) {

                currentPage++;

                loadComponents();

            }

        });

    document.getElementById("refreshComparison")
        .addEventListener("click", compareComponents);

    document.querySelectorAll("[data-format]")
        .forEach(button => {

            button.addEventListener("click", () => {

                exportComparison(button.dataset.format);

            });

        });

    document.getElementById("backHome")
        .addEventListener("click", () => {

            window.location.href = "dashboard.html";

        });

    // ------------------------------------
    // Initialization
    // ------------------------------------

    renderSelected();

    loadComponents();

});
