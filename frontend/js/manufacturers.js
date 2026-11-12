// Manufacturer management.

document.addEventListener("DOMContentLoaded", async () => {

    if (!getToken()) {
        window.location.href = "../login.html";
        return;
    }

    let currentUser = null;

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

    async function loadManufacturers() {
        try {
            const response = await apiRequest("/api/manufacturers?page=1&page_size=100");
            const data = response.data || {};
            const items = data.items || [];
            document.getElementById("manufacturerCount").textContent = `${data.total ?? items.length} manufacturer(s)`;
            renderManufacturers(items);
        } catch (error) {
            document.getElementById("manufacturerTableBody").innerHTML =
                '<tr><td colspan="5">Unable to load manufacturers.</td></tr>';
            show("manufacturerListMessage", error.message, "error");
        }
    }

    function renderManufacturers(items) {
        const body = document.getElementById("manufacturerTableBody");
        body.innerHTML = "";
        if (!items.length) {
            body.innerHTML = '<tr><td colspan="5">No manufacturers found.</td></tr>';
            return;
        }
        const canEdit = currentUser.role === "admin" || currentUser.role === "auditor";
        const canDelete = currentUser.role === "admin";
        items.forEach(item => {
            const row = document.createElement("tr");

            const idCell = document.createElement("td");
            idCell.textContent = item.manufacturer_id;
            row.appendChild(idCell);

            const nameCell = document.createElement("td");
            const name = document.createElement("input");
            name.className = "table-input";
            name.value = item.name || "";
            name.disabled = !canEdit;
            nameCell.appendChild(name);
            row.appendChild(nameCell);

            const shortCell = document.createElement("td");
            const shortName = document.createElement("input");
            shortName.className = "table-input";
            shortName.value = item.short_name || "";
            shortName.disabled = !canEdit;
            shortCell.appendChild(shortName);
            row.appendChild(shortCell);

            const websiteCell = document.createElement("td");
            const website = document.createElement("input");
            website.className = "table-input";
            website.value = item.website || "";
            website.disabled = !canEdit;
            websiteCell.appendChild(website);
            row.appendChild(websiteCell);

            const actionCell = document.createElement("td");
            if (canEdit) {
                const save = document.createElement("button");
                save.className = "primary-button table-action";
                save.textContent = "Save";
                save.addEventListener("click", async () => {
                    try {
                        await apiRequest(`/api/manufacturers/${item.manufacturer_id}`, {
                            method: "PUT",
                            body: {
                                name: name.value.trim(),
                                short_name: shortName.value.trim() || null,
                                website: website.value.trim() || null
                            }
                        });
                        show("manufacturerListMessage", "Manufacturer updated.", "success");
                        await loadManufacturers();
                    } catch (error) {
                        show("manufacturerListMessage", error.message, "error");
                    }
                });
                actionCell.appendChild(save);
            }
            if (canDelete) {
                const remove = document.createElement("button");
                remove.className = "danger-button table-action";
                remove.textContent = "Delete";
                remove.addEventListener("click", async () => {
                    if (!confirm(`Delete manufacturer "${item.name}"?`)) return;
                    try {
                        await apiRequest(`/api/manufacturers/${item.manufacturer_id}`, {
                            method: "DELETE",
                            body: { confirm: true }
                        });
                        show("manufacturerListMessage", "Manufacturer deleted.", "success");
                        await loadManufacturers();
                    } catch (error) {
                        show("manufacturerListMessage", error.message, "error");
                    }
                });
                actionCell.appendChild(remove);
            }
            row.appendChild(actionCell);
            body.appendChild(row);
        });
    }

    document.getElementById("manufacturerForm").addEventListener("submit", async event => {
        event.preventDefault();
        try {
            await apiRequest("/api/manufacturers", {
                method: "POST",
                body: {
                    name: document.getElementById("manufacturerName").value.trim(),
                    short_name: document.getElementById("manufacturerShortName").value.trim() || null,
                    website: document.getElementById("manufacturerWebsite").value.trim() || null
                }
            });
            show("manufacturerMessage", "Manufacturer created.", "success");
            document.getElementById("manufacturerForm").reset();
            await loadManufacturers();
        } catch (error) {
            show("manufacturerMessage", error.message, "error");
        }
    });

    document.getElementById("backHome").addEventListener("click", () => {
        window.location.href = "dashboard.html";
    });

    try {
        await loadCurrentUser();
        if (currentUser.role === "user") {
            document.getElementById("manufacturerForm").querySelectorAll("input, button")
                .forEach(element => element.disabled = true);
        }
        await loadManufacturers();
    } catch (error) {
        show("manufacturerListMessage", error.message, "error");
        if (error.message.includes("401")) {
            clearAuth();
            window.location.href = "../login.html";
        }
    }
});
