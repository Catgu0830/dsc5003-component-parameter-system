// Administrator user management.

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

    function formatDate(value) {
        if (!value) return "-";
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("en-US");
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
        return currentUser;
    }

    async function loadUsers() {
        try {
            const response = await apiRequest("/api/users?page=1&page_size=100");
            const data = response.data || {};
            const items = data.items || [];
            document.getElementById("userCount").textContent = `${data.total ?? items.length} user(s)`;
            renderUsers(items);
        } catch (error) {
            document.getElementById("userTableBody").innerHTML =
                '<tr><td colspan="7">Unable to load users.</td></tr>';
            show("userMessage", error.message, "error");
        }
    }

    function renderUsers(items) {
        const body = document.getElementById("userTableBody");
        body.innerHTML = "";
        if (!items.length) {
            body.innerHTML = '<tr><td colspan="7">No users found.</td></tr>';
            return;
        }
        items.forEach(user => {
            const row = document.createElement("tr");

            [user.user_id, user.username].forEach(value => {
                const cell = document.createElement("td");
                cell.textContent = value ?? "-";
                row.appendChild(cell);
            });

            const roleCell = document.createElement("td");
            const role = document.createElement("select");
            ["user", "auditor", "admin"].forEach(value => {
                const option = document.createElement("option");
                option.value = value;
                option.textContent = value;
                role.appendChild(option);
            });
            role.value = user.role;
            roleCell.appendChild(role);
            row.appendChild(roleCell);

            const activeCell = document.createElement("td");
            const active = document.createElement("input");
            active.type = "checkbox";
            active.checked = Boolean(user.is_active);
            activeCell.appendChild(active);
            row.appendChild(activeCell);

            const loginCell = document.createElement("td");
            loginCell.textContent = formatDate(user.last_login_time);
            row.appendChild(loginCell);

            const passwordCell = document.createElement("td");
            const password = document.createElement("input");
            password.type = "password";
            password.placeholder = "Optional";
            password.className = "table-input";
            passwordCell.appendChild(password);
            row.appendChild(passwordCell);

            const actionCell = document.createElement("td");
            const save = document.createElement("button");
            save.className = "primary-button table-action";
            save.textContent = "Save";
            save.addEventListener("click", async () => {
                const payload = {
                    role: role.value,
                    is_active: active.checked
                };
                if (password.value.trim()) payload.password = password.value;
                try {
                    await apiRequest(`/api/users/${user.user_id}`, {
                        method: "PUT",
                        body: payload
                    });
                    show("userMessage", `User ${user.username} updated.`, "success");
                    await loadUsers();
                } catch (error) {
                    show("userMessage", error.message, "error");
                }
            });
            actionCell.appendChild(save);
            row.appendChild(actionCell);

            body.appendChild(row);
        });
    }

    document.getElementById("createUserForm").addEventListener("submit", async event => {
        event.preventDefault();
        try {
            await apiRequest("/api/users", {
                method: "POST",
                body: {
                    username: document.getElementById("newUsername").value.trim(),
                    password: document.getElementById("newPassword").value,
                    role: document.getElementById("newRole").value
                }
            });
            show("createMessage", "User created.", "success");
            document.getElementById("createUserForm").reset();
            await loadUsers();
        } catch (error) {
            show("createMessage", error.message, "error");
        }
    });

    document.getElementById("backHome").addEventListener("click", () => {
        window.location.href = "dashboard.html";
    });

    try {
        await loadCurrentUser();
        if (currentUser.role !== "admin") {
            document.querySelectorAll("form, button").forEach(element => element.disabled = true);
            show("userMessage", "Only administrators can manage users.", "error");
            return;
        }
        await loadUsers();
    } catch (error) {
        show("userMessage", error.message, "error");
        if (error.message.includes("401")) {
            clearAuth();
            window.location.href = "../login.html";
        }
    }
});
