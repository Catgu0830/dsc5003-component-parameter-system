// Administrator component CRUD.

document.addEventListener("DOMContentLoaded", async () => {

    if (!getToken()) {
        window.location.href = "../login.html";
        return;
    }

    let currentUser = null;
    let currentPage = 1;
    let totalPages = 1;

    function show(id, text, type = "") {
        const element = document.getElementById(id);
        element.textContent = text;
        element.className = "form-message " + type;
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

    async function loadCategories() {
        const response = await apiRequest("/api/categories");
        const select = document.getElementById("componentCategory");
        select.innerHTML = '<option value="">Select a category</option>';
        (response.data?.items || []).forEach(category => {
            const option = document.createElement("option");
            option.value = category.name;
            option.textContent = category.name;
            select.appendChild(option);
        });
    }

    async function loadComponents() {
        try {
            const response = await apiRequest(`/api/components?page=${currentPage}&page_size=50`);
            const data = response.data || {};
            const items = data.items || [];
            document.getElementById("componentCount").textContent = `${data.total ?? items.length} component(s)`;
            renderComponents(items);
            totalPages = Math.max(1, Math.ceil(Number(data.total ?? 0) / Number(data.page_size ?? 50)));
            document.getElementById("pageInfo").textContent = `Page ${currentPage} / ${totalPages}`;
            document.getElementById("prevPage").disabled = currentPage <= 1;
            document.getElementById("nextPage").disabled = currentPage >= totalPages;
        } catch (error) {
            document.getElementById("componentTableBody").innerHTML =
                '<tr><td colspan="7">Unable to load components.</td></tr>';
            show("componentListMessage", error.message, "error");
        }
    }

    function renderComponents(items) {
        const body = document.getElementById("componentTableBody");
        body.innerHTML = "";
        if (!items.length) {
            body.innerHTML = '<tr><td colspan="7">No components found.</td></tr>';
            return;
        }
        items.forEach(component => {
            const row = document.createElement("tr");
            [
                component.component_id,
                component.model,
                component.manufacturer,
                component.category,
                component.package,
                (component.parameters || []).length
            ].forEach(value => {
                const cell = document.createElement("td");
                cell.textContent = value ?? "-";
                row.appendChild(cell);
            });

            const actions = document.createElement("td");
            const edit = document.createElement("button");
            edit.className = "secondary-button table-action";
            edit.textContent = "Edit";
            edit.addEventListener("click", () => loadForEdit(component.component_id));
            actions.appendChild(edit);

            const remove = document.createElement("button");
            remove.className = "danger-button table-action";
            remove.textContent = "Delete";
            remove.addEventListener("click", async () => {
                if (!confirm(`Delete component "${component.model}"? Parameters will also be removed.`)) return;
                try {
                    await apiRequest(`/api/components/${component.component_id}`, {
                        method: "DELETE",
                        body: { confirm: true }
                    });
                    show("componentListMessage", "Component deleted.", "success");
                    await loadComponents();
                } catch (error) {
                    show("componentListMessage", error.message, "error");
                }
            });
            actions.appendChild(remove);
            row.appendChild(actions);
            body.appendChild(row);
        });
    }

    async function loadForEdit(componentId) {
        try {
            const response = await apiRequest(`/api/components/${componentId}`);
            const component = response.data;
            document.getElementById("componentId").value = component.component_id;
            document.getElementById("componentModel").value = component.model || "";
            document.getElementById("componentManufacturer").value = component.manufacturer || "";
            document.getElementById("componentCategory").value = component.category || "";
            document.getElementById("componentPackage").value = component.package || "";
            document.getElementById("componentDescription").value = component.description || "";
            document.getElementById("componentFormTitle").textContent = `Edit Component #${componentId}`;
            document.getElementById("cancelEdit").hidden = false;
            document.getElementById("componentForm").scrollIntoView({ behavior: "smooth" });
        } catch (error) {
            show("componentMessage", error.message, "error");
        }
    }

    function resetForm() {
        document.getElementById("componentForm").reset();
        document.getElementById("componentId").value = "";
        document.getElementById("componentFormTitle").textContent = "Add Component";
        document.getElementById("cancelEdit").hidden = true;
        show("componentMessage", "");
    }

    document.getElementById("componentForm").addEventListener("submit", async event => {
        event.preventDefault();
        const componentId = document.getElementById("componentId").value;
        const payload = {
            model: document.getElementById("componentModel").value.trim(),
            manufacturer: document.getElementById("componentManufacturer").value.trim(),
            category: document.getElementById("componentCategory").value,
            package: document.getElementById("componentPackage").value.trim() || null,
            description: document.getElementById("componentDescription").value.trim() || null
        };
        try {
            if (componentId) {
                await apiRequest(`/api/components/${componentId}`, { method: "PUT", body: payload });
                show("componentMessage", "Component updated.", "success");
            } else {
                await apiRequest("/api/components", { method: "POST", body: payload });
                show("componentMessage", "Component created.", "success");
            }
            resetForm();
            await loadComponents();
        } catch (error) {
            show("componentMessage", error.message, "error");
        }
    });

    document.getElementById("cancelEdit").addEventListener("click", resetForm);

    document.getElementById("prevPage").addEventListener("click", () => {
        if (currentPage > 1) {
            currentPage--;
            loadComponents();
        }
    });

    document.getElementById("nextPage").addEventListener("click", () => {
        if (currentPage < totalPages) {
            currentPage++;
            loadComponents();
        }
    });

    document.getElementById("backHome").addEventListener("click", () => {
        window.location.href = "dashboard.html";
    });

    try {
        await loadCurrentUser();
        if (currentUser.role !== "admin") {
            document.querySelectorAll("form, button").forEach(element => element.disabled = true);
            show("componentListMessage", "Only administrators can manage components.", "error");
            return;
        }
        await loadCategories();
        await loadComponents();
    } catch (error) {
        show("componentListMessage", error.message, "error");
        if (error.message.includes("401")) {
            clearAuth();
            window.location.href = "../login.html";
        }
    }
});
