
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

            detailPanel.hidden = false;

            detailPanel.scrollIntoView({
                behavior: "smooth"
            });

        } catch (error) {

            alert("Failed to retrieve component details: " + error.message);

        }

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

    // Initialize page
    loadCategories().finally(loadComponents);

});
